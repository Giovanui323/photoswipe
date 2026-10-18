"""Formati delle foto: JPEG, PNG, HEIC e Live Photo di iPhone (HEIC + MOV).

Le foto vengono copiate byte per byte, quindi qui si controlla soprattutto che lo scanner
le riconosca, le abbini nel modo giusto e che l'export le porti via intatte. La lettura
dell'HEIC per la visualizzazione passa da Qt (solo macOS) e viene testata a parte."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cloud  # noqa: E402
import exporter  # noqa: E402
import frames  # noqa: E402
from scanner import scan  # noqa: E402
from test_ui import qapp  # noqa: E402,F401

FF = frames.ffmpeg_exe()
MAC = sys.platform == "darwin"
needs_sips = pytest.mark.skipif(not (MAC and shutil.which("sips")), reason="serve sips (macOS)")


def make_jpg(path: Path, size=(400, 300)) -> Path:
    Image.new("RGB", size, (200, 80, 40)).save(path, "JPEG", quality=92)
    return path


def make_png(path: Path) -> Path:
    Image.new("RGBA", (120, 90), (10, 200, 90, 255)).save(path, "PNG")
    return path


def make_heic(dst: Path, size=(400, 300)) -> Path:
    """HEIC vero, creato con sips (macOS) da un JPEG temporaneo fuori dalla cartella di prova."""
    src = make_jpg(Path(tempfile.mkdtemp()) / "src.jpg", size)
    r = subprocess.run(["sips", "-s", "format", "heic", str(src), "--out", str(dst)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not dst.exists():
        pytest.skip(f"sips non sa scrivere HEIC: {r.stderr.strip()}")
    return dst


def make_mov(path: Path, seconds: float = 3.0) -> Path:
    """Video MOV come quello di una Live di iPhone (H.264, ~3 secondi)."""
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=640x480:rate=30:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(path)], check=True)
    return path


def by_name(items) -> dict[str, object]:
    return {i.main.name: i for i in items}


# ---- riconoscimento dei formati foto ----

@pytest.mark.parametrize("name", ["FOTO_1.JPG", "foto_2.jpeg", "FOTO_3.Jpg"])
def test_jpeg_extensions_are_photos(tmp_path, name):
    make_jpg(tmp_path / name)
    items = scan(tmp_path)
    assert len(items) == 1
    assert items[0].kind == "photo"
    assert items[0].image == tmp_path / name
    assert items[0].video is None


def test_png_is_a_photo(tmp_path):
    make_png(tmp_path / "SCHERMO.PNG")
    (item,) = scan(tmp_path)
    assert item.kind == "photo" and item.image.suffix.upper() == ".PNG"


@needs_sips
def test_heic_is_a_photo(tmp_path):
    make_heic(tmp_path / "IMG_0001.HEIC")
    (item,) = scan(tmp_path)
    assert item.kind == "photo"
    assert item.image.name == "IMG_0001.HEIC"


def test_unsupported_files_are_ignored(tmp_path):
    (tmp_path / "note.txt").write_text("ciao")
    (tmp_path / "miniatura.THM").write_bytes(b"\0" * 10)
    (tmp_path / "anteprima.LRF").write_bytes(b"\0" * 10)
    assert scan(tmp_path) == []


def test_export_png_copies_byte_identical(tmp_path):
    src_dir = tmp_path / "sorgente"
    src_dir.mkdir()
    src = make_png(src_dir / "ORIG.png")
    (item,) = scan(src_dir)
    out_dir = tmp_path / "export"
    out_dir.mkdir()
    out = exporter.export_item(item, None, out_dir, exporter.Settings())
    assert len(out) == 1
    assert out[0].read_bytes() == src.read_bytes()


@needs_sips
def test_export_heic_copies_byte_identical(tmp_path):
    src = make_heic(tmp_path / "IMG_0002.HEIC")
    (item,) = scan(tmp_path)
    out_dir = tmp_path / "export"
    out_dir.mkdir()
    out = exporter.export_item(item, None, out_dir, exporter.Settings())
    assert out[0].name == "IMG_0002.HEIC"
    assert out[0].read_bytes() == src.read_bytes()


# ---- abbinamenti: nome base uguale = stesso elemento ----

def test_jpg_and_heic_with_same_name_are_two_items(tmp_path):
    """Foto scattata con due formati insieme: non si sovrascrivono."""
    make_jpg(tmp_path / "IMG_0003.JPG")
    (tmp_path / "IMG_0003.HEIC").write_bytes(b"\0" * 64)   # contenuto non importa per lo scan
    items = scan(tmp_path)
    assert len(items) == 2
    assert {i.image.suffix.upper() for i in items} == {".JPG", ".HEIC"}


def test_jpg_and_dng_with_same_name_are_one_item(tmp_path):
    make_jpg(tmp_path / "DSC_0004.JPG")
    (tmp_path / "DSC_0004.DNG").write_bytes(b"\0" * 64)
    (item,) = scan(tmp_path)
    assert item.image.name == "DSC_0004.JPG"
    assert item.raw.name == "DSC_0004.DNG"


# ---- Live Photo di iPhone: HEIC + MOV con lo stesso nome ----

@needs_sips
def test_iphone_live_photo_is_one_photo_with_its_video(tmp_path):
    make_heic(tmp_path / "IMG_0010.HEIC")
    make_mov(tmp_path / "IMG_0010.MOV")
    items = scan(tmp_path)
    assert len(items) == 1                           # niente doppioni: un solo elemento
    item = items[0]
    assert item.kind == "photo"                      # resta una foto, non diventa una Live
    assert item.image.name == "IMG_0010.HEIC"
    assert item.video.name == "IMG_0010.MOV"


@needs_sips
def test_iphone_live_export_keeps_still_only_by_default(tmp_path):
    src = make_heic(tmp_path / "IMG_0011.HEIC")
    make_mov(tmp_path / "IMG_0011.MOV")
    (item,) = scan(tmp_path)
    out_dir = tmp_path / "export"
    out_dir.mkdir()
    out = exporter.export_item(item, None, out_dir, exporter.Settings(copy_video=False))
    assert [p.name for p in out] == ["IMG_0011.HEIC"]
    assert out[0].read_bytes() == src.read_bytes()
    assert not (out_dir / exporter.VIDEO_SUBDIR).exists()


@needs_sips
def test_iphone_live_export_with_video_copies_mov_too(tmp_path):
    make_heic(tmp_path / "IMG_0012.HEIC")
    mov = make_mov(tmp_path / "IMG_0012.MOV")
    (item,) = scan(tmp_path)
    out_dir = tmp_path / "export"
    out_dir.mkdir()
    out = exporter.export_item(item, None, out_dir, exporter.Settings(copy_video=True))
    assert out[1] == out_dir / exporter.VIDEO_SUBDIR / "IMG_0012.MOV"
    assert out[1].read_bytes() == mov.read_bytes()


def test_iphone_live_with_different_names_are_not_paired(tmp_path):
    """Se il MOV è stato rinominato, non si abbina: sono due elementi separati."""
    make_jpg(tmp_path / "IMG_0013.JPG")
    make_mov(tmp_path / "IMG_0099.MOV")
    items = by_name(scan(tmp_path))
    assert items["IMG_0013.JPG"].video is None
    assert items["IMG_0099.MOV"].kind in ("live", "video")


@pytest.mark.parametrize("seconds, kind", [(3.0, "live"), (8.0, "video")])
def test_stand_alone_mov_is_live_only_when_short(tmp_path, seconds, kind):
    make_mov(tmp_path / "CLIP.MOV", seconds)
    (item,) = scan(tmp_path)
    assert item.kind == kind


def test_icloud_placeholder_heic_is_listed_with_its_real_name(tmp_path):
    """Foto solo su iCloud: il segnaposto '.nome.HEIC.icloud' viene mostrato col nome vero."""
    (tmp_path / ".IMG_0020.HEIC.icloud").write_bytes(b"x")
    (item,) = scan(tmp_path)
    assert item.image.name == "IMG_0020.HEIC"
    assert not cloud.is_local(item.image)


# ---- visualizzazione dell'HEIC (Qt, solo macOS) ----

@needs_sips
def test_heic_can_be_decoded_for_display(tmp_path, qapp):
    from PySide6.QtGui import QImageReader
    heic = make_heic(tmp_path / "IMG_0030.HEIC", (640, 480))
    reader = QImageReader(str(heic))
    img = reader.read()
    assert img.isNull() is False, reader.errorString()
    assert (img.width(), img.height()) == (640, 480)
