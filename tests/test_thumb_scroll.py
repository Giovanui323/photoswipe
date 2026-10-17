"""Striscia delle miniature in basso: scorre morbida (frecce, rotella, trascinamento con inerzia),
si ferma ai bordi, e un clic seleziona ancora la miniatura."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from test_ui import go, open_folder, pump, qapp, sd, sd_template, win, wait, PHOTO1  # noqa: F401
from app import ThumbStrip


def narrow(strip, monkeypatch, px: int = 320) -> None:
    """Striscia più stretta delle miniature: c'è davvero da scorrere (la finestra di prova è larga)."""
    monkeypatch.setattr(strip, "width", lambda: px)


def settled(qa, strip) -> bool:
    return wait(qa, lambda: not strip._timer.isActive(), 5)


def test_arrow_scrolls_smoothly_and_stops_at_the_end(qapp, win, sd, monkeypatch):
    win.resize(1440, 900)
    open_folder(qapp, win, sd)
    strip = win.thumbs_strip
    narrow(strip, monkeypatch)
    win.scroll_thumbs(-1)                          # freccia avanti (verso destra)
    assert strip.pan == 0.0                        # non salta: si muove nei passi dopo
    assert strip._target != 0.0
    settled(qapp, strip)
    assert abs(strip.pan - strip._target) < 0.5
    for _ in range(40):                            # oltre la fine: si ferma all'ultima
        win.scroll_thumbs(-1)
        settled(qapp, strip)
    assert abs(strip.pan) <= strip._limit() + 0.5
    win.locate_thumb()                             # riporta alla selezionata
    settled(qapp, strip)
    assert abs(strip.pan) < 0.5


def test_wheel_trackpad_moves_with_the_fingers(qapp, win, sd, monkeypatch):
    win.resize(1440, 900)
    open_folder(qapp, win, sd)
    strip = win.thumbs_strip
    narrow(strip, monkeypatch)
    win.locate_thumb(); settled(qapp, strip)
    strip.nudge(-120); settled(qapp, strip)
    before = strip.pan
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent
    e = QWheelEvent(QPointF(100, 30), QPointF(300, 30), QPoint(-40, 0), QPoint(0, 0),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)   # trackpad: pixel
    strip.wheelEvent(e)
    assert strip.pan != before and strip.pan == strip._target   # segue le dita, subito


def test_drag_then_inertia_glides_on_release(qapp, win, sd, monkeypatch):
    win.resize(1440, 900)
    open_folder(qapp, win, sd)
    strip = win.thumbs_strip
    narrow(strip, monkeypatch)
    win.locate_thumb(); settled(qapp, strip)
    y = strip.height() // 2
    QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, QPointF(600, y).toPoint())
    for x in range(600, 480, -12):                 # trascino a sinistra
        QTest.mouseMove(strip, QPointF(x, y).toPoint())
        pump(qapp, 0.02)
    p_before = strip.pan
    QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, QPointF(480, y).toPoint())
    assert strip._vel != 0.0                       # c'è velocità da inerzia
    pump(qapp, 0.3)
    assert strip.pan < p_before - 5                # ha continuato a scorrere dopo il rilascio
    settled(qapp, strip)


def test_click_still_picks_a_thumbnail(qapp, win, sd):
    win.resize(1440, 900)
    open_folder(qapp, win, sd)
    strip = win.thumbs_strip
    target = next(r for r, i in strip._rects if i == 2)
    QTest.mouseClick(strip, Qt.LeftButton, Qt.NoModifier, target.center().toPoint())
    pump(qapp, 0.2)
    assert win.idx == 2
