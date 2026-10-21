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


def test_album_opens_with_all_approved_turns_pages_and_click_goes_back(qapp, win, sd):
    """"Apri l'album": tutte le approvate (non solo le ultime 5) dalla prima, impaginate; si
    sfoglia con → ←; clic su una foto = l'album si richiude e l'app torna a quella foto."""
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest
    open_folder(qapp, win, sd)
    photos = [it.main.name for it in win.items if it.kind == "photo"]
    for n in photos:
        go(qapp, win, n)
        press(qapp, win, Qt.Key_Y)
    go(qapp, win, PHOTO1)   # il fotolibro piccolo ne vede 1, l'album tutte
    win.photobook.open_btn.click()
    dlg = win.photobook.album
    assert dlg is not None and dlg.isVisible()
    assert [p.main.name for p in dlg.photos] == photos
    assert wait(qapp, lambda: dlg.pages and not dlg.view._flip), "copertina che si apre"
    assert sum(map(len, dlg.pages)) == len(photos)
    last = dlg.spreads() - 1   # pagine per giorno: con le foto di prova possono essere poche
    QTest.keyClick(dlg, Qt.Key_End)
    assert dlg.view.spread == last
    assert wait(qapp, lambda: not dlg.view._flip and dlg.view._photos(last)), "pagina girata"
    rect, i = dlg.view._photos(last)[-1]
    assert wait(qapp, lambda: i in dlg.images), "foto caricate"
    QTest.mouseClick(dlg.view, Qt.LeftButton, pos=rect.center().toPoint())
    assert wait(qapp, lambda: win.current().main.name == dlg.photos[i].main.name), "non torna alla foto"
    assert wait(qapp, lambda: not dlg.isVisible()), "l'album non si chiude"
    win.photobook.open_btn.click()   # Esc: il libro si richiude e la finestra sparisce
    dlg = win.photobook.album
    assert wait(qapp, lambda: dlg.pages and not dlg.view._flip)
    for n in range(4):
        dlg.view._anim.setCurrentTime(dlg.view._anim.duration()) if dlg.view._flip else None
        QTest.keyClick(dlg, Qt.Key_Right)
        pump(qapp, 0.5)
        dlg.grab().save(f"{__import__('os').environ.get('ALBUM_SHOTS', '/nonexistent')}/spread{n}.png")
    QTest.keyClick(dlg, Qt.Key_Escape)
    assert wait(qapp, lambda: not dlg.isVisible()), "Esc non chiude l'album"


def test_album_pages_follow_days_and_weeks():
    """Una pagina per giorno (fino a 5, le altre nella pagina dopo); giorni con poche foto della
    stessa settimana insieme fino a 4; le caselle hanno le proporzioni delle foto (niente schiacciate)."""
    from datetime import datetime
    from pathlib import Path

    from PySide6.QtCore import QRectF

    import album
    from photobook import Page
    from scanner import Item

    def pg(day, n):
        it = Item("photo", f"{day}_{n}.jpg", image=Path(f"{day}_{n}.jpg"), taken=datetime(2026, 7, day, 10, n))
        return Page(it.id, it.id, it.main, it, None)
    # 3 lug: 1 · 4 lug: 5 · 5 lug: 7 · 8 e 9 lug (stessa settimana): 2 + 1 · 13 lug (settimana dopo): 1
    photos = [pg(3, 0)] + [pg(4, n) for n in range(5)] + [pg(5, n) for n in range(7)] \
        + [pg(8, 0), pg(8, 1), pg(9, 0), pg(13, 0)]
    assert album.plan(photos) == [[0], [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12], [13, 14, 15], [16]]
    eleven = [pg(30, n) for n in range(11)]   # 11 foto dello stesso giorno: 5 + 5 + 1
    assert [len(p) for p in album.plan(eleven)] == [5, 5, 1]
    page = QRectF(0, 0, 300, 400)
    for aspects in ([0.75], [1.5, 0.75], [0.75, 0.75, 1.33, 1.33, 0.75]):
        rects = album.slots(page, aspects)
        assert len(rects) == len(aspects)
        for r, a in zip(rects, aspects):
            assert abs(r.width() / r.height() - a) < 0.01 and page.adjusted(-0.5, -0.5, 0.5, 0.5).contains(r)


def test_album_layout_every_mix_of_landscape_portrait_pano_square():
    """Ogni combinazione da 1 a 5 foto (orizzontali, verticali, panorami, quadrate): tutte
    dentro la pagina, con le loro proporzioni, senza sovrapporsi, nell'ordine e nessuna minuscola."""
    from itertools import product

    from PySide6.QtCore import QRectF

    import album
    page = QRectF(0, 0, 300, 400)
    worst = 1.0
    for n in range(1, 6):
        for aspects in product((4 / 3, 3 / 4, 3.0, 1.0), repeat=n):
            rects = album.slots(page, list(aspects))
            assert len(rects) == n
            for r, a in zip(rects, aspects):
                assert abs(r.width() / r.height() - a) < 0.01, (aspects, r)
                assert page.adjusted(-0.5, -0.5, 0.5, 0.5).contains(r), (aspects, r)
            for i in range(n):
                for j in range(i + 1, n):
                    over = rects[i].intersected(rects[j])
                    assert over.width() < 0.5 or over.height() < 0.5, (aspects, i, j)
            cover = sum(r.width() * r.height() for r in rects) / (page.width() * page.height())
            smallest = min(r.width() * r.height() for r in rects) / (page.width() * page.height())
            assert smallest > 0.02, (aspects, smallest)   # nessuna foto ridotta a francobollo
            worst = min(worst, cover)
    assert worst >= 0.24, worst   # il caso peggiore: un panorama 3:1 da solo, largo quanto la pagina


def test_album_pages_gather_by_place():
    """Il luogo mette insieme: nello stesso giorno le foto dello stesso posto sulla stessa pagina
    (anche se non sono una dopo l'altra), quelle fatte altrove su un'altra; i luoghi con poche foto
    insieme tra loro; giorni della stessa settimana insieme solo se nello stesso posto."""
    from datetime import datetime
    from pathlib import Path

    import album
    from photobook import Page
    from scanner import Item

    def pg(month, day, n):
        it = Item("photo", f"{month}_{day}_{n}.jpg", image=Path(f"{day}_{n}.jpg"),
                  taken=datetime(2026, month, day, 10, n))
        return Page(it.id, it.id, it.main, it, None)
    la, hollywood, sf = (34.05, -118.25), (34.13, -118.32), (37.77, -122.42)
    # 4 a LA e 1 a Hollywood in mezzo: le 4 insieme, la quinta a parte
    day = [pg(7, 20, n) for n in range(5)]
    assert album.plan(day, [la, la, hollywood, la, la]) == [[0, 1, 3, 4], [2]]
    # foto da sole in giorni e posti diversi della stessa settimana: insieme, non una per pagina
    singles = [pg(7, 21, 0), pg(7, 22, 0), pg(7, 23, 0)]
    assert album.plan(singles, [la, sf, hollywood]) == [[0, 1, 2]]
    eleven = [pg(7, 24, n) for n in range(11)] + [pg(7, 25, 0)]
    assert [len(p) for p in album.plan(eleven, [la] * 11 + [sf])] == [5, 5, 2]   # la foto sola del 25 va con l'avanzo
    # 27 lug: 2 a LA, 1 senza GPS (resta con LA), 2 a Hollywood · 28 lug: 1 a Hollywood e 1 a SF
    # (poche, insieme) che si uniscono alle 2 di Hollywood del giorno prima · 30 lug: 4 a LA, 3 a SF
    # · 1 ago (stessa settimana, a SF): con le 3 di SF
    photos = [pg(7, 27, n) for n in range(5)] + [pg(7, 28, n) for n in range(2)] \
        + [pg(7, 30, n) for n in range(7)] + [pg(8, 1, 0)]
    gps = [la, la, None, hollywood, hollywood, hollywood, sf] + [la] * 4 + [sf] * 3 + [sf]
    assert album.plan(photos, gps) == [[0, 1, 2], [3, 4, 5, 6], [7, 8, 9, 10], [11, 12, 13, 14]]
    assert album.plan(photos) == [[0, 1, 2, 3, 4], [5, 6], [7, 8, 9, 10, 11], [12, 13, 14]]   # senza GPS: solo le date
    assert album.caption(photos, [0, 1], "Los Angeles").endswith("2026 · Los Angeles")
    assert album.place_name(gps, [2, 3]) and album.place_name([None], [0]) == ""
