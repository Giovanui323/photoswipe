"""Striscia dei fotogrammi: mentre il video della Live va, la linea segue il punto del video
(e non c'è il riquadro della foto scelta). Tornati alla foto, il riquadro torna dove era."""
from __future__ import annotations

from test_core import LIVE
from test_ui import click, go, open_folder, pump, qapp, sd, sd_template, win  # noqa: F401


def test_live_playing_shows_playhead_at_video_position(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    win.on_strip_picked(20)                      # foto scelta: fotogramma 20
    pump(qapp, 0.2)
    assert win.strip.selected == 20
    click(qapp, win, win.btn_live)               # vedi Live: il video parte
    pump(qapp, 0.1)
    info = win.infos[win.current().id]
    assert win.live_view and win.strip.selected is None   # niente riquadro sulla foto
    for seconds in (0.0, 1.0, 2.0):              # il video va avanti
        win.on_position(int(seconds * 1000))
        assert win.strip.playhead == info.frame_at(seconds)
        assert win.strip.selected is None         # la linea è quella del video
    assert win.strip.playhead == info.frame_at(2.0)


def test_back_to_photo_brings_the_chosen_frame_back(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    win.on_strip_picked(20)
    pump(qapp, 0.2)
    click(qapp, win, win.btn_live)
    pump(qapp, 0.1)
    win.on_position(1000)
    click(qapp, win, win.btn_live)               # torna alla foto
    pump(qapp, 0.2)
    assert not win.live_view
    assert win.strip.selected == win.live_photo_frame(win.current())
    assert win.strip.playhead is None
