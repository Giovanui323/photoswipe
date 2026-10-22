"""Correzioni sulla gestione dei dati: copie doppie alla ripresa, salvataggio che non riesce,
salvataggio rotto in una cartella di sola lettura, doppioni con DNG, mdls, date iCloud, Unicode,
"cancellare" nelle sottocartelle. Gli originali non si modificano né si cancellano mai."""
from __future__ import annotations

from album_names import nodate  # noqa: E402
import hashlib
import json
import os
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cloud  # noqa: E402
import exporter  # noqa: E402
import scanner  # noqa: E402
from scanner import scan  # noqa: E402

NOT_ROOT = pytest.mark.skipif(os.geteuid() == 0, reason="root scrive ovunque")


@pytest.fixture(autouse=True)
def fresh_process():
    """Ogni test parte come un'app appena aperta: nessuna copia "in mano" a questo processo."""
    exporter._claims.clear()
    yield
    exporter._claims.clear()


def jpeg(path: Path, when: str | None = None, color=(120, 80, 40)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    if when:
        exif[306] = when
        exif.get_ifd(0x8769)[36867] = when
    Image.new("RGB", (64, 48), color).save(path, quality=90, exif=exif)
    return path


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def files_in(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                  if p.is_file() and not p.name.startswith("."))


SHOT = "2024:06:15 12:34:56"     # data di scatto nell'EXIF delle foto di prova
P = "20240615_123456_"           # ...e il prefisso che ogni copia esportata ha davanti al nome


def snapshot(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob("*"))
            if p.is_file() and not p.name.startswith(".") and exporter.TRASH_DIR not in p.parts}


# 1 ---------------------------------------------------------- copie doppie "_2" alla ripresa

def test_reexport_after_crash_adopts_identical_copies(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    jpeg(root / "IMG_0001.JPG", SHOT)
    (root / "IMG_0001.DNG").write_bytes(b"raw-data" * 100)
    (root / "IMG_0001.MOV").write_bytes(b"mov" * 1000)
    before = snapshot(root)
    [item] = scan(root)
    s = exporter.Session(root, out, ids=[item.id])
    s.set(item.id, "yes", [])
    s.mark_export(item.id, "t1")
    settings = exporter.Settings(copy_video=True)
    first = exporter.export_item(item, None, out, settings)
    # l'app muore qui: copie finite, esito mai registrato
    exporter._claims.clear()
    s2 = exporter.Session(root, out, ids=[item.id])
    assert s2.pending_exports({item.id}) == [item.id]
    s2.mark_export(item.id, "t2")
    again = exporter.export_item(item, None, out, settings)
    assert again == first
    assert files_in(out) == [f"Foto/{P}IMG_0001.DNG", f"Foto/{P}IMG_0001.JPG", f"Video/{P}IMG_0001.MOV"]
    assert s2.record_export(item.id, "t2", again) == "ok"
    assert snapshot(root) == before


def test_reexport_after_stale_result_adopts_copy(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    jpeg(root / "IMG_0001.JPG", SHOT)
    [item] = scan(root)
    s = exporter.Session(root, out, ids=[item.id])
    s.set(item.id, "yes", [])
    s.mark_export(item.id, "vecchio")
    res = exporter.export_item(item, None, out, exporter.Settings())
    s.mark_export(item.id, "nuovo")                                   # riaperta: export rimesso in coda
    assert s.record_export(item.id, "vecchio", res) == "stale"         # copia rimasta senza padrone
    again = exporter.export_item(item, None, out, exporter.Settings())
    assert again == res and files_in(out) == [f"Foto/{P}IMG_0001.JPG"]


def test_identical_copy_owned_by_another_choice_is_not_adopted(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    jpeg(root / "IMG_0001.JPG", SHOT)
    [item] = scan(root)
    taken = out / exporter.PHOTO_SUBDIR / f"{P}IMG_0001.JPG"         # dove e come la farebbe l'export
    taken.parent.mkdir(parents=True)
    taken.write_bytes(item.image.read_bytes())                        # stessa copia, ma di un'altra scelta
    s = exporter.Session(root, out, ids=[item.id])
    s.set("altro/IMG_0001.JPG", "yes", [taken])
    s.set(item.id, "yes", [])
    res = exporter.export_item(item, None, out, exporter.Settings())
    assert res == [taken.with_name(f"{P}IMG_0001_2.JPG")]


def test_different_or_claimed_copy_is_not_adopted(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    jpeg(root / "IMG_0001.JPG", SHOT)
    [item] = scan(root)
    other = out / exporter.PHOTO_SUBDIR / f"{P}IMG_0001.JPG"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"x" * item.image.stat().st_size)              # stessa dimensione, altro contenuto
    res = exporter.export_item(item, None, out, exporter.Settings())
    assert res == [other.with_name(f"{P}IMG_0001_2.JPG")]
    assert other.read_bytes() == b"x" * item.image.stat().st_size
    # una copia fatta da questo processo e non ancora registrata non si riusa (due elementi uguali)
    res2 = exporter.export_item(item, None, out, exporter.Settings())
    assert res2 == [other.with_name(f"{P}IMG_0001_3.JPG")]


def test_failed_reexport_never_deletes_adopted_copy(tmp_path, monkeypatch):
    root, out = tmp_path / "src", tmp_path / "out"
    jpeg(root / "IMG_0001.JPG", SHOT)
    (root / "IMG_0001.DNG").write_bytes(b"raw-data" * 100)
    [item] = scan(root)
    foto = out / exporter.PHOTO_SUBDIR
    assert exporter.export_item(item, None, out, exporter.Settings()) == \
        [foto / f"{P}IMG_0001.JPG", foto / f"{P}IMG_0001.DNG"]
    exporter._claims.clear()
    (foto / f"{P}IMG_0001.DNG").unlink()
    real = exporter.shutil.copy2

    def fail_dng(src, dst, **kw):
        if str(src).endswith(".DNG"):
            raise OSError("disco pieno")
        return real(src, dst, **kw)
    monkeypatch.setattr(exporter.shutil, "copy2", fail_dng)
    with pytest.raises(OSError):
        exporter.export_item(item, None, out, exporter.Settings())
    assert (foto / f"{P}IMG_0001.JPG").exists()                       # adottata: non tolta
    assert files_in(out) == [f"Foto/{P}IMG_0001.JPG"]


def test_live_frame_adopted_only_if_identical(tmp_path):
    from test_core import LIVE, make_clip
    root, out = tmp_path / "sd", tmp_path / "out"
    dcim = root / "DCIM" / "DJI_001"
    dcim.mkdir(parents=True)
    make_clip(dcim / f"{LIVE}.MP4", 3.036, "320x180")
    [item] = scan(root)
    assert item.kind == "live"
    foto = out / exporter.PHOTO_SUBDIR
    first = exporter.export_item(item, 20, out, exporter.Settings())
    assert first == [foto / ("20260730_132204_" + nodate(f"{LIVE}.jpg"))]      # 20 / 29,97 fps = +0,67 s
    exporter._claims.clear()
    assert exporter.export_item(item, 20, out, exporter.Settings()) == first   # stesso fotogramma
    exporter._claims.clear()
    # altro fotogramma nello stesso secondo: stesso nome, contenuto diverso -> copia nuova
    other = exporter.export_item(item, 25, out, exporter.Settings())
    assert other == [foto / ("20260730_132204_" + nodate(f"{LIVE}_2.jpg"))]
    assert sha(other[0]) != sha(first[0])
    exporter._claims.clear()
    later = exporter.export_item(item, 60, out, exporter.Settings())           # +2 s: altro nome
    assert later == [foto / ("20260730_132206_" + nodate(f"{LIVE}.jpg"))]
    assert not [p for p in out.rglob("*") if ".part" in p.name]


def test_edited_photo_adopted_only_if_identical(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    jpeg(root / "IMG_0001.JPG", SHOT)
    [item] = scan(root)
    first = exporter.export_item(item, None, out, exporter.Settings(), edit={"exposure": 0.3})
    assert first == [out / exporter.PHOTO_SUBDIR / f"{P}IMG_0001.JPG"]
    exporter._claims.clear()
    assert exporter.export_item(item, None, out, exporter.Settings(), edit={"exposure": 0.3}) == first
    exporter._claims.clear()
    other = exporter.export_item(item, None, out, exporter.Settings(), edit={"exposure": -0.5})
    assert other == [out / exporter.PHOTO_SUBDIR / f"{P}IMG_0001_2.JPG"]


# 2 ---------------------------------------------------------- salvataggio che non riesce

@NOT_ROOT
def test_save_falls_back_to_export_then_raises_clear_error(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    root.mkdir()
    s = exporter.Session(root, out)
    s.save()
    root.chmod(0o555)                                                 # disco pieno / permessi tolti
    try:
        s.set("a.jpg", "trash", moved=[["x", "y"]])
        assert s.path == out / exporter.SESSION_FILE and s.saved_elsewhere == s.path
        assert exporter.Session(root, out).get("a.jpg")["moved"] == [["x", "y"]]   # il più recente
        out.chmod(0o555)
        try:
            with pytest.raises(exporter.SessionSaveError) as e:
                s.set("b.jpg", "skip")
            assert "b.jpg" not in json.loads((out / exporter.SESSION_FILE).read_text())["decisions"]
            assert str(root) in str(e.value) or str(out) in str(e.value)
        finally:
            out.chmod(0o755)
    finally:
        root.chmod(0o755)


def test_trash_item_puts_originals_back_if_save_fails(tmp_path, monkeypatch):
    root, out = tmp_path / "src", tmp_path / "out"
    jpg = jpeg(root / "sub" / "IMG_0001.JPG")
    (root / "sub" / "IMG_0001.DNG").write_bytes(b"raw" * 50)
    before = snapshot(root)
    [item] = scan(root)
    s = exporter.Session(root, out, ids=[item.id])
    s.set(item.id, "skip")

    def broken(self, path):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(exporter.Session, "_write", broken)
    with pytest.raises(exporter.SessionSaveError):
        exporter.trash_item(s, item, root)
    assert snapshot(root) == before and jpg.exists()                 # originali al loro posto
    assert not (root / exporter.TRASH_DIR).exists()
    assert s.get(item.id)["choice"] == "skip"                         # in memoria: la scelta di prima
    monkeypatch.undo()
    moved = exporter.trash_item(s, item, root)
    assert s.get(item.id) == {"choice": "trash", "files": [], "frame": None,
                              "with_video": False, "moved": moved}
    assert (root / exporter.TRASH_DIR / "sub" / "IMG_0001.DNG").exists()


# 3 ---------------------------------------------------------- salvataggio rotto, cartella di sola lettura

@NOT_ROOT
def test_corrupt_session_in_readonly_folder_opens_and_is_kept(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    jpeg(root / "IMG_0001.JPG")
    broken = b'{"decisions": {"IMG_0001.JPG": {"choice": "trash", "moved": [["/x/a.jpg", "/x/canc'
    (root / exporter.SESSION_FILE).write_bytes(broken)
    root.chmod(0o555)
    try:
        s = exporter.Session(root, out, ids=["IMG_0001.JPG"])         # prima: OSError, cartella inapribile
        assert s.decisions == {}
        assert (root / exporter.SESSION_FILE).read_bytes() == broken  # intatto, al suo posto
        assert s.corrupt_backup is not None and s.corrupt_backup.parent == out
        assert s.corrupt_backup.read_bytes() == broken
        assert s.path == out / exporter.SESSION_FILE
        s.set("IMG_0001.JPG", "yes", [])
        again = exporter.Session(root, out, ids=["IMG_0001.JPG"])
        assert again.get("IMG_0001.JPG")["choice"] == "yes"
        assert again.corrupt_backup is None                            # copia già fatta: niente doppioni
        assert len(list(out.glob("*.corrupt"))) == 1
        assert (root / exporter.SESSION_FILE).read_bytes() == broken
    finally:
        root.chmod(0o755)


# 4 ---------------------------------------------------------- doppioni: il DNG del doppione

def test_duplicate_with_dng_brings_the_dng(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    jpg = jpeg(root / "DCIM" / "100" / "IMG_0001.JPG", SHOT)         # tenuta (cartella più profonda)
    copia = root / "copia"
    copia.mkdir()
    (copia / "IMG_0001.JPG").write_bytes(jpg.read_bytes())
    (copia / "IMG_0001.DNG").write_bytes(b"raw-data" * 100)
    [item] = scan(root)
    assert item.id == "DCIM/100/IMG_0001.JPG"
    assert item.image == jpg.resolve() and item.raw == (copia / "IMG_0001.DNG").resolve()
    foto = out / exporter.PHOTO_SUBDIR
    assert exporter.export_item(item, None, out, exporter.Settings()) == \
        [foto / f"{P}IMG_0001.JPG", foto / f"{P}IMG_0001.DNG"]          # stessa data: restano vicini
    moved = exporter.move_to_trash(item, root)
    assert (root / exporter.TRASH_DIR / "copia" / "IMG_0001.DNG").exists()
    exporter.restore_from_trash(moved)
    assert (copia / "IMG_0001.DNG").exists() and jpg.exists()


# 5 ---------------------------------------------------------- mdls si ferma al primo file mancante

def fake_mdls(values: dict[str, str], calls: list):
    """Come mdls: si ferma al primo percorso che non trova (errore e niente per i successivi)."""
    def run(cmd, capture_output=True, timeout=None, **kw):
        paths = cmd[4:]
        calls.append(paths)
        outv, err = [], b""
        for p in paths:
            if not os.path.exists(p):
                err = f"{p}: could not find {p}.\n".encode()
                break
            outv.append(values.get(Path(p).name, "(null)"))
        return subprocess.CompletedProcess(cmd, 0, "\0".join(outv).encode(), err)
    return run


def test_spotlight_skips_missing_paths(tmp_path, monkeypatch):
    names = [f"f{i}.heic" for i in range(5)]
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    paths = [tmp_path / n for n in names]
    paths.insert(2, tmp_path / "sparito.heic")                       # tolto o solo stub iCloud
    values = {n: f"2024-06-1{i} 10:00:00 +0000" for i, n in enumerate(names)}
    calls: list = []
    monkeypatch.setattr(scanner.sys, "platform", "darwin")
    monkeypatch.setattr(scanner.subprocess, "run", fake_mdls(values, calls))
    got = scanner.spotlight_dates(paths)
    assert len(got) == 6 and got[2] is None
    assert [g.day for g in got if g] == [10, 11, 12, 13, 14]
    assert all(str(tmp_path / "sparito.heic") not in c for c in calls)

    dvalues = {n: str(1.5 + i) for i, n in enumerate(names)}
    monkeypatch.setattr(scanner.subprocess, "run", fake_mdls(dvalues, calls))
    assert scanner.spotlight_durations(paths) == [1.5, 2.5, 0.0, 3.5, 4.5, 5.5]


def test_spotlight_falls_back_to_one_call_per_file(tmp_path, monkeypatch):
    names = [f"f{i}.mov" for i in range(4)]
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    paths = [tmp_path / n for n in names]
    calls: list = []
    good = fake_mdls({n: str(i + 1) for i, n in enumerate(names)}, calls)

    def flaky(cmd, **kw):   # in blocco si ferma al secondo file (es. sparito nel frattempo)
        if len(cmd) > 5:
            return subprocess.CompletedProcess(cmd, 0, b"1\0", b"errore")
        return good(cmd, **kw)
    monkeypatch.setattr(scanner.sys, "platform", "darwin")
    monkeypatch.setattr(scanner.subprocess, "run", flaky)
    assert scanner.spotlight_durations(paths) == [1.0, 2.0, 3.0, 4.0]


# 6 ---------------------------------------------------------- data di scatto dopo il download iCloud

def test_refresh_capture_time_after_download(tmp_path, monkeypatch):
    root = tmp_path / "src"
    jpeg(root / "IMG_0001.JPG", "2023:05:04 10:11:12")
    monkeypatch.setattr(cloud, "is_local", lambda p: False)         # alla lettura: solo su iCloud
    [item] = scan(root)
    assert item.taken != datetime(2023, 5, 4, 10, 11, 12)            # la data del file
    assert not scanner.refresh_capture_time(item)                     # ancora non scaricato
    monkeypatch.setattr(cloud, "is_local", lambda p: True)          # scaricato
    assert scanner.refresh_capture_time(item)
    assert item.taken == datetime(2023, 5, 4, 10, 11, 12)
    assert not scanner.refresh_capture_time(item)                     # già giusta


# 7 ---------------------------------------------------------- Unicode NFC / NFD

def test_resume_with_nfd_keys(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    nfd_dir = unicodedata.normalize("NFD", "Città")
    nfd_name = unicodedata.normalize("NFD", "Caffè.JPG")
    jpeg(root / nfd_dir / nfd_name)
    jpeg(root / "Perù.JPG", color=(1, 2, 3))
    items = scan(root)
    ids = {it.id for it in items}
    assert ids == {unicodedata.normalize("NFC", "Città/Caffè.JPG"), unicodedata.normalize("NFC", "Perù.JPG")}
    for it in items:                                                   # i percorsi veri non cambiano
        assert it.main.exists()
    key = unicodedata.normalize("NFD", "Città/Caffè.JPG")
    (root / exporter.SESSION_FILE).write_text(json.dumps({
        "root": str(root), "updated": "2024-01-01T00:00:00",
        "decisions": {key: {"choice": "yes", "files": []},
                      unicodedata.normalize("NFD", "Perù.JPG"): {"choice": "no", "files": []}},
        "favorites": [key], "edits": {key: {"exposure": 0.2}}}), "utf-8")
    s = exporter.Session(root, out, ids=[it.id for it in items])
    nfc = unicodedata.normalize("NFC", key)
    assert s.get(nfc)["choice"] == "yes" and nfc in s.favorites and nfc in s.edits
    assert s.decided == 2 and s.pending_exports(ids) == [nfc]


def test_nfd_subfolder_save_rebased_from_parent(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    sub = root / unicodedata.normalize("NFD", "Città")
    jpeg(sub / "IMG_0001.JPG")
    (sub / exporter.SESSION_FILE).write_text(json.dumps({
        "root": str(sub), "updated": "2024-01-01T00:00:00",
        "decisions": {"IMG_0001.JPG": {"choice": "no", "files": []}}}), "utf-8")
    [item] = scan(root)
    s = exporter.Session(root, out, ids=[item.id])
    assert s.get(item.id) is not None and s.get(item.id)["choice"] == "no"


# 8 ---------------------------------------------------------- "cancellare" nelle sottocartelle

def test_trash_from_subfolder_goes_to_root_trash_with_same_subpath(tmp_path):
    root = tmp_path / "src"
    jpg = jpeg(root / "viaggio" / "giorno1" / "IMG_0001.JPG")
    old = jpeg(root / "viaggio" / exporter.TRASH_DIR / "IMG_0009.JPG")   # "cancellare" annidato
    [item] = scan(root)
    assert item.id == "viaggio/giorno1/IMG_0001.JPG"
    moved = exporter.move_to_trash(item, root)
    assert moved == [[str(jpg.resolve()),
                      str((root / exporter.TRASH_DIR / "viaggio" / "giorno1" / "IMG_0001.JPG").resolve())]]
    assert scan(root) == []                                           # nessuno dei due "cancellare" riletto
    exporter.restore_from_trash(moved)
    assert jpg.exists() and old.exists()
    assert not (root / exporter.TRASH_DIR).exists()                   # cartelle vuote tolte, solo quelle
    assert (root / "viaggio" / exporter.TRASH_DIR).is_dir()


@NOT_ROOT
def test_broken_link_and_untraversable_folder_do_not_stop_the_scan(tmp_path):
    root = tmp_path / "foto"
    jpeg(root / "a.jpg")
    jpeg(root / "sub" / "b.jpg")
    (root / "rotto.jpg").symlink_to(tmp_path / "non_c_e.jpg")
    os.chmod(root / "sub", 0o444)   # leggibile ma non attraversabile
    try:
        ids = [i.id for i in scan(root)]
    finally:
        os.chmod(root / "sub", 0o755)
    assert "a.jpg" in ids
    assert "rotto.jpg" not in ids   # niente da mostrare


def test_same_name_and_size_but_different_photo_is_not_a_duplicate(tmp_path):
    # contatori che ripartono su ogni scheda, RAW non compressi tutti della stessa dimensione
    root = tmp_path / "foto"
    a = jpeg(root / "card1" / "DSC_0001.JPG", "2023:05:01 10:00:00", (200, 0, 0))
    b = root / "card2" / "DSC_0001.JPG"
    b.parent.mkdir(parents=True)
    data = bytearray(a.read_bytes())
    data[-10] ^= 0xFF   # stessa dimensione, contenuto diverso
    b.write_bytes(bytes(data))
    copy = root / "copia" / "DSC_0001.JPG"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(a.read_bytes())   # questa invece è un doppione vero
    ids = sorted(i.id for i in scan(root))
    assert len(ids) == 2
    assert "card2/DSC_0001.JPG" in ids


def test_user_folders_named_panorama_or_misc_are_shown(tmp_path):
    root = tmp_path / "foto"
    jpeg(root / "Vacanze" / "Panorama" / "tramonto.jpg")
    jpeg(root / "Vacanze" / "misc" / "varie.jpg")
    jpeg(root / "SD" / "PANORAMA" / "001_0001" / "PANO0001.JPG")   # scatti singoli DJI
    jpeg(root / "SD" / "MISC" / "THM" / "x.jpg")                   # file di sistema DJI
    ids = sorted(i.id for i in scan(root))
    assert ids == ["Vacanze/Panorama/tramonto.jpg", "Vacanze/misc/varie.jpg"]


def test_capture_time_reads_exif_of_png_and_dng(tmp_path):
    for name, fmt in (("a.png", "PNG"), ("b.dng", "TIFF")):
        exif = Image.Exif()
        exif[271] = "Camera"   # senza un tag base Pillow non scrive l'EXIF
        exif[306] = "2025:06:01 10:00:00"   # nel TIFF Pillow non scrive il blocco Exif: c'è DateTime
        exif.get_ifd(0x8769)[36867] = "2025:06:01 10:00:00"
        Image.new("RGB", (8, 8)).save(tmp_path / name, fmt, exif=exif)
        assert scanner.capture_time(tmp_path / name, True) == datetime(2025, 6, 1, 10, 0, 0)


def test_iphone_video_uses_the_local_time_of_the_place(tmp_path):
    # foto alle 10:00 ora di Tokyo, video alle 10:00:30 ora di Tokyo (01:00:30 UTC): il video
    # va dopo la foto qualunque sia il fuso del Mac
    import imageio_ffmpeg
    v = tmp_path / "IMG_0002.MOV"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=size=64x48:rate=10:duration=5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-metadata", "creation_time=2025-06-04T01:00:30Z",
                    "-metadata", "com.apple.quicktime.creationdate=2025-06-04T10:00:30+0900",
                    "-movflags", "use_metadata_tags", str(v)], check=True)
    assert scanner.capture_time(v, True) == datetime(2025, 6, 4, 10, 0, 30)


def test_trash_is_recorded_before_the_files_move(tmp_path, monkeypatch):
    # l'app si chiude fra il salvataggio e lo spostamento: su disco c'è già la traccia
    root, out = tmp_path / "src", tmp_path / "out"
    jpeg(root / "IMG_0001.JPG")
    [item] = scan(root)
    s = exporter.Session(root, out, ids=[item.id])

    def killed(*a, **k):
        raise SystemExit("uscita a metà")
    monkeypatch.setattr(exporter, "move_to_trash", killed)
    with pytest.raises(SystemExit):
        exporter.trash_item(s, item, root)
    on_disk = exporter.Session.read(s.path)["decisions"][item.id]
    assert on_disk["choice"] == "trash"
    assert on_disk["moved"] == [[str(root.resolve() / "IMG_0001.JPG"),
                                 str(root.resolve() / exporter.TRASH_DIR / "IMG_0001.JPG")]]
    monkeypatch.undo()
    # alla ripresa Annulla trova il file ancora al suo posto: niente da rimettere, niente perso
    assert exporter.restore_from_trash(on_disk["moved"]) == []
    assert (root / "IMG_0001.JPG").exists()


def test_file_already_in_export_before_the_session_is_never_adopted(tmp_path):
    # in export c'è già una copia identica messa dall'utente: Sì non la riusa, così Z non la toglie
    root, out = tmp_path / "src", tmp_path / "out"
    jpeg(root / "IMG_0001.JPG", SHOT)
    [item] = scan(root)
    mine = out / exporter.PHOTO_SUBDIR / f"{P}IMG_0001.JPG"
    mine.parent.mkdir(parents=True)
    mine.write_bytes(item.image.read_bytes())
    s = exporter.Session(root, out, ids=[item.id])
    s.created = datetime.fromtimestamp(mine.stat().st_mtime + 60).isoformat(timespec="seconds")   # dopo il file
    s.set(item.id, "yes", [])
    res = exporter.export_item(item, None, out, exporter.Settings())
    assert res == [mine.with_name(f"{P}IMG_0001_2.JPG")]
    exporter.remove_files([str(f) for f in res])   # Z
    assert mine.exists()


def test_move_new_never_overwrites_a_file_that_appeared_meanwhile(tmp_path, monkeypatch):
    folder = tmp_path / "Foto"
    folder.mkdir()
    src = tmp_path / "a.part"
    src.write_bytes(b"nuova")
    real = exporter.unique_path

    def racing(f, name):   # fra la scelta del nome e lo spostamento arriva un altro file
        p = real(f, name)
        if not p.exists() and name == "a.jpg" and not (f / "a.jpg").exists():
            p.write_bytes(b"di un altro")
        return p
    monkeypatch.setattr(exporter, "unique_path", racing)
    dst = exporter.move_new(src, folder, "a.jpg")
    assert (folder / "a.jpg").read_bytes() == b"di un altro"
    assert dst == folder / "a_2.jpg" and dst.read_bytes() == b"nuova" and not src.exists()


def test_link_to_a_file_of_the_same_folder_is_shown_once(tmp_path):
    root = tmp_path / "foto"
    jpeg(root / "IMG_0005.JPG")
    (root / "copia.JPG").symlink_to(root / "IMG_0005.JPG")
    assert [i.id for i in scan(root)] == ["IMG_0005.JPG"]
