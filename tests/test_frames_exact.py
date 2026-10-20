"""Foto prese da un video, "Più nitida" e scelte cambiate: i file in export devono essere
ESATTAMENTE i fotogrammi scelti, e una scelta cambiata deve togliere/rifare le copie giuste.

Per sapere quale fotogramma c'è in un file, lo si confronta con tutti i fotogrammi del video
decodificato di fila dall'inizio (stessa conversione colore dell'app, nessun salto -ss):
vince il più simile, con un margine netto sul secondo."""
from __future__ import annotations

import random
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageFilter, ImageStat
from PySide6.QtCore import Qt

import exporter
import frames
from test_core import FF, LIVE, LONG
from test_ui import (PHOTO1, click, exported, exports_done, go, open_folder, press,  # noqa: F401
                     pump, qapp, sd, sd_template, wait, win)

SMALL = (160, 90)


# ------------------------------------------------------------------ nomi attesi in export
# export/Foto e export/Video, ogni nome con data e ora di scatto davanti: calcolati qui
# dal nome DJI (ora della fotocamera) e dal fotogramma, senza chiedere all'app.

def shot_time(name: str) -> datetime:
    """Ora di scatto scritta nel nome DJI (DJI_YYYYMMDDHHMMSS_...)."""
    return datetime.strptime(re.search(r"DJI_(\d{14})_", name).group(1), "%Y%m%d%H%M%S")


def album(name: str, when: datetime) -> str:
    from album_names import nodate
    return f"{when:%Y%m%d_%H%M%S}_{nodate(name)}"


def photo_rel(name: str) -> str:
    """Foto copiata così com'è: export/Foto/<data ora>_<nome>."""
    return f"{exporter.PHOTO_SUBDIR}/{album(name, shot_time(name))}"


def video_rel(name: str) -> str:
    """Video copiato: export/Video/<ora d'inizio>_<nome>."""
    return f"{exporter.VIDEO_SUBDIR}/{album(name, shot_time(name))}"


def frame_rel(clip: Path, n: int, snapshot: bool = True) -> str:
    """Fotogramma n (da 0) del video: export/Foto/<ora esatta del fotogramma>_<nome>.
    snapshot (Prendi foto): <video>_fNNNN.jpg; Live: <video>.jpg."""
    when = shot_time(clip.name) + timedelta(seconds=float(n / frames.probe(clip).fps))
    name = f"{clip.stem}_f{n + 1:04d}.jpg" if snapshot else f"{clip.stem}.jpg"
    return f"{exporter.PHOTO_SUBDIR}/{album(name, when)}"


def decode_all(clip: Path) -> list[Image.Image]:
    """Tutti i fotogrammi, di fila, ridotti: il riferimento indipendente dai salti dell'app."""
    info = frames.probe(clip)
    raw = subprocess.run([FF, "-v", "error", "-i", str(clip), "-map", "0:v:0",
                          "-vf", f"{frames._SCALE_EXACT},format=rgb24", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    size = info.width * info.height * 3
    out = [Image.frombytes("RGB", (info.width, info.height), raw[k * size:(k + 1) * size])
           .convert("L").resize(SMALL, Image.BILINEAR) for k in range(len(raw) // size)]
    assert len(out) == info.frames
    return out


def which(img: Image.Image, ref: list[Image.Image]) -> int:
    """Indice del fotogramma che è img (con margine netto, altrimenti il test non vale)."""
    small = img.convert("L").resize(SMALL, Image.BILINEAR)
    diffs = [ImageStat.Stat(ImageChops.difference(small, r)).mean[0] for r in ref]
    order = sorted(range(len(diffs)), key=diffs.__getitem__)
    best, second = diffs[order[0]], diffs[order[1]]
    assert second > 2 * best + 0.5, f"fotogrammi non distinguibili: {best:.2f} vs {second:.2f}"
    return order[0]


def clip_of(w, stem: str) -> Path:
    return w.root / "DCIM" / "DJI_001" / f"{stem}.MP4"


def snap_file(w, n: int) -> Path:
    """La foto presa dal fotogramma n del video LONG, col suo nome esatto in export/Foto."""
    f = w.export_dir / frame_rel(clip_of(w, LONG), n)
    assert f.is_file(), (f, exported(w))
    return f


def shown_image(qa, w) -> Image.Image:
    key = (w.current().id, w.shown_frame)
    assert wait(qa, lambda: key in w.exact_cache), "fotogramma esatto non arrivato"
    pump(qa, 0.1)
    q = w.image_view.item.pixmap().toImage().convertToFormat(w.image_view.item.pixmap().toImage().Format.Format_RGB888)
    return Image.frombytes("RGB", (q.width(), q.height()), bytes(q.constBits()), "raw", "RGB", q.bytesPerLine())


@pytest.fixture(scope="module")
def video_ref(sd_template) -> list[Image.Image]:
    return decode_all(sd_template / "DCIM" / "DJI_001" / f"{LONG}.MP4")


@pytest.fixture(scope="module")
def live_ref(sd_template) -> list[Image.Image]:
    return decode_all(sd_template / "DCIM" / "DJI_001" / f"{LIVE}.MP4")


# ------------------------------------------------------------------ foto prese da un video (F)

def test_video_snapshots_are_exactly_the_frames_shown(qapp, win, sd, video_ref):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    taken = []
    win.on_strip_picked(30)                       # clic sulla striscia
    pump(qapp, 0.2)
    taken.append(win.current_frame())
    assert which(shown_image(qapp, win), video_ref) == 30
    press(qapp, win, Qt.Key_F)
    for _ in range(5):                            # → cinque volte
        press(qapp, win, Qt.Key_Down)
    taken.append(win.current_frame())
    assert which(shown_image(qapp, win), video_ref) == 35
    click(qapp, win, win.btn_snap)                # pulsante 📷
    press(qapp, win, Qt.Key_Down, Qt.ShiftModifier)   # Maiusc+→ = 10 avanti
    taken.append(win.current_frame())
    press(qapp, win, Qt.Key_F)
    exports_done(qapp, win)
    assert taken == [30, 35, 45]
    assert exported(win) == sorted(frame_rel(clip_of(win, LONG), n) for n in taken)
    for n in taken:
        assert which(Image.open(snap_file(win, n)), video_ref) == n
    assert sorted(win.strip.marks) == taken


# ------------------------------------------------------------------ Più nitida (P)

SHARP = 50   # nel video di prova solo questo fotogramma è a fuoco


@pytest.fixture(scope="module")
def blurry_sd(tmp_path_factory) -> Path:
    """Video di 4 s (quindi "video", non Live): una trama che scorre, tutta sfocata tranne
    il fotogramma SHARP."""
    root = tmp_path_factory.mktemp("blur") / "sd"
    dcim = root / "DCIM" / "DJI_001"
    dcim.mkdir(parents=True)
    w, h, n = 320, 180, 120
    rnd = random.Random(7)
    tex = Image.frombytes("L", (w, h), bytes(rnd.randrange(256) for _ in range(w * h)))
    tex = tex.filter(ImageFilter.GaussianBlur(0.6)).convert("RGB")
    raw = bytearray()
    for k in range(n):
        f = ImageChops.offset(tex, k * 2, 0)      # si sposta: ogni fotogramma è diverso
        if k != SHARP:
            f = f.filter(ImageFilter.GaussianBlur(2.5))
        raw += f.tobytes()
    subprocess.run([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                    "-r", "30000/1001", "-i", "-", "-c:v", "libx264", "-crf", "2", "-pix_fmt", "yuv420p",
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    "-movflags", "+faststart", str(dcim / f"{LONG}.MP4")], input=bytes(raw), check=True)
    return root


@pytest.fixture
def bsd(blurry_sd, tmp_path) -> Path:
    root = tmp_path / "sd"
    shutil.copytree(blurry_sd, root)
    return root


def press_p_and_wait(qa, w) -> int:
    before = w.frame_label.text()
    press(qa, w, Qt.Key_P)
    assert wait(qa, lambda: "cerco" not in w.frame_label.text() and w.frame_label.text() != before
                or w.bg._work_queue.empty() and not w._preview_busy, 20)
    pump(qa, 0.5)
    return w.current_frame()


@pytest.mark.parametrize("start", [SHARP - 6, SHARP - 2, SHARP + 4, SHARP + 6])
def test_sharpest_finds_the_sharp_frame_nearby(qapp, win, bsd, start):
    open_folder(qapp, win, bsd)
    go(qapp, win, f"{LONG}.MP4")
    win.on_strip_picked(start)
    pump(qapp, 0.2)
    assert wait(qapp, lambda: win.current_frame() == start)
    press(qapp, win, Qt.Key_P)
    assert wait(qapp, lambda: win.current_frame() == SHARP, 20), \
        f"P da {start}: resta su {win.current_frame()}, non trova {SHARP}"


def test_sharpest_stays_near_when_sharp_frame_is_far(qapp, win, bsd):
    """Fuori dai ±6 fotogrammi non salta lontano: cerca solo lì vicino, come dice l'aiuto."""
    open_folder(qapp, win, bsd)
    go(qapp, win, f"{LONG}.MP4")
    win.on_strip_picked(90)
    pump(qapp, 0.2)
    press(qapp, win, Qt.Key_P)
    pump(qapp, 3)
    assert abs(win.current_frame() - 90) <= 6


def test_sharpest_then_take_photo_exports_the_sharp_frame(qapp, win, bsd):
    ref = decode_all(bsd / "DCIM" / "DJI_001" / f"{LONG}.MP4")
    open_folder(qapp, win, bsd)
    go(qapp, win, f"{LONG}.MP4")
    win.on_strip_picked(SHARP - 3)
    pump(qapp, 0.2)
    press(qapp, win, Qt.Key_P)
    assert wait(qapp, lambda: win.current_frame() == SHARP, 20)
    press(qapp, win, Qt.Key_F)
    exports_done(qapp, win)
    assert which(Image.open(snap_file(win, SHARP)), ref) == SHARP


def test_sharpest_on_live_changes_the_photo_that_yes_saves(qapp, win, sd, live_ref):
    """Su una Live, P sposta la foto scelta: SÌ salva quella trovata."""
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    win.on_strip_picked(20)
    pump(qapp, 0.2)
    press(qapp, win, Qt.Key_P)
    assert wait(qapp, lambda: "cerco" not in win.frame_label.text(), 20)
    pump(qapp, 0.5)
    found = win.current_frame()
    assert abs(found - 20) <= 6
    expected = frames.sharpest_near(sd / "DCIM" / "DJI_001" / f"{LIVE}.MP4",
                                    win.infos[win.current().id], 20)
    assert found == expected
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    rel = frame_rel(sd / "DCIM" / "DJI_001" / f"{LIVE}.MP4", found, snapshot=False)
    assert exported(win) == [rel]
    assert which(Image.open(win.export_dir / rel), live_ref) == found


# ------------------------------------------------------------------ scelte cambiate

def test_video_back_and_take_another_frame_then_remove_the_first(qapp, win, sd, video_ref):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    win.on_strip_picked(30)
    pump(qapp, 0.2)
    press(qapp, win, Qt.Key_F)
    go(qapp, win, PHOTO1)                          # va altrove…
    go(qapp, win, f"{LONG}.MP4")                   # …e torna indietro
    win.on_strip_picked(80)
    pump(qapp, 0.2)
    press(qapp, win, Qt.Key_F)
    exports_done(qapp, win)
    assert which(Image.open(snap_file(win, 30)), video_ref) == 30
    assert which(Image.open(snap_file(win, 80)), video_ref) == 80
    win.remove_snap(f"{win.current().id}#f30")     # ✕ sulla prima foto presa
    exports_done(qapp, win)
    assert exported(win) == [frame_rel(clip_of(win, LONG), 80)]
    assert which(Image.open(snap_file(win, 80)), video_ref) == 80


def test_video_snapshots_taken_backwards_sort_in_frame_order(qapp, win, sd, video_ref):
    """Foto prese dallo stesso video al contrario (prima la più avanti): in export/Foto,
    in ordine di nome, sono comunque in ordine di fotogramma (anche due nello stesso secondo)."""
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    order = [80, 40, 35]                           # 13:23:02, 13:23:01, 13:23:01
    for n in order:
        win.on_strip_picked(n)
        pump(qapp, 0.2)
        assert wait(qapp, lambda: win.current_frame() == n)
        press(qapp, win, Qt.Key_F)
    exports_done(qapp, win)
    expected = [frame_rel(clip_of(win, LONG), n) for n in sorted(order)]
    assert exported(win) == expected               # exported() è già in ordine di nome
    names = sorted(p.name for p in (win.export_dir / exporter.PHOTO_SUBDIR).iterdir())
    assert names == [Path(r).name for r in expected]
    assert [which(Image.open(win.export_dir / exporter.PHOTO_SUBDIR / f), video_ref) for f in names] \
        == sorted(order)


def test_video_snapshots_stay_when_video_is_rejected(qapp, win, sd):
    """Come dice l'aiuto: le foto prese restano in export anche se il video è NO."""
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    win.on_strip_picked(12)
    pump(qapp, 0.2)
    press(qapp, win, Qt.Key_F)
    click(qapp, win, win.btn_no)
    exports_done(qapp, win)
    assert exported(win) == [frame_rel(clip_of(win, LONG), 12)]


def test_video_yes_then_back_and_no_removes_the_video(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert exported(win) == [video_rel(f"{LONG}.MP4")]
    go(qapp, win, f"{LONG}.MP4")
    click(qapp, win, win.btn_no)
    exports_done(qapp, win)
    assert exported(win) == []


@pytest.mark.parametrize("button", ["btn_no", "btn_skip"])
def test_live_yes_then_changed_mind_removes_the_photo(qapp, win, sd, button):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    win.on_strip_picked(20)
    pump(qapp, 0.2)
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert exported(win) == [frame_rel(clip_of(win, LIVE), 20, snapshot=False)]
    go(qapp, win, f"{LIVE}.MP4")
    click(qapp, win, getattr(win, button))
    exports_done(qapp, win)
    assert exported(win) == []


def test_live_yes_back_new_frame_yes_then_undo_restores_the_first(qapp, win, sd, live_ref):
    """Sì su 20, poi torno e Sì su 70: in export SOLO 70. Z: di nuovo SOLO 20."""
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    win.on_strip_picked(20)
    pump(qapp, 0.2)
    click(qapp, win, win.btn_yes)
    go(qapp, win, f"{LIVE}.MP4")
    win.on_strip_picked(70)
    pump(qapp, 0.2)
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    f70, f20 = (frame_rel(clip_of(win, LIVE), n, snapshot=False) for n in (70, 20))
    assert f70 != f20                                # ore diverse: 13:22:06 e 13:22:04
    assert exported(win) == [f70]
    assert which(Image.open(win.export_dir / f70), live_ref) == 70
    press(qapp, win, Qt.Key_Z)
    exports_done(qapp, win)
    assert exported(win) == [f20]
    assert which(Image.open(win.export_dir / f20), live_ref) == 20


@pytest.mark.parametrize("button", ["btn_no", "btn_skip"])
def test_photo_yes_then_changed_mind_removes_the_copy(qapp, win, sd, button):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert exported(win) == [photo_rel(PHOTO1)]
    go(qapp, win, PHOTO1)
    click(qapp, win, getattr(win, button))
    exports_done(qapp, win)
    assert exported(win) == []


def test_photo_yes_then_trash_moves_original_and_removes_copy_undo_restores(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    original = win.current().image
    data = original.read_bytes()
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_trash)
    exports_done(qapp, win)
    assert exported(win) == []
    assert not original.exists()
    assert (sd / exporter.TRASH_DIR / original.relative_to(sd)).read_bytes() == data
    press(qapp, win, Qt.Key_Z)                      # annulla: torna al Sì
    exports_done(qapp, win)
    assert original.read_bytes() == data            # originale al suo posto, identico
    assert exported(win) == [photo_rel(PHOTO1)]
    assert (win.export_dir / photo_rel(PHOTO1)).read_bytes() == data
