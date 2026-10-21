"""Con il filtro della striscia attivo, le frecce ← → passano solo dagli elementi filtrati."""
from __future__ import annotations

from test_ui import open_folder, qapp, sd, sd_template, win  # noqa: F401


def _decide(win, choice):
    win._last_decision = 0
    win.decide(choice)


def test_arrows_follow_strip_filter(qapp, win, sd):
    open_folder(qapp, win, sd)
    assert len(win.items) >= 3
    first = win.idx
    _decide(win, "yes")
    _decide(win, "no")
    third = win.idx
    _decide(win, "yes")
    win._pick_strip_filter("yes", "")
    win.idx = first
    win.show_item()
    win.go_forward()
    assert win.idx == third, "la freccia è finita su un elemento non accettato"
    win.go_back()
    assert win.idx == first
    choices = {k: d["choice"] for k, d in win.session.decisions.items()}
    win.go_forward()
    win.go_back()
    assert {k: d["choice"] for k, d in win.session.decisions.items()} == choices
    win._pick_strip_filter("all", "")


def test_choice_inside_filter_goes_to_next_in_filter(qapp, win, sd):
    open_folder(qapp, win, sd)
    first = win.idx
    _decide(win, "yes")
    _decide(win, "no")
    third = win.idx
    _decide(win, "yes")
    win._pick_strip_filter("yes", "")
    win.idx = first
    win.show_item()
    _decide(win, "yes")   # confermata: si va alla prossima ✓, non alla prossima da decidere
    assert win.idx == third
    win.idx = first
    win.show_item()
    _decide(win, "no")    # cambiata: anche così si resta tra le ✓
    assert win.idx == third
    win._pick_strip_filter("all", "")


def test_thumb_queue_center_first_cancel_and_retry(monkeypatch):
    import time
    from concurrent.futures import Future
    from thumbqueue import ThumbQueue
    q = ThumbQueue()
    asked = []

    def submit(k):
        asked.append(k)
        return Future()   # mai partita: si può annullare
    q.sync(["c", "b", "d"], submit)
    assert asked == ["c", "b", "d"]
    old = q.futs["d"]
    q.sync(["x", "c"], submit)          # andato altrove: "b" e "d" non servono più
    assert old.cancelled() and set(q.futs) == {"c", "x"}
    q.arrived("x", ok=False)
    assert not q.can_try("x")           # non subito
    t = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: t + ThumbQueue.RETRY_S + 1)
    assert q.can_try("x")
    for _ in range(ThumbQueue.TRIES - 1):
        q.arrived("x", ok=False)
    assert q.gave_up("x") and not q.can_try("x")
    q.clear()
    assert not q.futs and q.can_try("x")
    q.pool.shutdown()


def test_thumb_disk_cache_reused_and_pruned(qapp, tmp_path, monkeypatch):
    import thumbcache
    from PySide6.QtGui import QImage
    from scanner import Item
    monkeypatch.setenv("PHOTOSWIPE_THUMB_CACHE", str(tmp_path / "cache"))
    src = tmp_path / "a.png"
    img = QImage(400, 300, QImage.Format_RGB32)
    img.fill(0xff3366)
    img.save(str(src))
    item = Item(kind="photo", id="a.png", image=src)
    assert not thumbcache.cached_thumb(item).isNull()
    assert len(list((tmp_path / "cache").glob("*/*.jpg"))) == 1
    monkeypatch.setattr(thumbcache, "make_thumb", lambda it: QImage())   # ora si legge dalla cache
    assert not thumbcache.cached_thumb(item).isNull()
    thumbcache.prune(max_files=0)
    assert not list((tmp_path / "cache").glob("*/*.jpg"))


def test_strip_set_thumb_and_wanted(qapp):
    from PySide6.QtGui import QImage
    from widgets import ThumbStrip
    s = ThumbStrip()
    s.set_entries([(0, None, None, False, "a"), (1, None, "yes", False, "b")], 0)
    got = []
    s.wanted.connect(got.append)
    s._shown = [0, 1]
    s.ask_shown()
    assert got == [[0, 1]]
    img = QImage(10, 10, QImage.Format_RGB32)
    s.set_thumb(1, img)
    assert s.entries[1][1] is img and s.entries[1][2] == "yes"


def test_strip_long_current_outside_filter_and_return_on_thumb_click(qapp, win, sd):
    open_folder(qapp, win, sd)
    first = win.idx
    _decide(win, "yes")
    win._pick_strip_filter("yes", "")   # quella attuale è da decidere: fuori dal filtro
    assert win.thumbs_strip.outside
    here = win.idx
    win.jump_to(first)                  # clic su una miniatura prima: come ←
    assert win.btn_locate.isVisible()   # "Prossima da decidere" per tornare
    assert not win.thumbs_strip.outside
    win._pick_strip_filter("all", "")
    assert len(win.thumbs_strip.entries) == len(win.items)   # nessun taglio a 12 per lato
