"""Fotolibro "Ultime foto approvate": conta anche le foto prese dai video, e il clic riporta lì."""
from __future__ import annotations

from test_ui import (LONG, PHOTO1, PHOTO2, Qt, exports_done, go, open_folder, press, pump,  # noqa: F401
                     qapp, sd, sd_template, wait, win)


def test_photobook_has_video_snaps_and_click_goes_back_to_them(qapp, win, sd):
    """Le foto prese da un video entrano nel libro al posto del video (dall'ultimo fotogramma),
    anche se il video è NO; clic su una foto presa = il video torna fermo su quel fotogramma."""
    open_folder(qapp, win, sd)
    photos = [it.main.name for it in win.items if it.kind == "photo"]   # PHOTO1, PHOTO2, poi 4 foto
    for n in (PHOTO1, PHOTO2):
        go(qapp, win, n)
        press(qapp, win, Qt.Key_Y)
    go(qapp, win, f"{LONG}.MP4")
    for frame in (30, 60):
        win.on_strip_picked(frame)
        pump(qapp, 0.2)
        press(qapp, win, Qt.Key_F)
    keys = lambda: [p.key for p in win.photobook.items]  # noqa: E731
    vid = win.current().id
    assert keys()[:2] == [f"{vid}#f60", f"{vid}#f30"]   # già sul video: le sue foto prese
    press(qapp, win, Qt.Key_N)   # video NO: le foto prese restano in export, e nel libro
    go(qapp, win, photos[2])
    press(qapp, win, Qt.Key_Y)
    go(qapp, win, photos[2])
    exports_done(qapp, win)
    first = win.items[win.idx].id
    assert keys() == [first, f"{vid}#f60", f"{vid}#f30", win.items[2].id, win.items[1].id]
    assert win.photobook.isVisible()
    assert wait(qapp, lambda: (win.update_counter() or True)
                and all(k in win.photobook.book._thumbs for k in keys())), "miniature delle foto prese"
    win.photobook.opened.emit(f"{vid}#f30")   # clic sulla foto presa
    assert wait(qapp, lambda: win.current().id == vid and win.current_frame() == 30), "non torna al fotogramma"
    win.photobook.opened.emit(win.items[1].id)   # clic su una foto: si torna lì per cambiare scelta
    pump(qapp, 0.1)
    assert win.current().main.name == PHOTO1
