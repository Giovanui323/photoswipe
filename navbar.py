"""Barra in alto, separata da app.py: casa, annulla e ripristina (come in Word), solo icone a contorno."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton

import a11y
from i18n import tr
from theme import COLORS as C


def pill(*buttons: QPushButton) -> QFrame:
    """Pulsanti raccolti in una capsula, come la barra strumenti di Foto."""
    f = QFrame()
    f.setObjectName("pill")
    h = QHBoxLayout(f)
    h.setContentsMargins(4, 3, 4, 3)
    h.setSpacing(2)
    for b in buttons:
        b.setFocusPolicy(Qt.NoFocus)
        h.addWidget(b)
    return f


class NavButton(QPushButton):
    """Icona a contorno: "home" = casa, "undo" / "redo" = freccia a uncino verso sinistra / destra."""

    def __init__(self, kind: str, name: str, tip: str):
        super().__init__("")
        self.kind = kind
        self.setObjectName("navicon")
        self.setAccessibleName(name)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 34)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(C["text"] if self.isEnabled() else C["text_off"])
        p.setPen(QPen(col, 1.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        cx, cy = self.width() / 2, self.height() / 2
        p.translate(cx, cy)   # disegno su 16 px, ingrandito come le icone di Word
        p.scale(1.3, 1.3)
        p.translate(-cx, -cy)
        path = QPainterPath()
        if self.kind == "home":   # casetta a contorno, con la porta
            path.moveTo(cx - 8, cy - 1.5)
            path.lineTo(cx, cy - 9)
            path.lineTo(cx + 8, cy - 1.5)
            path.moveTo(cx - 6.5, cy - 3)
            path.lineTo(cx - 6.5, cy + 8)
            path.lineTo(cx + 6.5, cy + 8)
            path.lineTo(cx + 6.5, cy - 3)
            path.moveTo(cx - 2.5, cy + 8)
            path.lineTo(cx - 2.5, cy + 2.5)
            path.lineTo(cx + 2.5, cy + 2.5)
            path.lineTo(cx + 2.5, cy + 8)
            p.drawPath(path)
        elif self.kind in ("undo", "redo"):   # uncino di Word: punta in alto, curva sul lato opposto, coda in basso
            s = -1 if self.kind == "undo" else 1   # ripristina = annulla allo specchio
            path.moveTo(cx + s * 8, cy - 4)
            path.lineTo(cx - s * 1, cy - 4)
            path.arcTo(QRectF(cx - 4.5 if s < 0 else cx - 6.5, cy - 4, 11, 11),
                       90, 180 if s > 0 else -180)
            path.lineTo(cx + s * 5, cy + 7)
            path.moveTo(cx + s * 4.5, cy - 7.5)   # punta della freccia
            path.lineTo(cx + s * 8, cy - 4)
            path.lineTo(cx + s * 4.5, cy - 0.5)
            p.drawPath(path)
        elif self.kind == "fav":
            on = self.property("on") == "true" or self.text() == "♥"
            p.setPen(QPen(QColor(C["accent"] if on else col), 1.3))
            p.setBrush(QColor(C["accent"]) if on else Qt.NoBrush)
            path.moveTo(cx, cy + 6.2)
            path.cubicTo(cx - 7.5, cy + 1.5, cx - 7.5, cy - 5.5, cx - 3.8, cy - 5.5)
            path.cubicTo(cx - 1.8, cy - 5.5, cx, cy - 3.5, cx, cy - 1.8)
            path.cubicTo(cx, cy - 3.5, cx + 1.8, cy - 5.5, cx + 3.8, cy - 5.5)
            path.cubicTo(cx + 7.5, cy - 5.5, cx + 7.5, cy + 1.5, cx, cy + 6.2)
            path.closeSubpath()
            p.drawPath(path)
        elif self.kind == "info":
            r = QRectF(cx - 6.5, cy - 6.5, 13, 13)
            p.drawEllipse(r)
            p.drawLine(QPointF(cx, cy - 1.5), QPointF(cx, cy + 3.5))
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(cx, cy - 3.8), 1.1, 1.1)
        elif self.kind == "settings":
            import math
            p.setPen(QPen(col, 1.3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), 2.8, 2.8)
            for a in range(0, 360, 60):
                rad = math.radians(a)
                p.drawLine(QPointF(cx + 4.0 * math.cos(rad), cy + 4.0 * math.sin(rad)),
                           QPointF(cx + 6.6 * math.cos(rad), cy + 6.6 * math.sin(rad)))
            p.drawEllipse(QPointF(cx, cy), 6.5, 6.5)
        elif self.kind == "help":
            r = QRectF(cx - 6.5, cy - 6.5, 13, 13)
            p.drawEllipse(r)
            f = p.font()
            f.setPixelSize(10)
            f.setBold(True)
            p.setFont(f)
            p.drawText(r.adjusted(0, -1, 0, 1), Qt.AlignCenter, "?")
        p.resetTransform()
        a11y.paint_focus(p, self)


def bar(*buttons: NavButton) -> QFrame:
    """Icone libere, senza capsula intorno (come la barra di Word)."""
    f = pill(*buttons)
    f.setObjectName("navbar")
    return f


def make_buttons() -> dict[str, NavButton]:
    """I tre pulsanti della barra in alto, con nome e suggerimento (i collegamenti li fa app.py)."""
    return {
        "home": NavButton("home", tr("Cartelle"),
                          tr("Cartelle: chiude questa cartella e torna alla scelta (la sessione resta salvata).")),
        "undo": NavButton("undo", tr("Annulla"),
                          tr("Annulla l'ultima scelta e torna a quella foto (Z o ⌘Z).\nSe era un Sì, toglie anche i file copiati in export.")),
        "redo": NavButton("redo", tr("Ripristina"), tr("Ripristina la scelta appena annullata (⇧Z o ⇧⌘Z).")),
    }
