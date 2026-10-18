"""La dimensione a schermo di un fotogramma cambia SOLO quando si zooma: cambiando fotogramma
(striscia, frecce, Più nitida, Live, video) la foto resta della misura della finestra."""
from __future__ import annotations

from PySide6.QtCore import Qt

from test_core import LIVE, LONG
from test_ui import go, open_folder, press, pump, qapp, sd, sd_template, win, wait  # noqa: F401
from test_live_still_size import fit_size, shown_size


def settle(qa, w, tag: str):
    """Aspetta che il fotogramma esatto sia arrivato, poi misura."""
    key = (w.current().id, w.shown_frame)
    wait(qa, lambda: key in w.exact_cache or not w.current().is_clip, 20)
    pump(qa, 0.3)
    shown, fit = shown_size(w), fit_size(w)
    assert abs(shown[0] - fit[0]) <= 2 and abs(shown[1] - fit[1]) <= 2, \
        f"{tag}: mostrata {shown}, misura della finestra {fit}"
    return shown


def test_video_frame_size_changes_only_with_zoom(qapp, win, sd):
    win.resize(1440, 900)
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    sizes = []
    for n in (5, 30, 60):
        win.on_strip_picked(n)
        pump(qapp, 0.2)
        sizes.append(settle(qapp, win, f"fotogramma {n}"))
    press(qapp, win, Qt.Key_Down)
    sizes.append(settle(qapp, win, "freccia"))
    assert len(set(sizes)) == 1, f"la misura cambia senza zoom: {sizes}"


def test_live_frame_size_changes_only_with_zoom(qapp, win, sd):
    win.resize(1440, 900)
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    sizes = [settle(qapp, win, "appena aperta")]
    for n in (10, 50):
        win.on_strip_picked(n)
        pump(qapp, 0.2)
        sizes.append(settle(qapp, win, f"fotogramma {n}"))
    press(qapp, win, Qt.Key_Up, Qt.ShiftModifier)
    sizes.append(settle(qapp, win, "Maiusc+←"))
    assert len(set(sizes)) == 1, f"la misura cambia senza zoom: {sizes}"


def test_zoom_is_the_only_thing_that_changes_the_size(qapp, win, sd):
    win.resize(1440, 900)
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    win.on_strip_picked(20)
    base = settle(qapp, win, "prima dello zoom")
    win.image_view.zoom_by(1.5)                  # zoom: la foto deve cambiare misura
    pump(qapp, 0.2)
    zoomed = shown_size(win)
    assert zoomed != base, "lo zoom non ha cambiato la misura"
    win.image_view.fit()                         # tornata intera: misura di prima
    pump(qapp, 0.2)
    assert shown_size(win) == base
