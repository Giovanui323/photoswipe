"""Scegliere un fotogramma deve aggiornare l'app SUBITO: si vede il fotogramma giusto
dall'anteprima .LRF (720p) nello stesso istante, poi arriva quello esatto a risoluzione piena.
Le miniature in caricamento non devono far aspettare il fotogramma."""
from __future__ import annotations

import time

from PIL import Image
from PySide6.QtCore import Qt

import frames
from test_core import LIVE, LONG
from test_frames_exact import live_ref, video_ref, which  # noqa: F401
from test_ui import go, open_folder, press, pump, qapp, sd, sd_template, wait, win  # noqa: F401


def nearest(img: Image.Image, ref: list[Image.Image]) -> int:
    """Come which(), per l'anteprima JPEG: la compressione aggiunge un po' di rumore uguale per
    tutti i fotogrammi, quindi basta che il giusto sia chiaramente il più vicino."""
    from PIL import ImageChops, ImageStat
    from test_frames_exact import SMALL
    small = img.convert("L").resize(SMALL, Image.BILINEAR)
    diffs = [ImageStat.Stat(ImageChops.difference(small, r)).mean[0] for r in ref]
    order = sorted(range(len(diffs)), key=diffs.__getitem__)
    assert diffs[order[1]] > diffs[order[0]] + 0.3, f"non distinguibili: {diffs[order[0]]:.2f}"
    return order[0]


def on_screen(w) -> Image.Image:
    q = w.image_view.full.convertToFormat(w.image_view.full.Format.Format_RGB888)
    return Image.frombytes("RGB", (q.width(), q.height()), bytes(q.constBits()), "raw", "RGB",
                           q.bytesPerLine())


def open_live(qa, w, sd):
    open_folder(qa, w, sd)
    go(qa, w, f"{LIVE}.MP4")
    assert wait(qa, lambda: w.current().id in w.proxy_frames, 10), "anteprima .LRF non pronta"
    pump(qa, 0.3)


def test_pick_shows_the_right_frame_immediately(qapp, win, sd, live_ref):
    open_live(qapp, win, sd)
    for n in (5, 25, 60, 85):
        t = time.perf_counter()
        win.on_strip_picked(n)                     # nessun evento elaborato: deve essere già lì
        ms = (time.perf_counter() - t) * 1000
        assert ms < 100, f"fotogramma {n}: {ms:.0f} ms"
        assert win.shown_frame == n
        assert nearest(on_screen(win), live_ref) == n, "a schermo un fotogramma diverso"


def test_full_resolution_replaces_the_quick_frame(qapp, win, sd, live_ref):
    open_live(qapp, win, sd)
    info = win.infos[win.current().id]
    win.on_strip_picked(33)
    assert wait(qapp, lambda: (win.current().id, 33) in win.exact_cache, 10)
    pump(qapp, 0.1)
    assert win.image_view.full.width() == info.width
    assert which(on_screen(win), live_ref) == 33


def test_arrows_are_immediate(qapp, win, sd, live_ref):
    open_live(qapp, win, sd)
    win.on_strip_picked(40)
    for k in range(1, 6):
        win.step(1)                                # → senza aspettare
        assert win.shown_frame == 40 + k
        assert nearest(on_screen(win), live_ref) == 40 + k


def test_drag_across_the_strip_follows_without_waiting(qapp, win, sd, live_ref):
    open_live(qapp, win, sd)
    t = time.perf_counter()
    for n in range(10, 80, 3):                     # trascinamento veloce sulla striscia
        win.on_strip_picked(n)
        qapp.processEvents()
        assert nearest(on_screen(win), live_ref) == n
    assert time.perf_counter() - t < 1.5
    assert wait(qapp, lambda: (win.current().id, win.shown_frame) in win.exact_cache, 10)


def test_busy_thumbnails_do_not_delay_the_exact_frame(qapp, win, sd):
    """Coda delle miniature piena (cartella appena aperta): il 4K del fotogramma arriva lo stesso."""
    open_live(qapp, win, sd)
    for _ in range(12):
        win.bg.submit(time.sleep, 3)
    win.on_strip_picked(50)
    t = time.perf_counter()
    assert wait(qapp, lambda: (win.current().id, 50) in win.exact_cache, 10)
    assert time.perf_counter() - t < 2.0, "il fotogramma ha aspettato dietro le miniature"


def test_video_without_lrf_still_gets_the_exact_frame(qapp, win, sd, video_ref):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    assert win.current().id not in win.proxy_frames
    win.on_strip_picked(30)
    assert wait(qapp, lambda: (win.current().id, 30) in win.exact_cache, 10)
    pump(qapp, 0.1)
    assert which(on_screen(win), video_ref) == 30


def test_zoomed_keeps_its_size_when_full_resolution_arrives(qapp, win, sd):
    open_live(qapp, win, sd)
    win.on_strip_picked(20)
    assert wait(qapp, lambda: (win.current().id, 20) in win.exact_cache, 10)
    pump(qapp, 0.1)
    win.image_view.set_zoom_level(0.5)
    shown = win.image_view.item.boundingRect().width() * win.image_view.transform().m11()
    quick = win.proxy_image(win.current(), 21)    # risoluzione diversa da quella attuale
    win.image_view.set_image(quick, keep_zoom=True)
    after = win.image_view.item.boundingRect().width() * win.image_view.transform().m11()
    assert abs(after - shown) < 1, (shown, after)


def test_proxy_memory_is_limited(qapp, win, sd):
    open_live(qapp, win, sd)
    assert win.proxy_frames.maxsize <= 2
    start, jpgs = win.proxy_frames[win.current().id]
    assert len(jpgs) <= win.PROXY_SPAN


def test_proxy_window_frames_are_exact(sd, live_ref):
    lrf = sd / "DCIM" / "DJI_001" / f"{LIVE}.LRF"
    info = frames.probe(lrf)
    import io
    jpgs = frames.proxy_window(lrf, info, 30, 20)
    assert len(jpgs) == 20
    for k in (0, 7, 19):
        assert nearest(Image.open(io.BytesIO(jpgs[k])), live_ref) == 30 + k


def test_key_arrows_still_work_after_quick_frames(qapp, win, sd):
    open_live(qapp, win, sd)
    win.on_strip_picked(10)
    press(qapp, win, Qt.Key_Down)
    assert win.shown_frame == 11
