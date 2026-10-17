"""Retrocompatibilità: salvataggi fatti con versioni vecchie, a un altro livello di cartella,
su un disco con un altro nome o su un altro computer (Mac o Windows)."""
import json
from pathlib import Path

import exporter
from exporter import SESSION_FILE, Session

# com'era il salvataggio della 1.1.7 (struttura reale, accorciata)
OLD = {
    "app": "PhotoSwipe", "root": "/Volumes/Backup/TRIP/DJI/1",
    "export": "/Users/qualcuno/Desktop/FOTODAHARDDISK1",
    "created": "2026-10-17T12:47:23", "updated": "2026-10-17T13:18:08",
    "closed": "2026-10-17T15:05:59", "total": 422, "completed": False,
    "decisions": {
        "DCIM/DJI_001/DJI_20260723215408_0001_D.JPG":
            {"choice": "no", "files": [], "frame": None, "with_video": False},
        "DCIM/DJI_001/DJI_20260728185459_0006_D.MP4#f187":
            {"choice": "snap", "files": ["/Users/qualcuno/Desktop/FOTODAHARDDISK1/x_f0188.jpg"],
             "frame": 187, "with_video": False},
        "DCIM/DJI_001/DJI_20260728185459_0006_D.MP4":
            {"choice": "yes", "files": [], "frame": None, "with_video": False, "noexport": True},
        "DCIM/DJI_001/DJI_20260730073450_0015_D.JPG":
            {"choice": "yes", "files": ["/Users/qualcuno/Desktop/FOTODAHARDDISK1/y.JPG"],
             "frame": None, "with_video": False},
    },
}
PHOTO = "DCIM/DJI_001/DJI_20260730073450_0015_D.JPG"


def save_at(folder: Path, data: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / SESSION_FILE).write_text(json.dumps(data))


def test_same_folder_on_another_computer(tmp_path):
    root = tmp_path / "DJI" / "1"
    save_at(root, OLD)
    s = Session(root, tmp_path / "nuovo_export")
    assert s.get(PHOTO)["choice"] == "yes"
    assert len(s.decisions) == 4
    info = Session.peek(root)
    assert info["decided"] == 3 and info["export_ok"] is False   # export di allora non c'è qui


def test_opened_one_level_up(tmp_path):
    save_at(tmp_path / "DJI" / "1", OLD)
    s = Session(tmp_path / "DJI", tmp_path / "exp")
    assert s.get("1/" + PHOTO)["choice"] == "yes"
    assert Session.peek(tmp_path / "DJI")["decided"] == 3


def test_opened_one_level_down(tmp_path):
    save_at(tmp_path / "DJI" / "1", OLD)
    s = Session(tmp_path / "DJI" / "1" / "DCIM", tmp_path / "exp")
    assert s.get("DJI_001/DJI_20260730073450_0015_D.JPG")["choice"] == "yes"
    assert len(s.decisions) == 4


def test_old_file_is_never_modified(tmp_path):
    save_at(tmp_path / "DJI" / "1", OLD)
    before = (tmp_path / "DJI" / "1" / SESSION_FILE).read_text()
    s = Session(tmp_path / "DJI", tmp_path / "exp")
    s.set("altro.JPG", "no")
    assert (tmp_path / "DJI" / "1" / SESSION_FILE).read_text() == before
    assert (tmp_path / "DJI" / SESSION_FILE).exists()


def test_windows_keys_and_missing_fields(tmp_path):
    data = {"decisions": {"DCIM\\DJI_001\\a.JPG": {"choice": "yes"},
                          "DCIM\\DJI_001\\b.JPG": {"choice": "no"},
                          "rotta.JPG": "non è una scelta"},
            "favorites": ["DCIM\\DJI_001\\a.JPG"]}
    save_at(tmp_path, data)
    s = Session(tmp_path, tmp_path / "exp")
    d = s.get("DCIM/DJI_001/a.JPG")
    assert d == {"choice": "yes", "files": [], "frame": None, "with_video": False}
    assert "DCIM/DJI_001/a.JPG" in s.favorites
    assert "rotta.JPG" not in s.decisions
    assert s.pending_exports({"DCIM/DJI_001/a.JPG"}) == ["DCIM/DJI_001/a.JPG"]  # mai copiata


def test_newest_save_wins_when_levels_overlap(tmp_path):
    save_at(tmp_path / "DJI" / "1", OLD)
    newer = {"updated": "2026-10-18T09:00:00",
             "decisions": {"DJI_001/DJI_20260730073450_0015_D.JPG": {"choice": "no", "files": []}}}
    save_at(tmp_path / "DJI" / "1" / "DCIM", newer)
    s = Session(tmp_path / "DJI" / "1", tmp_path / "exp")
    assert s.get(PHOTO)["choice"] == "no"


def test_renamed_volume_matches_export_fallback(tmp_path, monkeypatch):
    assert exporter._same_root("/Volumes/Backup/TRIP/DJI/1", "/Volumes/Backup 1/TRIP/DJI/1")
    assert exporter._same_root("/Volumes/Backup", "/Volumes/Backup 1")
    assert not exporter._same_root("/Volumes/SanDisk/DCIM", "/Volumes/Seagate/DCIM")
    assert not exporter._same_root("/Volumes/Backup/A", "/Volumes/Backup/B")
    assert not exporter._same_root("/Users/a/x", "/Users/b/x")


def test_restart_ignores_saves_of_other_levels(tmp_path):
    save_at(tmp_path / "DJI" / "1", OLD)
    Session(tmp_path / "DJI", tmp_path / "exp").archive()
    assert Session.peek(tmp_path / "DJI") is None
    assert Session(tmp_path / "DJI", tmp_path / "exp").decisions == {}
    assert len(Session(tmp_path / "DJI" / "1", tmp_path / "exp").decisions) == 4  # lì resta tutto
