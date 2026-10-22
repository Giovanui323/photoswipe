"""Fasi che prima non avevano test: download iCloud, pulizia dei parziali, preferiti e archivio
del salvataggio, dialogo "lavoro già iniziato", Spotlight e fuso dei video, auto-colore, pannello
Regola (ripristino e accensione di una sezione), freccia dei menu."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from PIL import Image
from PySide6.QtWidgets import QMessageBox

import app as A
import cloud
import edits
import editpanel
import exporter
import frames
from test_ui import PHOTO1, qapp, sd, sd_template, win  # noqa: F401  (fixture del pacchetto)


# ------------------------------------------------------------------ iCloud: cloud.download

def test_local_file_is_ready_without_touching_it(tmp_path, monkeypatch):
    f = tmp_path / "IMG_0001.JPG"
    f.write_bytes(b"x")
    run = mock.Mock(side_effect=AssertionError("brctl non deve partire"))
    monkeypatch.setattr(cloud.subprocess, "run", run)
    assert cloud.download(f) is True
    run.assert_not_called()


def test_dataless_file_is_forced_by_reading_it(tmp_path, monkeypatch):
    f = tmp_path / "IMG_0002.JPG"
    f.write_bytes(b"dati" * 100)
    states = iter([False, True])          # prima "solo nel cloud", poi "scaricato" dopo la lettura
    monkeypatch.setattr(cloud, "is_local", lambda p: next(states, True))
    run = mock.Mock(side_effect=AssertionError("brctl non deve partire"))
    monkeypatch.setattr(cloud.subprocess, "run", run)
    assert cloud.download(f) is True
    run.assert_not_called()


def test_stub_only_file_goes_through_brctl_until_it_is_local(tmp_path, monkeypatch):
    path = tmp_path / "IMG_0003.JPG"          # il file vero non c'è: solo lo stub .icloud
    cloud.stub_for(path).write_bytes(b"")
    monkeypatch.setattr(sys, "platform", "darwin")
    arrived = {"ok": False}

    def fake_run(args, **kw):
        assert args[:2] == ["brctl", "download"]
        assert args[2] == str(cloud.stub_for(path))
        arrived["ok"] = True                  # brctl ha finito: ora il file è in locale
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cloud.subprocess, "run", fake_run)
    monkeypatch.setattr(cloud, "is_local", lambda p: arrived["ok"])
    assert cloud.download(path, timeout=5) is True
    assert arrived["ok"]


def test_gives_up_without_crashing_when_download_never_arrives(tmp_path, monkeypatch):
    path = tmp_path / "IMG_0004.JPG"          # né file né stub: brctl fallisce
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(cloud, "is_local", lambda p: False)
    monkeypatch.setattr(cloud.subprocess, "run",
                        mock.Mock(side_effect=subprocess.SubprocessError("niente brctl")))
    assert cloud.download(path, timeout=0.2) is False


# ------------------------------------------------------------------ parziali di export

def test_clean_partial_removes_only_app_temp_copies(tmp_path):
    export = tmp_path / "export"
    (export / "Video").mkdir(parents=True)
    (export / "Foto" / "Preferite").mkdir(parents=True)
    (export / "Foto" / "a.JPG.part").write_bytes(b"x")
    (export / "Foto" / "Preferite" / "b.JPG.part.png").write_bytes(b"x")
    (export / "Video" / "c.MOV.part").write_bytes(b"x")
    (export / "Foto" / "keep.JPG").write_bytes(b"x")
    (export / "Foto" / "notes.part.txt").write_bytes(b"x")   # non è un parziale dell'app
    assert exporter.clean_partial(export) == 3
    assert sorted(p.name for p in export.rglob("*") if p.is_file()) == ["keep.JPG", "notes.part.txt"]


def test_clean_partial_leaves_the_users_own_part_files(tmp_path):
    # la cartella export può essere una cartella dell'utente (es. Download)
    export = tmp_path / "Download"
    (export / "deep").mkdir(parents=True)
    (export / "Foto" / "album").mkdir(parents=True)
    user = [export / "film.mkv.part", export / "deep" / "img.part.png",
            export / "Foto" / "album" / "x.JPG.part"]
    for f in user:
        f.write_bytes(b"x")
    assert exporter.clean_partial(export) == 0
    assert all(f.exists() for f in user)


def test_clean_partial_on_missing_folder_is_zero(tmp_path):
    assert exporter.clean_partial(tmp_path / "non_c_e") == 0


# ------------------------------------------------------------------ salvataggio: preferiti e archivio

def test_favorite_is_saved_and_toggles_off(tmp_path):
    root, export = tmp_path / "src", tmp_path / "out"
    root.mkdir()
    s = exporter.Session(root, export)
    assert s.toggle_favorite("IMG_0001.JPG") is True
    assert exporter.Session(root, export).favorites == {"IMG_0001.JPG"}   # riletto dal disco
    assert s.toggle_favorite("IMG_0001.JPG") is False
    assert exporter.Session(root, export).favorites == set()


def test_archive_keeps_old_choices_as_backup(tmp_path):
    root, export = tmp_path / "src", tmp_path / "out"
    root.mkdir()
    s = exporter.Session(root, export)
    s.set("IMG_0001.JPG", "yes", [])
    s.save()
    s.archive()
    assert s.decisions == {}
    assert not (root / exporter.SESSION_FILE).exists()
    backups = list(root.glob(exporter.SESSION_FILE + "*.bak"))
    assert len(backups) == 1 and "IMG_0001.JPG" in backups[0].read_text("utf-8")


# ------------------------------------------------------------------ dialogo "lavoro già iniziato"

def _saved_work(root: Path, export: Path) -> None:
    s = exporter.Session(root, export)
    s.set(PHOTO1, "yes", [])
    s.save()


def _press_in_dialog(monkeypatch, text: str, shown: list) -> None:
    """Simula il clic su un pulsante del QMessageBox senza mostrare nulla."""
    def fake_exec(self):
        shown.append(self.text())
        for b in self.buttons():
            if b.text() == text:
                b.click()
                return 0
        raise AssertionError(f"pulsante non trovato: {text}")
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)


def test_no_dialog_when_folder_was_never_worked(qapp, win, sd, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(1) or 0)
    win.ask_about_saved_work(sd)
    assert shown == []


def test_resume_opens_the_saved_export_folder(qapp, win, sd, monkeypatch):
    export = sd / "export"
    export.mkdir()
    _saved_work(sd, export)
    shown, started = [], mock.Mock()
    monkeypatch.setattr(win, "start_from_setup", started)
    _press_in_dialog(monkeypatch, "Riprendi da dove eri", shown)
    win.ask_about_saved_work(sd)
    assert len(shown) == 1 and "lavoro a metà" in shown[0]
    started.assert_called_once()
    assert win.pick_export == export


def test_resume_asks_for_export_when_saved_folder_is_gone(qapp, win, sd, monkeypatch):
    _saved_work(sd, sd / "export_di_allora")     # la cartella export non esiste più
    monkeypatch.setattr(exporter, "export_reachable", lambda p: False)
    started = mock.Mock()
    monkeypatch.setattr(win, "start_from_setup", started)
    _press_in_dialog(monkeypatch, "Riprendi da dove eri", [])
    win.ask_about_saved_work(sd)
    started.assert_not_called()                  # niente avvio: prima bisogna scegliere dove copiare
    assert win.pick_export is None
    assert win.setup_note.isVisible()
    assert "export_di_allora" in win.setup_note.text()


def test_cancel_changes_nothing(qapp, win, sd, monkeypatch):
    export = sd / "export"
    export.mkdir()
    _saved_work(sd, export)
    started = mock.Mock()
    monkeypatch.setattr(win, "start_from_setup", started)
    _press_in_dialog(monkeypatch, "Annulla", [])
    win.ask_about_saved_work(sd)
    started.assert_not_called()
    assert (sd / exporter.SESSION_FILE).exists()


def test_restart_archives_the_old_work_after_confirmation(qapp, win, sd, monkeypatch):
    export = sd / "export"
    export.mkdir()
    _saved_work(sd, export)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    _press_in_dialog(monkeypatch, "Ricomincia da capo", [])
    win.ask_about_saved_work(sd)
    assert not (sd / exporter.SESSION_FILE).exists()
    assert list(sd.glob(exporter.SESSION_FILE + "*.bak"))   # rinominato, non cancellato


# ------------------------------------------------------------------ Spotlight (video su iCloud)

def test_spotlight_dims_is_none_outside_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert frames.spotlight_dims(tmp_path / "v.MP4") is None


@pytest.mark.parametrize("stdout, expected", [
    (b"1920\x001080", (1920, 1080)),     # risposta normale di mdls
    (b"0\x000", None),                   # dimensioni non note
    (b"", None),                         # niente risposta
])
def test_spotlight_dims_parses_mdls_answer(tmp_path, monkeypatch, stdout, expected):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(frames.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stdout=stdout))
    assert frames.spotlight_dims(tmp_path / "v.MP4") == expected


def test_spotlight_dims_survives_missing_mdls(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(frames.subprocess, "run", mock.Mock(side_effect=FileNotFoundError))
    assert frames.spotlight_dims(tmp_path / "v.MP4") is None


# ------------------------------------------------------------------ fuso orario dei video

def _info(created_utc):
    return frames.VideoInfo(1920, 1080, Fraction(30), 4.0, 120, created_utc=created_utc)


def test_capture_time_without_camera_clock_is_kept_as_is():
    name_time = datetime(2026, 7, 30, 13, 22, 10)
    assert frames.capture_times(name_time, _info(None), None) == (name_time, None)


def test_camera_offset_is_rounded_to_quarter_hours():
    created = datetime(2026, 7, 30, 11, 22, 10, tzinfo=timezone.utc)
    name_time = datetime(2026, 7, 30, 13, 22, 10)        # orologio della camera: UTC+2
    when, off = frames.capture_times(name_time, _info(created), None)
    assert when == name_time and off == timedelta(hours=2)


def test_timezone_override_uses_utc_with_the_travel_zone():
    created = datetime(2026, 7, 30, 11, 22, 10, tzinfo=timezone.utc)
    name_time = datetime(2026, 7, 30, 13, 22, 10)
    when, off = frames.capture_times(name_time, _info(created), 5)
    assert when == datetime(2026, 7, 30, 16, 22, 10)     # UTC+5 scelto dall'utente
    assert off == timedelta(hours=5)


# ------------------------------------------------------------------ auto-colore classico

def test_grey_photo_gets_vibrance_and_no_saturation_cut():
    out = edits.classic_auto_color(Image.new("RGB", (60, 60), (120, 120, 120)))
    assert out["vibrance"] == pytest.approx(0.45)
    assert "saturation" not in out


def test_already_vivid_photo_gets_only_a_saturation_cut():
    out = edits.classic_auto_color(Image.new("RGB", (60, 60), (255, 0, 0)))
    assert "vibrance" not in out
    assert out["saturation"] == pytest.approx(-0.25)


# ------------------------------------------------------------------ pannello Regola

def test_reset_section_clears_only_that_section(qapp):
    p = editpanel.RegolaPanel()
    p.edit = {"exposure": 0.5, "contrast": 0.3, "saturation": 0.2, "off": ["light"]}
    seen = []
    p.changed.connect(seen.append)
    p.reset_section("light")
    assert "exposure" not in p.edit and "contrast" not in p.edit
    assert p.edit["saturation"] == 0.2                   # l'altra sezione resta
    assert "light" not in p.edit["off"]
    assert seen and "exposure" not in seen[-1]


def test_toggle_section_switches_it_off_and_back_on(qapp):
    p = editpanel.RegolaPanel()
    p.edit = {"exposure": 0.5}
    p.toggle_section("light")
    assert "light" in p.edit["off"]
    p.toggle_section("light")
    assert "light" not in p.edit["off"]


def test_toggle_on_untouched_section_asks_for_automatic(qapp):
    p = editpanel.RegolaPanel()
    p.edit = {}
    asked = []
    p.auto_requested.connect(asked.append)
    p.toggle_section("light")
    assert asked == ["light"]
    assert "off" not in p.edit or "light" not in p.edit["off"]


# ------------------------------------------------------------------ freccia dei menu

def test_chevron_file_is_a_real_png(qapp):
    path = Path(A.chevron_file())
    assert path.is_file()
    with Image.open(path) as im:
        assert im.format == "PNG" and im.size == (20, 12)
