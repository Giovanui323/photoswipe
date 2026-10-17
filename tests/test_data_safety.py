"""Test sui rischi di perdita dati: ripresa, export, 'cancellare', annullamento, salvataggio."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import exporter  # noqa: E402
from scanner import scan  # noqa: E402


def photo_pair(folder: Path, stem: str = "IMG_0001") -> tuple[Path, Path]:
    """JPG + DNG con lo stesso nome (il DNG è finto: basta che esista)."""
    folder.mkdir(parents=True, exist_ok=True)
    jpg, dng = folder / f"{stem}.JPG", folder / f"{stem}.DNG"
    Image.new("RGB", (64, 48), "green").save(jpg, quality=90)
    dng.write_bytes(b"raw-data" * 100)
    return jpg, dng


# 1 ------------------------------------------------------------------------------------------
def test_resume_never_touches_exports_already_recorded(tmp_path):
    root, export = tmp_path / "src", tmp_path / "out"
    root.mkdir()
    export.mkdir()
    edited = export / "IMG_0001.JPG"
    edited.write_bytes(b"ritoccata dall'utente")
    s = exporter.Session(root, export)
    s.set("IMG_0001.JPG", "yes", [edited, export / "IMG_0001.DNG"])  # DNG tolto a mano
    s.set("IMG_0002.JPG", "yes", [])                                   # copia mai finita
    s.set("IMG_0003.JPG", "skip")
    ids = {"IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG"}
    assert s.pending_exports(ids) == ["IMG_0002.JPG"]
    assert edited.read_bytes() == b"ritoccata dall'utente"


# 2 ------------------------------------------------------------------------------------------
def test_iphone_live_photo_exports_original_image(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    Image.new("RGB", (400, 300), "red").save(root / "IMG_0001.JPG", quality=95)
    (root / "IMG_0001.MOV").write_bytes(b"mov" * 1000)
    [item] = scan(root)
    assert item.kind == "photo" and item.video is not None
    out = exporter.export_item(item, None, tmp_path / "out", exporter.Settings())
    assert [p.name for p in out] == ["IMG_0001.JPG"]
    assert out[0].read_bytes() == item.image.read_bytes()            # l'originale, non un fotogramma
    out = exporter.export_item(item, None, tmp_path / "out2", exporter.Settings(copy_video=True))
    assert out[1] == tmp_path / "out2" / exporter.VIDEO_SUBDIR / "IMG_0001.MOV"
    moved = exporter.move_to_trash(item, root)                         # X sposta anche il MOV
    assert {Path(s).name for s, _ in moved} == {"IMG_0001.JPG", "IMG_0001.MOV"}


# 3 ------------------------------------------------------------------------------------------
@pytest.mark.skipif(os.geteuid() == 0, reason="root scrive ovunque")
def test_failed_export_keeps_choice_and_unreachable_export_detected(tmp_path):
    locked = tmp_path / "Volumes"
    locked.mkdir()
    locked.chmod(0o555)  # come /Volumes con il disco scollegato
    try:
        assert not exporter.export_reachable(locked / "SSD" / "export")
    finally:
        locked.chmod(0o755)
    assert exporter.export_reachable(tmp_path / "nuova" / "export")   # si potrà creare
    assert not (tmp_path / "nuova").exists()                           # ...ma non la crea ora

    root = tmp_path / "src"
    root.mkdir()
    s = exporter.Session(root, tmp_path / "out")
    s.set("a.jpg", "yes", [])
    s.mark_export("a.jpg", "t1")
    assert s.record_export("a.jpg", "t1", OSError("disco scollegato")) == "failed"
    assert s.get("a.jpg")["choice"] == "yes"                           # la scelta resta
    assert exporter.Session(root, tmp_path / "out").pending_exports({"a.jpg"}) == ["a.jpg"]
    assert s.record_export("a.jpg", "t1", [tmp_path / "out" / "a.jpg"]) == "ok"
    assert "export_failed" not in s.get("a.jpg")


# 4 ------------------------------------------------------------------------------------------
def test_stale_export_result_does_not_touch_newer_decision(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    s = exporter.Session(root, tmp_path / "out")
    s.set("a.jpg", "yes", [])
    s.mark_export("a.jpg", "vecchio")
    moved = [[str(root / "a.jpg"), str(root / exporter.TRASH_DIR / "a.jpg")]]
    s.set("a.jpg", "trash", moved=moved)                               # Z poi X prima della fine
    assert s.record_export("a.jpg", "vecchio", FileNotFoundError("a.jpg")) == "stale"
    assert s.get("a.jpg")["moved"] == moved                            # traccia dei file intatta
    s.set("a.jpg", "yes", [])
    s.mark_export("a.jpg", "nuovo")
    assert s.record_export("a.jpg", "vecchio", [root / "x.jpg"]) == "stale"
    assert s.get("a.jpg")["files"] == []


# 5 ------------------------------------------------------------------------------------------
def test_move_to_trash_is_all_or_nothing(tmp_path, monkeypatch):
    root = tmp_path / "src"
    jpg, dng = photo_pair(root / "DCIM")
    [item] = scan(root)
    real_move, calls = shutil.move, []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise PermissionError("file bloccato")
        return real_move(src, dst)
    monkeypatch.setattr(exporter.shutil, "move", flaky)
    with pytest.raises(PermissionError):
        exporter.move_to_trash(item, root)
    assert jpg.exists() and dng.exists()                               # il primo è tornato a posto
    assert not (root / exporter.TRASH_DIR).exists()


# 6 ------------------------------------------------------------------------------------------
def test_unreadable_session_is_kept_not_overwritten(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    broken = b'{"decisions": {"a.jpg": {"choice": "trash", "moved": [["/x/a.jpg", "/x/cance'
    (root / exporter.SESSION_FILE).write_bytes(broken)
    s = exporter.Session(root, tmp_path / "out")
    assert s.decisions == {} and s.corrupt_backup is not None
    assert s.corrupt_backup.read_bytes() == broken                    # conservato com'era
    s.save()
    assert s.corrupt_backup.read_bytes() == broken
    assert exporter.Session(root, tmp_path / "out").corrupt_backup is None  # il nuovo è valido


# 7 ------------------------------------------------------------------------------------------
def test_move_to_trash_through_symlinked_root(tmp_path):
    real = tmp_path / "real"
    jpg, dng = photo_pair(real / "DCIM")
    link = tmp_path / "Dropbox"
    link.symlink_to(real)
    [item] = scan(link)
    moved = exporter.move_to_trash(item, link)                         # prima: ValueError
    assert not jpg.exists() and (real / exporter.TRASH_DIR / "DCIM" / "IMG_0001.JPG").exists()
    exporter.restore_from_trash(moved)
    assert jpg.exists() and dng.exists()


# 8 ------------------------------------------------------------------------------------------
def test_restore_never_overwrites_and_can_be_retried(tmp_path, monkeypatch):
    root = tmp_path / "src"
    jpg, dng = photo_pair(root)
    [item] = scan(root)
    original = jpg.read_bytes()
    moved = exporter.move_to_trash(item, root)
    jpg.write_bytes(b"nuovo file con lo stesso nome")                  # posto originale occupato
    real_move, calls = shutil.move, []

    def fail_once(src, dst):
        calls.append(src)
        if len(calls) == 1:
            raise OSError("disco pieno")
        return real_move(src, dst)
    monkeypatch.setattr(exporter.shutil, "move", fail_once)
    with pytest.raises(OSError):
        exporter.restore_from_trash(moved)                             # l'app non perde la scelta
    renamed = exporter.restore_from_trash(moved)                       # Z di nuovo: riprende
    assert jpg.read_bytes() == b"nuovo file con lo stesso nome"        # non sovrascritto
    assert [p.name for p in renamed] == ["IMG_0001_2.JPG"]
    assert renamed[0].read_bytes() == original and dng.exists()
