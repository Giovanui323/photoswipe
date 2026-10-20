"""Accessibilità: nomi letti da VoiceOver e anello di focus per i controlli disegnati a mano."""
from __future__ import annotations

import re

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from theme import COLORS


def _icon_only(text: str) -> bool:
    """Testo senza lettere (⌂ ‹ › ⓘ ⚙ ? …): VoiceOver leggerebbe il nome del simbolo."""
    return not any(ch.isalpha() for ch in text)


def tooltip_name(tip: str) -> str:
    """Prima riga del tooltip, senza HTML e senza il tasto tra parentesi finale."""
    line = re.sub(r"<[^>]+>", "", tip).strip().split("\n")[0].strip()
    return re.sub(r"\s*\([^)]*\)\.?$", "", line).rstrip(" .:")


def name_icon_buttons(root: QWidget) -> None:
    """Ai pulsanti con sola icona dà come nome accessibile il loro tooltip.
    Non tocca i nomi messi a mano (setAccessibleName prima di questa chiamata)."""
    for b in root.findChildren(QAbstractButton):
        if b.toolTip() and _icon_only(b.text()) and (not b.accessibleName() or b.property("a11y_auto")):
            b.setAccessibleName(tooltip_name(b.toolTip()))
            b.setProperty("a11y_auto", True)


def setup(window: QWidget) -> None:
    """Nomi per VoiceOver e niente anello di focus all'avvio: compare solo premendo Tab
    (senza, Qt darebbe il focus al primo controllo raggiungibile con Tab)."""
    name_icon_buttons(window)
    window.setFocus()


def paint_focus(p: QPainter, w: QWidget, radius: float | None = None) -> None:
    """Anello blu di focus (Tab) sui widget che si disegnano da soli."""
    if not w.hasFocus():
        return
    r = QRectF(w.rect()).adjusted(1, 1, -1, -1)
    rad = r.height() / 2 if radius is None else radius
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(COLORS["focus"]), 2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(r, rad, rad)
    p.restore()


# tasti che un cursore col focus tiene per sé (senza, vincerebbero le scorciatoie della finestra:
# ← → cambierebbero foto)
SLIDER_KEYS = (Qt.Key_Left, Qt.Key_Right, Qt.Key_Backspace, Qt.Key_Delete)


def slider_key_step(e, lo: float, hi: float, value: float, default: float) -> float | None:
    """Nuovo valore per ← / → (⇧ = passo grande, ⌥ = passo fine) e ⌫ (valore predefinito)."""
    k = e.key()
    if k in (Qt.Key_Backspace, Qt.Key_Delete):
        return default
    if k not in (Qt.Key_Left, Qt.Key_Right):
        return None
    step = (hi - lo) * (0.1 if e.modifiers() & Qt.ShiftModifier else
                        0.005 if e.modifiers() & Qt.AltModifier else 0.02)
    return max(lo, min(hi, value + (step if k == Qt.Key_Right else -step)))
