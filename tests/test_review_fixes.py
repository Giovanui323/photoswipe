"""Test sui problemi medi della revisione (9–12): export, nomi uguali, DNG, completamento."""
from __future__ import annotations

import io
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import exporter  # noqa: E402
import scanner  # noqa: E402
from scanner import Item, scan  # noqa: E402


# 9 ------------------------------------------------------------------------------------------
def test_export_dir_validation(tmp_path):
    root = tmp_path / "src"
    (root / exporter.TRASH_DIR / "sub").mkdir(parents=True)
    bad = {
        "stessa": root,
        "cancellare": root / exporter.TRASH_DIR,
        "dentro cancellare": root / exporter.TRASH_DIR / "sub",
        "contiene la sorgente": tmp_path,
    }
    for why, export in bad.items():
        assert exporter.export_dir_problem(root, export), why
    assert exporter.export_dir_problem(root, root / "export") is None   # default: va bene
    assert exporter.export_dir_problem(root, tmp_path / "out") is None
    assert exporter.export_dir_problem(root, tmp_path / "src-export") is None  # solo prefisso
    # percorsi non risolti (link simbolici, "..") contano come quelli veri
    link = tmp_path / "link"
    link.symlink_to(root)
    assert exporter.export_dir_problem(root, link)
    assert exporter.export_dir_problem(root, root / "x" / ".." / exporter.TRASH_DIR)


# 10 -----------------------------------------------------------------------------------------
def test_same_stem_same_type_are_separate_items(tmp_path):
    for name in ("IMG_0002.JPG", "IMG_0002.HEIC"):
        Image.new("RGB", (8, 8), "red").save(tmp_path / name, format="JPEG")
    (tmp_path / "IMG_0002.DNG").write_bytes(b"raw" * 10)
    (tmp_path / "IMG_0003.MOV").write_bytes(b"\0" * 10)
    (tmp_path / "IMG_0003.MP4").write_bytes(b"\0" * 20)
    items = scan(tmp_path)
    images = sorted(it.image.name for it in items if it.image)
    videos = sorted(it.video.name for it in items if it.video)
    assert images == ["IMG_0002.HEIC", "IMG_0002.JPG"]          # nessuna immagine sparita
    assert videos == ["IMG_0003.MOV", "IMG_0003.MP4"]
    assert sum(1 for it in items if it.raw) == 1                # il DNG resta con una delle due
    assert len({it.id for it in items}) == len(items) == 4
    files = [f for it in items for f in it.files()]
    assert len(files) == len(set(files)) == 5                   # ogni file in un solo elemento


# 11 -----------------------------------------------------------------------------------------
def _fake_rawpy(monkeypatch, thumb=None, developed=None):
    """rawpy finto: un DNG vero non si crea facilmente nei test."""
    m = types.ModuleType("rawpy")

    class LibRawNoThumbnailError(Exception):
        pass

    class LibRawUnsupportedThumbnailError(Exception):
        pass

    m.LibRawNoThumbnailError = LibRawNoThumbnailError
    m.LibRawUnsupportedThumbnailError = LibRawUnsupportedThumbnailError
    m.ThumbFormat = types.SimpleNamespace(JPEG="jpeg", BITMAP="bitmap")

    class Raw:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_thumb(self):
            if thumb is None:
                raise LibRawNoThumbnailError()
            return thumb

        def postprocess(self, **kw):
            assert kw.get("half_size")
            return developed

    m.imread = lambda path: Raw()
    monkeypatch.setitem(sys.modules, "rawpy", m)


def test_dng_preview_embedded_jpeg(tmp_path, monkeypatch):
    buf = io.BytesIO()
    Image.new("RGB", (1200, 800), "blue").save(buf, format="JPEG")
    _fake_rawpy(monkeypatch, thumb=types.SimpleNamespace(format="jpeg", data=buf.getvalue()))
    img = scanner.raw_preview(tmp_path / "a.DNG")
    assert img is not None and img.size == (1200, 800)


def test_dng_preview_develops_when_thumb_missing_or_tiny(tmp_path, monkeypatch):
    developed = np.zeros((600, 900, 3), dtype=np.uint8)
    _fake_rawpy(monkeypatch, developed=developed)
    assert scanner.raw_preview(tmp_path / "a.DNG").size == (900, 600)
    tiny = types.SimpleNamespace(format="bitmap", data=np.zeros((120, 160, 3), dtype=np.uint8))
    _fake_rawpy(monkeypatch, thumb=tiny, developed=developed)
    assert scanner.raw_preview(tmp_path / "a.DNG").size == (900, 600)


def test_dng_preview_unreadable_file_returns_none(tmp_path):
    bad = tmp_path / "rotto.DNG"
    bad.write_bytes(b"non sono un raw" * 50)
    assert scanner.raw_preview(bad) is None      # rawpy vero: niente eccezioni verso l'app


def test_dng_only_item_downloads_the_dng(tmp_path):
    dng = tmp_path / "IMG_0009.DNG"
    it = Item(kind="photo", id=dng.name, raw=dng)
    assert it.needed_files() == [dng]            # senza il DNG in locale non c'è anteprima


# 12 -----------------------------------------------------------------------------------------
def test_completed_ignores_decisions_on_items_no_longer_scanned(tmp_path):
    root, export = tmp_path / "src", tmp_path / "out"
    root.mkdir()
    s = exporter.Session(root, export, ids=["a", "b", "c", "d"])
    s.set("a", "yes")
    s.set("b", "trash", moved=[["src/b", "src/cancellare/b"]])
    s.set("c", "no")
    assert s.decided == 3 and not s.completed
    # riapertura: "b" è in "cancellare", la scansione non lo trova più
    s2 = exporter.Session(root, export, ids=["a", "c", "d"])
    s2.set("a#f0010", "snap")                    # le foto da video non contano come elementi
    assert s2.total == 3 and s2.decided == 2 and not s2.completed
    info = exporter.Session.peek(root)
    assert info["decided"] == 2 and info["total"] == 3 and not info["completed"]
    s2.set("d", "skip")
    assert s2.completed and exporter.Session.peek(root)["completed"]
    assert s2.get("b")["choice"] == "trash"      # la scelta resta salvata (per annullare)
