"""Test per exporter: rename_by_date claims, Session.relocated stamps, move_new EXDEV, _sessions."""
from __future__ import annotations

import errno
import os
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import exporter  # noqa: E402


def _make_jpeg(path: Path, text: bytes = b"photo-bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (50, 100, 150)).save(path, "JPEG")
    return path


def test_rename_by_date_claims_destination(tmp_path):
    export_dir = tmp_path / "export"
    src = _make_jpeg(export_dir / "IMG_0001.JPG")
    exporter._claim([src])
    when = datetime(2024, 6, 15, 12, 34, 56)

    moved = exporter.rename_by_date([("IMG_0001.JPG", when, [str(src)])], export_dir)
    assert "IMG_0001.JPG" in moved
    old_str, new_str = moved["IMG_0001.JPG"][0]
    assert exporter._path_keys(old_str).isdisjoint(exporter._claims)
    assert exporter._path_keys(new_str).issubset(exporter._claims)
    exporter.release_claims([new_str])


def test_session_relocated_updates_stamps(tmp_path):
    root = tmp_path / "root"
    export_dir = tmp_path / "export"
    root.mkdir()
    export_dir.mkdir()
    f1 = _make_jpeg(export_dir / "old_name.jpg")
    sess = exporter.Session(root, export_dir, ids=["a.jpg"])
    sess.set("a.jpg", "yes", [])
    token = "tok-1"
    sess.mark_export("a.jpg", token)
    assert sess.record_export("a.jpg", token, [f1]) == "ok"

    f2 = export_dir / "Foto" / "20240615_123456_old_name.jpg"
    f2.parent.mkdir(parents=True, exist_ok=True)
    f2.write_bytes(b"updated-content-longer-than-before" * 10)
    f1.unlink()

    assert sess.relocated("a.jpg", token, [[str(f1), str(f2)]]) is True
    d = sess.get("a.jpg")
    assert d["files"] == [str(f2)]
    assert d["stamps"] == [exporter.file_stamp(f2)]
    assert sess.pending_exports({"a.jpg"}) == []


def test_move_new_exdev_never_overwrites_race_file(tmp_path, monkeypatch):
    folder = tmp_path / "dest"
    folder.mkdir()
    src = tmp_path / "src.jpg"
    src.write_bytes(b"my-new-photo")

    def exdev_link(a, b):
        raise OSError(errno.EXDEV, "Cross-device link")

    real_unique = exporter.unique_path
    first = [True]

    def racing_unique(f: Path, name: str) -> Path:
        p = real_unique(f, name)
        if first[0]:
            first[0] = False
            p.write_bytes(b"existing-other-file")
        return p

    monkeypatch.setattr(os, "link", exdev_link)
    monkeypatch.setattr(exporter, "unique_path", racing_unique)

    dst = exporter.move_new(src, folder, "photo.jpg")
    assert (folder / "photo.jpg").read_bytes() == b"existing-other-file"
    assert dst == folder / "photo_2.jpg"
    assert dst.read_bytes() == b"my-new-photo"
    assert not src.exists()


def test_move_new_keeps_committed_export_when_windows_locks_part_file(tmp_path, monkeypatch):
    folder = tmp_path / "dest"
    folder.mkdir()
    src = folder / "photo.jpg.part"
    src.write_bytes(b"photo-bytes")
    real_unlink = os.unlink

    def locked_part(path, *args, **kwargs):
        if Path(path) == src:
            raise PermissionError(13, "Access is denied", str(src))
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", locked_part)

    dst = exporter.move_new(src, folder, "photo.jpg")

    assert dst.read_bytes() == b"photo-bytes"
    assert src.exists()  # rimozione temporaneamente negata: si conserva la copia valida


def test_live_sessions_handles_concurrent_mutation(tmp_path):
    root = tmp_path / "root"
    out = tmp_path / "out"
    root.mkdir()
    out.mkdir()
    s = exporter.Session(root, out, ids=["a.jpg"])
    assert s in exporter._live_sessions()
    assert isinstance(exporter._recorded_files(), set)
    target = out / "Foto" / "test.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"123")
    assert isinstance(exporter._made_during_session(target), bool)
