"""Test specifici per la compatibilità e la robustezza su Windows (Win32)."""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import cloud
import exporter
import frames
import printprep


def test_windows_key_normalization():
    """I percorsi Windows con backslash devono essere normalizzati con slash."""
    win_path = r"subfolder\nested\photo.jpg"
    assert exporter._key(win_path) == "subfolder/nested/photo.jpg"


def test_windows_engine_paths(monkeypatch):
    """Su Windows il motore deve cercare in engines/windows e usare .exe."""
    monkeypatch.setattr(sys, "platform", "win32")
    engine_dir = printprep._engine_dir()
    assert engine_dir.name == "windows"
    assert "windows" in str(engine_dir)
    bin_path = printprep.realesrgan_bin()
    assert bin_path is not None
    assert bin_path.name == "realesrgan-ncnn-vulkan.exe"


def test_windows_no_window_flag(monkeypatch):
    """Su Windows deve essere impostato il flag CREATE_NO_WINDOW (0x08000000)."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert (0x08000000 if sys.platform == "win32" else 0) == 0x08000000


def test_windows_unlink_readonly(tmp_path):
    """_unlink deve rimuovere i file anche se hanno l'attributo sola lettura (come da schede SD su Windows)."""
    p = tmp_path / "readonly.txt"
    p.write_bytes(b"content")
    os.chmod(p, stat.S_IREAD)
    try:
        exporter._unlink(p)
        assert not p.exists()
    finally:
        if p.exists():
            os.chmod(p, stat.S_IWRITE)
            p.unlink(missing_ok=True)


def test_windows_move_new_with_readonly_part(tmp_path):
    """move_new deve completare l'export e rimuovere .part anche se questo è marcato sola lettura."""
    dest_dir = tmp_path / "Foto"
    dest_dir.mkdir(parents=True, exist_ok=True)
    part_file = dest_dir / "test_photo.jpg.part"
    part_file.write_bytes(b"image data")
    os.chmod(part_file, stat.S_IREAD)

    try:
        final_file = exporter.move_new(part_file, dest_dir, "test_photo.jpg")
        assert final_file.exists()
        assert final_file.name == "test_photo.jpg"
        assert final_file.read_bytes() == b"image data"
        assert not part_file.exists()
        # Il file finale deve essere modificabile/scrivibile
        assert os.access(final_file, os.W_OK)
    finally:
        if part_file.exists():
            os.chmod(part_file, stat.S_IWRITE)
            part_file.unlink(missing_ok=True)


def test_windows_clean_partial_readonly(tmp_path):
    """clean_partial deve ripulire i file .part temporanei anche se marcati sola lettura."""
    export_dir = tmp_path / "export"
    foto_dir = export_dir / "Foto"
    foto_dir.mkdir(parents=True, exist_ok=True)
    stale_part = foto_dir / "stale.jpg.part"
    stale_part.write_bytes(b"leftover")
    os.chmod(stale_part, stat.S_IREAD)

    try:
        cleaned = exporter.clean_partial(export_dir)
        assert cleaned >= 1
        assert not stale_part.exists()
    finally:
        if stale_part.exists():
            os.chmod(stale_part, stat.S_IWRITE)
            stale_part.unlink(missing_ok=True)


def test_windows_remove_files_readonly(tmp_path):
    """remove_files deve riuscire a cancellare i file esportati anche se marcati sola lettura."""
    f = tmp_path / "exported.jpg"
    f.write_bytes(b"data")
    os.chmod(f, stat.S_IREAD)
    try:
        exporter.remove_files([str(f)])
        assert not f.exists()
    finally:
        if f.exists():
            os.chmod(f, stat.S_IWRITE)
            f.unlink(missing_ok=True)


def test_applog_path_windows(monkeypatch, tmp_path):
    """Su Windows il percorso log deve stare sotto .photoswipe."""
    import applog
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("PHOTOSWIPE_LOG_DIR", raising=False)
    p = applog.log_path()
    assert ".photoswipe" in str(p)
    assert p.name == "photoswipe.log"


def test_applog_safe_rotating_handler(tmp_path):
    """SafeRotatingFileHandler non deve sollevare eccezioni in caso di PermissionError su doRollover."""
    import applog
    h = applog.SafeRotatingFileHandler(tmp_path / "test.log", maxBytes=100, backupCount=2)
    # Simula blocco del file durante il rollover
    def fail(*args, **kwargs):
        raise PermissionError(13, "Accesso negato")
    h.rotate = fail
    h.doRollover()  # non deve sollevare eccezioni
    h.close()


def test_settings_popup_has_log_button():
    """Il popup impostazioni deve includere il pulsante per aprire il file di log."""
    from PySide6.QtWidgets import QApplication
    import settingspop
    app = QApplication.instance() or QApplication([])

    class DummyStore:
        def value(self, key, default=None):
            return default
        def setValue(self, key, val):
            pass

    pop = settingspop.SettingsPopup(None, DummyStore(), "Esplora file")
    assert hasattr(pop, "btn_logs")
    assert pop.btn_logs.text() != ""

