"""Accessibilità: contrasto dei colori del tema, nomi per VoiceOver, cursori usabili con la tastiera."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

import a11y  # noqa: E402
import theme  # noqa: E402
from test_ui import PHOTO1, go, open_folder, pump, qapp, sd, sd_template, win  # noqa: E402,F401
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402


def contrast(a: str, b: str) -> float:
    def lum(h: str) -> float:
        c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


C = theme.COLORS


@pytest.mark.parametrize("fg, bg, minimum", [
    ("text", "bg_window", 4.5), ("text_2", "bg_panel", 4.5), ("text_2", "bg_control", 4.5),
    ("text_detail", "bg_panel", 4.5), ("link", "bg_panel", 4.5), ("text_warn", "bg_window", 4.5),
    ("text_danger", "bg_control", 4.5),
    ("line_control", "bg_window", 3.0), ("line_control", "bg_panel", 3.0), ("line_check", "bg_control", 3.0),
    ("focus", "bg_window", 3.0),
])
def test_theme_contrast_wcag_aa(fg, bg, minimum):
    assert contrast(C[fg], C[bg]) >= minimum


def test_disabled_text_still_readable():
    # i controlli spenti sono esenti da WCAG, ma devono restare leggibili (almeno 3:1)
    assert contrast(C["text_off"], C["bg_control"]) >= 3.0
    assert contrast(C["text_caption_off"], C["bg_window"]) >= 3.0


def test_tooltip_name():
    assert a11y.tooltip_name("Mostra / nascondi il pannello delle informazioni (I).\nAltro") == \
        "Mostra / nascondi il pannello delle informazioni"
    assert a11y.tooltip_name("<b>Annulla</b> questa regolazione") == "Annulla questa regolazione"


def test_slider_moves_with_arrows_and_photo_stays(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.on_side_tab("regola")
    pump(qapp, 0.3)
    sc = win.regola.scrubbers["light"]
    assert sc.focusPolicy() == Qt.TabFocus
    sc.setFocus(Qt.TabFocusReason)
    pump(qapp, 0.05)
    index, before = win.idx, sc.value
    QTest.keyClick(sc, Qt.Key_Right)
    pump(qapp, 0.1)
    assert sc.value > before and win.idx == index   # → regola la luce, non cambia foto
    QTest.keyClick(sc, Qt.Key_Backspace)
    pump(qapp, 0.1)
    assert sc.value == 0.0


def test_icon_buttons_have_spoken_names(qapp, win):
    # ⌂ ‹ › ⓘ ⚙ ?: VoiceOver legge il nome preso dal tooltip, non il nome del simbolo
    for b in (win.btn_info, win.btn_help):
        assert b.accessibleName() and any(ch.isalpha() for ch in b.accessibleName())
    assert win.btn_info.accessibleName() == "Mostra / nascondi il pannello delle informazioni"


def test_overlays_leave_the_photo_free(qapp, win, sd):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    pump(qapp, 0.3)
    # data e ora nella barra in alto, non sulla foto
    assert win.stamp.isVisible() and win.stamp.parent() is not win.stack and "30 lug 2026" in win.stamp.text()
    # zoom: solo col mouse sopra la foto
    assert not win.zoom_pill.isVisible()
    QApplication.sendEvent(win.stack, QEvent(QEvent.Enter))
    assert win.zoom_pill.isVisible()
    QApplication.sendEvent(win.stack, QEvent(QEvent.Leave))
    assert not win.zoom_pill.isVisible()
    # Ritaglia: lo zoom non copre la maniglia, anche col mouse sopra
    win.on_side_tab("ritaglia")
    QApplication.sendEvent(win.stack, QEvent(QEvent.Enter))
    assert not win.zoom_pill.isVisible()


def test_pending_edit_hides_choices_but_keeps_space(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.on_side_tab("ritaglia")
    h = win.image_view.height()
    assert win.decision_bar.graphicsEffect() is None   # aperto senza cambiare nulla: si sceglie ancora
    win.ritaglia._set_aspect("square")
    pump(qapp, 0.2)
    assert win.decision_bar.graphicsEffect() is not None and win.thumbs_strip.graphicsEffect() is not None
    assert win.image_view.height() == h                 # la foto non salta
    win.cancel_edit()
    pump(qapp, 0.2)
    assert win.decision_bar.graphicsEffect() is None and win.thumbs_strip.graphicsEffect() is None


def test_no_focus_ring_at_startup(qapp, win, sd):
    open_folder(qapp, win, sd)
    pump(qapp, 0.2)
    assert win.focusWidget() in (None, win)   # nessun controllo con l'anello blu finché non si preme Tab
