"""Bottone "✨ Più nitida": clic vero sul pulsante, quando si vede, bordi del video, errori e
risultati che arrivano tardi. In fondo: le miniature della striscia sono abbastanza grandi
per la casella su Retina (foto verticali e panorami)?"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

import app as A
import frames
from scanner import Item
from test_core import LONG
from test_frames_exact import SHARP, blurry_sd, bsd  # noqa: F401
from test_ui import click, go, open_folder, pump, qapp, sd, sd_template, wait, win  # noqa: F401


def at_frame(qa, w, n: int) -> None:
    w.on_strip_picked(n)
    assert wait(qa, lambda: w.current_frame() == n)
    pump(qa, 0.2)


# ------------------------------------------------------------------ il pulsante

def test_button_visible_only_when_stopped_on_a_frame(qapp, win, bsd):
    open_folder(qapp, win, bsd)
    go(qapp, win, f"{LONG}.MP4")
    assert not win.btn_sharp.isVisible()          # video che va: niente fotogramma da migliorare
    at_frame(qapp, win, SHARP - 4)
    assert win.btn_sharp.isVisible()


def test_click_on_button_finds_sharp_frame(qapp, win, bsd):
    open_folder(qapp, win, bsd)
    go(qapp, win, f"{LONG}.MP4")
    at_frame(qapp, win, SHARP + 5)
    click(qapp, win, win.btn_sharp)
    assert wait(qapp, lambda: win.current_frame() == SHARP, 20), win.current_frame()
    assert wait(qapp, lambda: "cerco" not in win.frame_label.text(), 5), win.frame_label.text()


def test_already_sharp_frame_stays_and_label_clears(qapp, win, bsd):
    open_folder(qapp, win, bsd)
    go(qapp, win, f"{LONG}.MP4")
    at_frame(qapp, win, SHARP)
    click(qapp, win, win.btn_sharp)
    pump(qapp, 3)
    assert win.current_frame() == SHARP
    assert "cerco" not in win.frame_label.text(), win.frame_label.text()


def test_edges_of_video(qapp, win, bsd):
    open_folder(qapp, win, bsd)
    go(qapp, win, f"{LONG}.MP4")
    info = win.infos[win.current().id]
    src = bsd / "DCIM" / "DJI_001" / f"{LONG}.MP4"
    for n in (0, info.frames - 1):
        r = frames.sharpest_near(src, info, n)
        assert 0 <= r < info.frames and abs(r - n) <= 6, (n, r)


# ------------------------------------------------------------------ casi difficili

def test_error_does_not_leave_label_stuck_on_searching(qapp, win, bsd, monkeypatch):
    """Se la ricerca fallisce (ffmpeg, disco scollegato…) l'etichetta non deve restare su 'cerco…'."""
    def boom(*a, **k):
        raise RuntimeError("ffmpeg non risponde")
    monkeypatch.setattr(frames, "sharpest_near", boom)
    open_folder(qapp, win, bsd)
    go(qapp, win, f"{LONG}.MP4")
    at_frame(qapp, win, SHARP - 3)
    click(qapp, win, win.btn_sharp)
    pump(qapp, 1.5)
    assert win.current_frame() == SHARP - 3
    assert "cerco" not in win.frame_label.text(), f"etichetta bloccata: {win.frame_label.text()!r}"


def test_late_result_does_not_undo_a_later_move(qapp, win, bsd, monkeypatch):
    """Premi P, poi ti sposti con →: il risultato in ritardo non deve riportarti indietro."""
    real = frames.sharpest_near

    def slow(*a, **k):
        time.sleep(1.0)
        return real(*a, **k)
    monkeypatch.setattr(frames, "sharpest_near", slow)
    open_folder(qapp, win, bsd)
    go(qapp, win, f"{LONG}.MP4")
    at_frame(qapp, win, 20)
    click(qapp, win, win.btn_sharp)
    for _ in range(10):
        win.step(1)                               # l'utente va avanti (→) mentre si cerca
        pump(qapp, 0.02)
    assert win.current_frame() == 30
    pump(qapp, 2.5)
    assert win.current_frame() == 30, f"il risultato tardivo ha spostato su {win.current_frame()}"


# ------------------------------------------------------------------ miniature

CELL_DEVICE = (round(A.ThumbStrip.CELL_W * 1.18 * 2), round(A.ThumbStrip.CELL_H * 1.18 * 2))  # Retina


def thumb_of(tmp: Path, size: tuple[int, int]):
    p = tmp / f"DJI_{size[0]}x{size[1]}.JPG"
    Image.new("RGB", size, "gray").save(p, quality=80)
    return A.MainWindow.make_thumb(Item(kind="photo", id=p.name, image=p))


def covers(img, cell) -> bool:
    """La miniatura ritagliata al centro riempie la casella senza essere ingrandita."""
    k = max(cell[0] / img.width(), cell[1] / img.height())
    return k <= 1.0


def test_thumb_landscape_is_sharp_enough(qapp, tmp_path):
    img = thumb_of(tmp_path, (4000, 3000))
    assert covers(img, CELL_DEVICE), (img.width(), img.height(), CELL_DEVICE)


def test_thumb_portrait_is_sharp_enough(qapp, tmp_path):
    img = thumb_of(tmp_path, (3000, 4000))
    assert covers(img, CELL_DEVICE), (img.width(), img.height(), CELL_DEVICE)


def test_thumb_panorama_is_sharp_enough(qapp, tmp_path):
    img = thumb_of(tmp_path, (9000, 1800))
    assert covers(img, CELL_DEVICE), (img.width(), img.height(), CELL_DEVICE)


# ------------------------------------------------------------------ memoria

def test_thumb_caches_have_a_ceiling(qapp, win):
    """Scorrendo migliaia di foto le miniature non si accumulano: la memoria resta limitata."""
    for k in range(1000):
        win.next_thumbs[f"foto{k}"] = A.QImage(184, 138, A.QImage.Format_RGB32)
        win.thumbs[f"video{k}"] = []
    assert len(win.next_thumbs) == win.next_thumbs.maxsize
    assert len(win.thumbs) == win.thumbs.maxsize
    assert "foto999" in win.next_thumbs and "foto0" not in win.next_thumbs


def test_lru_keeps_what_is_still_used():
    c = A.LruCache(3)
    c["a"], c["b"], c["c"] = 1, 2, 3
    assert c.get("a") == 1                        # usata di recente: resta
    c["d"] = 4
    assert list(c) == ["c", "a", "d"]
