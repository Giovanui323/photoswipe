"""Live: la foto ferma ha la dimensione giusta (adattata alla finestra) anche appena aperta,
dopo "Vedi Live" e tornando alla foto, e non solo dopo aver cambiato fotogramma."""
from __future__ import annotations

from test_core import LIVE
from test_ui import click, go, open_folder, pump, qapp, sd, sd_template, win, wait  # noqa: F401


def shown_size(w) -> tuple[int, int]:
    v = w.image_view
    k = v.transform().m11()
    return round(v.item.boundingRect().width() * k), round(v.item.boundingRect().height() * k)


def fit_size(w) -> tuple[int, int]:
    v = w.image_view
    k = v._fit_k()
    return round(v.full.width() * k), round(v.full.height() * k)


def assert_fitted(w, tag: str):
    shown, fit = shown_size(w), fit_size(w)
    assert abs(shown[0] - fit[0]) <= 2 and abs(shown[1] - fit[1]) <= 2, \
        f"{tag}: mostrata {shown}, dovrebbe essere {fit} (finestra {w.image_view.viewport().size().width()}x{w.image_view.viewport().size().height()})"


def test_live_still_fills_window_when_opened(qapp, win, sd):
    win.resize(1440, 900)
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    pump(qapp, 0.5)
    assert_fitted(win, "appena aperta")


def test_live_still_fills_window_after_video_and_back(qapp, win, sd):
    win.resize(1440, 900)
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    click(qapp, win, win.btn_live)               # vedi Live
    pump(qapp, 0.5)
    click(qapp, win, win.btn_live)               # torna alla foto
    pump(qapp, 0.5)
    assert_fitted(win, "dopo Vedi Live e ritorno")


def test_live_still_fills_window_after_changing_frame(qapp, win, sd):
    win.resize(1440, 900)
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    win.step(3)
    pump(qapp, 0.5)
    assert_fitted(win, "dopo cambio fotogramma")
