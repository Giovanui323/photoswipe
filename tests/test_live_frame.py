"""Live: la foto copiata in export è DAVVERO il fotogramma scelto sulla striscia.

Il video di prova è "numerato": ogni fotogramma ha una luminosità diversa. Il riferimento è il
video decodificato tutto di fila (senza i salti che usa l'app), così dall'immagine esportata si
ricava quale fotogramma è stato copiato e si confronta con quello scelto e con quello a schermo."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageStat
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

import frames
from test_core import FF, LIVE
from test_ui import click, exports_done, go, open_folder, press, pump, qapp, wait, win  # noqa: F401

CAM_FRAME = 40   # fotogramma che la "fotocamera" mostra come foto (anteprima .SCR)
W, H = 320, 180
REF: list[float] = []   # luminosità di ogni fotogramma, decodificando il video dall'inizio


def nearest(mean: float) -> int:
    return min(range(len(REF)), key=lambda k: abs(REF[k] - mean))


def frame_of(img: Image.Image) -> int:
    """Quale fotogramma è: il più vicino per luminosità (tra due vicini ci sono ~2,3 livelli)."""
    return nearest(ImageStat.Stat(img.convert("L")).mean[0])


@pytest.fixture(scope="module")
def numbered_sd(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("livenum") / "sd"
    dcim = root / "DCIM" / "DJI_001"
    dcim.mkdir(parents=True)
    clip = dcim / f"{LIVE}.MP4"
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=black:size={W}x{H}:rate=30000/1001:duration=3.036",
                    "-vf", "geq=lum='16+2*N':cb=128:cr=128",
                    "-c:v", "libx264", "-crf", "4", "-pix_fmt", "yuv420p",
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    "-movflags", "+faststart", str(clip)], check=True)
    info = frames.probe(clip)
    # stessa conversione colore dell'app, ma TUTTO di fila dall'inizio: nessun salto (-ss)
    raw = subprocess.run([FF, "-v", "error", "-i", str(clip), "-map", "0:v:0",
                          "-vf", f"{frames._SCALE_EXACT},format=rgb24", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    size = W * H * 3
    REF[:] = [ImageStat.Stat(Image.frombytes("RGB", (W, H), raw[k * size:(k + 1) * size])
                             .convert("L")).mean[0] for k in range(len(raw) // size)]
    assert len(REF) == info.frames >= 80
    assert min(b - a for a, b in zip(REF[5:], REF[6:])) > 1.5   # ogni fotogramma si distingue
    thm = root / "MISC" / "THM" / "DJI_001"
    thm.mkdir(parents=True)
    frames.frame_rgb(clip, info, CAM_FRAME).save(thm / f"{LIVE}.SCR", "JPEG", quality=95)
    return root


@pytest.fixture
def nsd(numbered_sd, tmp_path) -> Path:
    root = tmp_path / "sd"
    shutil.copytree(numbered_sd, root)
    return root


def exported_live(w) -> Image.Image:
    jpgs = sorted(w.export_dir.rglob(f"{LIVE}*.jpg"))
    assert len(jpgs) == 1, jpgs
    return Image.open(jpgs[0])


def shown(qa, w) -> int:
    """Fotogramma che si vede a schermo (quello esatto, a risoluzione piena)."""
    key = (w.current().id, w.shown_frame)
    assert wait(qa, lambda: key in w.exact_cache), "fotogramma esatto non arrivato"
    pump(qa, 0.1)
    img = w.image_view.item.pixmap().toImage()
    rgb = [QColor(img.pixel(x * img.width() // 8, y * img.height() // 6))
           for x in range(1, 8) for y in range(1, 6)]
    px = Image.new("RGB", (len(rgb), 1))
    px.putdata([(c.red(), c.green(), c.blue()) for c in rgb])
    return frame_of(px)


def test_live_without_changes_exports_the_camera_frame(qapp, win, nsd):
    open_folder(qapp, win, nsd)
    go(qapp, win, f"{LIVE}.MP4")
    assert win.camera_frames[win.current().id] == CAM_FRAME
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert frame_of(exported_live(win)) == CAM_FRAME


@pytest.mark.parametrize("how, expected", [
    ("shift_right", CAM_FRAME + 10),          # Maiusc+→ = 10 avanti
    ("left_x3", CAM_FRAME - 3),               # ← tre volte
    ("strip_click", 71),                      # clic sulla striscia
    ("strip_then_right", 12),                 # clic e poi aggiustato con →
])
def test_live_exports_exactly_the_frame_chosen_and_shown(qapp, win, nsd, how, expected):
    open_folder(qapp, win, nsd)
    go(qapp, win, f"{LIVE}.MP4")
    if how == "shift_right":
        press(qapp, win, Qt.Key_Right, Qt.ShiftModifier)
    elif how == "left_x3":
        for _ in range(3):
            press(qapp, win, Qt.Key_Left)
    elif how == "strip_click":
        win.strip.picked.emit(71)
    else:
        win.strip.picked.emit(10)
        press(qapp, win, Qt.Key_Right)
        press(qapp, win, Qt.Key_Right)
    pump(qapp, 0.2)
    assert win.frame == expected
    assert shown(qapp, win) == expected                      # a schermo c'è proprio quello
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert win.session.get(win.items[0].id)["frame"] == expected
    assert frame_of(exported_live(win)) == expected           # e in export pure


def test_live_changing_frame_after_yes_replaces_the_copy(qapp, win, nsd):
    """Tornati indietro, un altro fotogramma + Sì: in export resta SOLO il nuovo."""
    open_folder(qapp, win, nsd)
    go(qapp, win, f"{LIVE}.MP4")
    win.strip.picked.emit(20)
    pump(qapp, 0.2)
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert frame_of(exported_live(win)) == 20
    go(qapp, win, f"{LIVE}.MP4")
    win.strip.picked.emit(60)
    pump(qapp, 0.2)
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert frame_of(exported_live(win)) == 60                 # una sola copia, quella nuova
