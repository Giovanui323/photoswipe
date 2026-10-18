"""Pannelli Regola e Ritaglia (come in Foto di macOS) e il selettore Info · Regola · Ritaglia."""
from __future__ import annotations

import copy

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

import edits as E
from i18n import tr

EDIT_STYLE = """
QFrame#segbar { background: #2c2c2e; border: 1px solid #48484a; border-radius: 16px; }
QFrame#side QFrame#segbar QPushButton { background: transparent; border: none; border-radius: 12px;
    padding: 5px 0; font-size: 13px; font-weight: 600; color: #f2f2f7; text-align: center; }
QFrame#side QFrame#segbar QPushButton:hover { background: #3a3a3c; }
QFrame#side QFrame#segbar QPushButton:checked { background: #545456; }
QFrame#side QFrame#segbar QPushButton:disabled { color: #6e6e73; }
QLabel#editnote { color: #98989f; font-size: 11px; }
QFrame#side QPushButton#chev { background: transparent; border: none; padding: 0; font-size: 12px; color: #d1d1d6;
    min-width: 14px; max-width: 14px; text-align: center; }
QFrame#side QPushButton#sectitle { background: transparent; border: none; padding: 2px 0; font-size: 15px;
    color: #f2f2f7; text-align: left; }
QFrame#side QPushButton#sectitle:hover { color: #ffffff; }
QFrame#side QPushButton#secundo { background: transparent; border: none; padding: 0; font-size: 15px; color: #8e8e93;
    min-width: 20px; max-width: 20px; text-align: center; }
QFrame#side QPushButton#secundo:hover { color: #f2f2f7; }
QFrame#side QPushButton#auto { background: transparent; border: 1px solid #8e8e93; border-radius: 8px;
    padding: 0 5px; font-size: 9px; font-weight: 700; color: #d1d1d6; min-height: 15px; max-height: 15px;
    text-align: center; }
QFrame#side QPushButton#auto:hover { border-color: #f2f2f7; color: #ffffff; }
QFrame#side QPushButton#auto[on="true"] { background: #8e8e93; border-color: #8e8e93; color: #1c1c1e; }
QFrame#side QPushButton#secundo:disabled { color: #545456; }
QFrame#side QPushButton#opts { background: transparent; border: none; padding: 2px 0 2px 18px; font-size: 13px;
    color: #d1d1d6; text-align: left; }
QFrame#side QPushButton#reset, QFrame#side QPushButton#cropbtn { background: #3a3a3c; border: none; border-radius: 15px;
    padding: 7px 14px; font-size: 13px; text-align: center; }
QFrame#side QPushButton#reset:hover, QFrame#side QPushButton#cropbtn:hover { background: #48484a; }
QFrame#side QPushButton#reset:disabled, QFrame#side QPushButton#cropbtn:disabled { color: #6e6e73; background: #2c2c2e; }
QFrame#side QPushButton#cropok { background: #ffd60a; color: #1c1c1e; border: none; border-radius: 15px;
    padding: 7px 14px; font-size: 14px; font-weight: 700; text-align: center; }
QFrame#side QPushButton#cropok:hover { background: #ffe14d; }
QLabel#panelhead { color: #98989f; font-size: 13px; font-weight: 700; padding-bottom: 7px;
    border-bottom: 2px solid #48484a; }
QFrame#side QPushButton#cropitem { background: transparent; border: none; padding: 4px 0; font-size: 15px;
    color: #d1d1d6; text-align: left; }
QFrame#side QPushButton#cropitem:hover { color: #ffffff; }
QFrame#side QPushButton#cropitem[on="true"] { color: #ffffff; }
QLabel#cropitemlabel { font-size: 15px; color: #d1d1d6; padding: 4px 0; }
QFrame#side QPushButton#cropbig { background: #48484a; border: none; border-radius: 20px; min-height: 40px;
    max-height: 40px; font-size: 15px; color: #f2f2f7; text-align: center; padding: 0 12px; }
QFrame#side QPushButton#cropbig:hover { background: #545456; }
QFrame#side QPushButton#cropbig:disabled { background: #2f2f31; color: #6e6e73; }
QFrame#side QPushButton#aspect:checked { color: #ffffff; }
QFrame#side QPushButton#aspect { background: transparent; border: none; border-radius: 0; padding: 5px 0;
    font-size: 15px; color: #aeaeb2; text-align: left; }
QFrame#side QPushButton#aspect:hover { color: #ffffff; }
QFrame#side QPushButton#aspect:checked { color: #ffffff; }
QFrame#side QPushButton#flip { background: transparent; border: none; padding: 4px 0; font-size: 15px;
    color: #d1d1d6; text-align: left; }
QFrame#side QPushButton#flip:hover { color: #ffffff; }
QFrame#side QPushButton#orient { background: #2c2c2e; border: 1px solid #48484a; border-radius: 6px; padding: 0;
    font-size: 15px; min-width: 34px; max-width: 34px; min-height: 24px; max-height: 24px; text-align: center; }
QFrame#side QPushButton#orient:checked { background: #545456; border-color: #8e8e93; }
QFrame#side QPushButton#swatch { border-radius: 11px; min-width: 22px; max-width: 22px; min-height: 22px;
    max-height: 22px; padding: 0; border: 2px solid transparent; }
QFrame#side QPushButton#swatch:checked { border: 2px solid #ffffff; }
QFrame#side QPushButton#small2 { background: #3a3a3c; border: none; border-radius: 10px; padding: 3px 10px;
    font-size: 12px; text-align: center; }
QFrame#side QPushButton#small2:hover { background: #48484a; }
QFrame#side QPushButton#discard { background: #3a3a3c; border: 1px solid #ff453a; color: #ff6961; border-radius: 15px;
    padding: 7px 14px; font-size: 13px; font-weight: 600; text-align: center; }
QFrame#side QPushButton#discard:hover { background: rgba(255, 69, 58, 50); }
QFrame#side QPushButton#discard:disabled { color: #6e6e73; border-color: #3a3a3c; background: #2c2c2e; }
QFrame#side QSpinBox { background: #2c2c2e; border: 1px solid #545456; border-radius: 6px; padding: 2px 4px; }
"""


# ----------------------------------------------------------------------------- piccoli widget
class Segmented(QFrame):
    """Info · Regola · Ritaglia, come la barra Regola · Stili · Ritaglia di Foto."""
    changed = Signal(str)

    def __init__(self, items: list[tuple[str, str]]):
        super().__init__()
        self.setObjectName("segbar")
        h = QHBoxLayout(self)
        h.setContentsMargins(3, 3, 3, 3)
        h.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in items:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            h.addWidget(b, 1)

    def set_current(self, key: str) -> None:
        self.buttons[key].setChecked(True)

    def current(self) -> str:
        for k, b in self.buttons.items():
            if b.isChecked():
                return k
        return ""


class ValueBar(QWidget):
    """Cursore a barra di Foto: nome a sinistra, valore a destra, si trascina in orizzontale.
    Doppio clic = valore predefinito."""
    changed = Signal(float)

    def __init__(self, label: str, lo: float = -1.0, hi: float = 1.0, default: float = 0.0,
                 fmt=None, origin: float | None = None):
        super().__init__()
        self.label, self.lo, self.hi, self.default = label, lo, hi, default
        self.value = default
        self.origin = default if origin is None else origin   # da dove parte la parte chiara
        self.fmt = fmt or (lambda v: f"{v:+.2f}".replace("+0.00", "0.00").replace(".", ","))
        self.setFixedHeight(26)
        self.setCursor(Qt.SizeHorCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._press: tuple[float, float] | None = None

    def set_value(self, v: float) -> None:
        self.value = max(self.lo, min(self.hi, float(v)))
        self.update()

    def _frac(self, v: float) -> float:
        return (v - self.lo) / (self.hi - self.lo)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = (e.position().x(), self.value)

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        x0, v0 = self._press
        k = 0.25 if e.modifiers() & Qt.AltModifier else 1.0   # ⌥ = movimento fine
        v = v0 + (e.position().x() - x0) / max(1, self.width()) * (self.hi - self.lo) * k
        if abs(v - self.default) < (self.hi - self.lo) * 0.01:
            v = self.default   # si "aggancia" allo zero
        v = max(self.lo, min(self.hi, v))
        if abs(v - self.value) > 1e-9:
            self.value = v
            self.update()
            self.changed.emit(v)

    def mouseReleaseEvent(self, e):
        self._press = None

    def mouseDoubleClickEvent(self, e):
        self.value = self.default
        self.update()
        self.changed.emit(self.value)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.fillPath(path, QColor("#323234" if self.isEnabled() else "#2a2a2c"))
        p.setClipPath(path)
        x0 = r.left() + r.width() * self._frac(self.origin)
        x1 = r.left() + r.width() * self._frac(self.value)
        p.fillRect(QRectF(min(x0, x1), r.top(), abs(x1 - x0), r.height()), QColor("#4a4a4d"))
        p.setPen(QPen(QColor("#5a5a5e"), 2))            # la tacca dello zero resta ferma, come in Foto
        p.drawLine(QPointF(x0, r.top()), QPointF(x0, r.bottom()))
        if abs(x1 - x0) > 1:
            p.setPen(QPen(QColor("#a1a1a6"), 2))
            p.drawLine(QPointF(x1, r.top()), QPointF(x1, r.bottom()))
        p.setClipping(False)
        p.setPen(QColor("#f2f2f7" if self.isEnabled() else "#6e6e73"))
        f = p.font()
        f.setPixelSize(13)
        p.setFont(f)
        p.drawText(r.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, self.label)
        p.drawText(r.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignRight, self.fmt(self.value))


class ThumbScrubber(QWidget):
    """Le 5 miniature di Luce / Colore / Bianco e nero: si trascina la linea per regolare."""
    changed = Signal(float)

    def __init__(self, lo: float = -1.0, hi: float = 1.0):
        super().__init__()
        self.lo, self.hi = lo, hi
        self.value = 0.0
        self.thumbs: list[QImage] = []
        self.setFixedHeight(62)
        self.setCursor(Qt.SizeHorCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._drag = False

    def set_value(self, v: float) -> None:
        self.value = v
        self.update()

    def set_thumbs(self, thumbs: list[QImage]) -> None:
        self.thumbs = thumbs
        self.update()

    def _from_x(self, x: float) -> float:
        t = max(0.0, min(1.0, x / max(1, self.width())))
        v = self.lo + t * (self.hi - self.lo)
        return 0.0 if abs(v) < (self.hi - self.lo) * 0.015 else v

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = True
            self.value = self._from_x(e.position().x())
            self.update()
            self.changed.emit(self.value)

    def mouseMoveEvent(self, e):
        if self._drag:
            v = self._from_x(e.position().x())
            if v != self.value:
                self.value = v
                self.update()
                self.changed.emit(v)

    def mouseReleaseEvent(self, e):
        self._drag = False

    def mouseDoubleClickEvent(self, e):
        self.value = 0.0
        self.update()
        self.changed.emit(0.0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.setClipPath(path)
        p.fillRect(r, QColor("#2c2c2e"))
        n = len(self.thumbs)
        if n:
            w = r.width() / n
            for i, im in enumerate(self.thumbs):
                cell = QRectF(r.left() + i * w, r.top(), w + 0.5, r.height())
                if im.isNull():
                    continue
                src = QRectF(im.rect())
                k = max(cell.width() / src.width(), cell.height() / src.height())
                sw, sh = cell.width() / k, cell.height() / k
                src = QRectF((src.width() - sw) / 2, (src.height() - sh) / 2, sw, sh)
                p.drawImage(cell, im, src)
        p.setClipping(False)
        x = r.left() + r.width() * (self.value - self.lo) / (self.hi - self.lo)
        p.setPen(QPen(QColor(0, 0, 0, 120), 4))
        p.drawLine(QPointF(x, r.top() + 1), QPointF(x, r.bottom() - 1))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawLine(QPointF(x, r.top() + 1), QPointF(x, r.bottom() - 1))


class WandButton(QPushButton):
    """La bacchetta magica di Foto: migliora automaticamente (gialla quando è applicata)."""

    def __init__(self):
        super().__init__("")
        self.active = False

    def set_active(self, on: bool) -> None:
        self.active = on
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor("#ffd60a" if self.active else ("#f2f2f7" if self.isEnabled() else "#6e6e73"))
        cx, cy = self.width() / 2, self.height() / 2
        p.setPen(QPen(col, 1.8, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx - 6, cy + 7), QPointF(cx + 3, cy - 2))          # la bacchetta
        p.setPen(QPen(col, 1.2, Qt.SolidLine, Qt.RoundCap))
        for (x, y, r) in ((cx + 6, cy - 6, 2.6), (cx - 1, cy - 7, 1.6), (cx + 7, cy + 1, 1.6)):   # stelline
            p.drawLine(QPointF(x - r, y), QPointF(x + r, y))
            p.drawLine(QPointF(x, y - r), QPointF(x, y + r))


class CompareButton(QPushButton):
    """□|□ di Foto: mostra l'originale per confrontare (premuto = originale)."""

    def __init__(self):
        super().__init__("")
        self.setCheckable(True)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor("#f2f2f7" if self.isEnabled() else "#6e6e73")
        cx, cy = self.width() / 2, self.height() / 2
        p.setPen(QPen(col, 1.4))
        left, right = QRectF(cx - 10, cy - 5, 8, 10), QRectF(cx + 2, cy - 5, 8, 10)
        p.setBrush(col if not self.isChecked() else Qt.NoBrush)
        p.drawRoundedRect(left, 1.5, 1.5)
        p.setBrush(col if self.isChecked() else Qt.NoBrush)
        p.drawRoundedRect(right, 1.5, 1.5)
        p.drawLine(QPointF(cx, cy - 8), QPointF(cx, cy + 8))


class VolumeButton(QPushButton):
    """Altoparlante di Foto: con le onde = audio acceso, barrato = muto."""

    def __init__(self):
        super().__init__("")
        self.setCheckable(True)   # premuto = muto

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor("#f2f2f7" if self.isEnabled() else "#6e6e73")
        cx, cy = self.width() / 2 - 4, self.height() / 2
        path = QPainterPath(QPointF(cx - 7, cy - 3))
        path.lineTo(QPointF(cx - 3, cy - 3))
        path.lineTo(QPointF(cx + 2, cy - 8))
        path.lineTo(QPointF(cx + 2, cy + 8))
        path.lineTo(QPointF(cx - 3, cy + 3))
        path.lineTo(QPointF(cx - 7, cy + 3))
        path.closeSubpath()
        p.fillPath(path, col)
        p.setPen(QPen(col, 1.6, Qt.SolidLine, Qt.RoundCap))
        if self.isChecked():
            p.drawLine(QPointF(cx + 6, cy - 4), QPointF(cx + 13, cy + 4))
            p.drawLine(QPointF(cx + 13, cy - 4), QPointF(cx + 6, cy + 4))
        else:
            for r in (5.0, 9.0):
                p.drawArc(QRectF(cx + 2 - r, cy - r, 2 * r, 2 * r), -45 * 16, 90 * 16)


class CircleToggle(QPushButton):
    """Il cerchio blu di Foto: pieno con ✓ = regolazione attiva; clic = accendi / spegni."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(22, 22)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none; padding: 0;")
        self.active = False

    def set_active(self, on: bool) -> None:
        self.active = on
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(3, 3, 16, 16)
        blue = QColor("#0a84ff" if self.isEnabled() else "#3a3a3c")
        if self.active:
            p.setBrush(blue)
            p.setPen(Qt.NoPen)
            p.drawEllipse(r)
            p.setPen(QPen(QColor("#ffffff"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath(QPointF(7, 11.2))
            path.lineTo(QPointF(9.8, 14))
            path.lineTo(QPointF(15, 8))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        else:
            p.setPen(QPen(blue, 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r)


class CurvePreview(QWidget):
    """Disegno della curva (Curve), sopra i cursori dei 5 punti."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(120)
        self.lut = None

    def set_edit(self, e: dict) -> None:
        self.lut = E._curve_lut(e)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.fillRect(r, QColor("#1f1f21"))
        p.setPen(QPen(QColor("#3a3a3c"), 1))
        for i in range(1, 4):
            p.drawLine(QPointF(r.left() + r.width() * i / 4, r.top()), QPointF(r.left() + r.width() * i / 4, r.bottom()))
            p.drawLine(QPointF(r.left(), r.top() + r.height() * i / 4), QPointF(r.right(), r.top() + r.height() * i / 4))
        p.setPen(QPen(QColor("#545456"), 1, Qt.DashLine))
        p.drawLine(r.bottomLeft(), r.topRight())
        if self.lut is None:
            return
        path = QPainterPath()
        n = len(self.lut)
        for i in range(0, n, 8):
            pt = QPointF(r.left() + r.width() * i / (n - 1), r.bottom() - r.height() * float(self.lut[i]))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        path.lineTo(QPointF(r.right(), r.bottom() - r.height() * float(self.lut[-1])))
        p.setPen(QPen(QColor("#f2f2f7"), 2))
        p.drawPath(path)


def _deg(v: float) -> str:
    return f"{round(v)}°" if abs(v) >= 0.5 else "0°"


# ----------------------------------------------------------------------------- Regola
class SectionIcon(QWidget):
    """Le icone delle regolazioni disegnate come quelle di Foto (linee sottili, grigio chiaro)."""

    def __init__(self, key: str):
        super().__init__()
        self.key = key
        self.setFixedSize(22, 22)

    def paintEvent(self, ev):
        import math as _m
        from PySide6.QtGui import QConicalGradient, QLinearGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor("#d1d1d6" if self.isEnabled() else "#6e6e73")
        pen = QPen(c, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        k = self.key
        box = QRectF(3.5, 3.5, 15, 15)
        if k == "light":            # sole
            p.drawEllipse(QPointF(11, 11), 3.6, 3.6)
            for i in range(8):
                a = i * _m.pi / 4
                p.drawLine(QPointF(11 + 6 * _m.cos(a), 11 + 6 * _m.sin(a)),
                           QPointF(11 + 8.3 * _m.cos(a), 11 + 8.3 * _m.sin(a)))
        elif k == "color":          # anello con tutti i colori
            g = QConicalGradient(QPointF(11, 11), 90)
            for i, col in enumerate(("#ff453a", "#ff9f0a", "#ffd60a", "#32d74b", "#64d2ff", "#0a84ff",
                                     "#bf5af2", "#ff453a")):
                g.setColorAt(i / 7, QColor(col))
            p.setPen(QPen(g, 2.2))
            p.drawEllipse(QPointF(11, 11), 7.2, 7.2)
        elif k == "bw":             # cerchio metà pieno
            p.drawEllipse(QPointF(11, 11), 7.5, 7.5)
            path = QPainterPath()
            path.moveTo(11, 3.5)
            path.arcTo(QRectF(3.5, 3.5, 15, 15), 90, 180)
            path.closeSubpath()
            p.fillPath(path, c)
        elif k == "redeye":         # occhio barrato
            path = QPainterPath(QPointF(3, 11))
            path.quadTo(QPointF(11, 3), QPointF(19, 11))
            path.quadTo(QPointF(11, 19), QPointF(3, 11))
            p.drawPath(path)
            p.drawEllipse(QPointF(11, 11), 2.6, 2.6)
            p.drawLine(QPointF(4, 4), QPointF(18, 18))
        elif k == "wb":             # quadrato W/B
            p.drawRoundedRect(box, 2.5, 2.5)
            p.drawLine(QPointF(18.5, 3.5), QPointF(3.5, 18.5))
            f = p.font()
            f.setPixelSize(6)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(4.5, 4, 7, 7), Qt.AlignCenter, "W")
            p.drawText(QRectF(11, 11, 7, 7), Qt.AlignCenter, "B")
        elif k == "curves":         # griglia con curva
            p.drawRoundedRect(box, 2, 2)
            p.setPen(QPen(c, 0.7))
            for t in (8.5, 13.5):
                p.drawLine(QPointF(t, 3.5), QPointF(t, 18.5))
                p.drawLine(QPointF(3.5, t), QPointF(18.5, t))
            p.setPen(pen)
            path = QPainterPath(QPointF(4, 18))
            path.cubicTo(QPointF(10, 17), QPointF(12, 5), QPointF(18, 4))
            p.drawPath(path)
        elif k == "levels":         # istogramma
            p.drawRoundedRect(box, 2, 2)
            for x, h in ((6, 3), (8, 6), (10, 9), (12, 7), (14, 10), (16, 5)):
                p.drawLine(QPointF(x, 17), QPointF(x, 17 - h))
        elif k == "definition":     # triangolo con l'angolo
            path = QPainterPath(QPointF(4, 18))
            path.lineTo(QPointF(18, 18))
            path.lineTo(QPointF(4, 4))
            path.closeSubpath()
            p.drawPath(path)
            p.drawArc(QRectF(-1, 13, 10, 10), 0, 45 * 16)
        elif k == "selective":      # puntini colorati
            p.setPen(Qt.NoPen)
            for i, col in enumerate(("#ff453a", "#ffd60a", "#32d74b", "#64d2ff", "#0a84ff", "#bf5af2")):
                a = i * _m.pi / 3 - _m.pi / 2
                p.setBrush(QColor(col))
                p.drawEllipse(QPointF(11 + 6 * _m.cos(a), 11 + 6 * _m.sin(a)), 1.9, 1.9)
            p.setBrush(c)
            p.drawEllipse(QPointF(11, 11), 1.9, 1.9)
        elif k == "noise":          # quadrato a scacchi sfumato
            p.drawRoundedRect(box, 2, 2)
            p.setPen(Qt.NoPen)
            for i in range(5):
                for j in range(5):
                    if (i + j) % 2 == 0:
                        col = QColor(c)
                        col.setAlphaF(0.25 + 0.75 * (i + j) / 8)
                        p.fillRect(QRectF(4 + i * 2.9, 4 + j * 2.9, 2.9, 2.9), col)
        elif k == "sharpen":        # triangolo pieno sfumato
            g = QLinearGradient(QPointF(4, 18), QPointF(18, 4))
            g.setColorAt(0, QColor(c.red(), c.green(), c.blue(), 60))
            g.setColorAt(1, c)
            path = QPainterPath(QPointF(4, 18))
            path.lineTo(QPointF(18, 18))
            path.lineTo(QPointF(18, 4))
            path.closeSubpath()
            p.fillPath(path, g)
        elif k == "deblur":         # cerchio sfocato che torna nitido
            p.drawEllipse(QPointF(11, 11), 4, 4)
            p.setPen(QPen(c, 1.2, Qt.DotLine))
            p.drawEllipse(QPointF(11, 11), 7.5, 7.5)
        elif k == "straighten":     # orizzonte dentro un cerchio
            p.drawEllipse(QPointF(11, 11), 6.5, 6.5)
            p.drawLine(QPointF(2, 11), QPointF(20, 11))
            path = QPainterPath()
            path.moveTo(4.5, 11)
            path.arcTo(QRectF(4.5, 4.5, 13, 13), 180, 180)
            path.closeSubpath()
            p.fillPath(path, c)
        elif k == "vertical":       # trapezio: verticali che convergono
            path = QPainterPath(QPointF(7, 4))
            path.lineTo(QPointF(15, 4))
            path.lineTo(QPointF(19, 18))
            path.lineTo(QPointF(3, 18))
            path.closeSubpath()
            p.drawPath(path)
            half = QPainterPath(QPointF(7, 4))
            half.lineTo(QPointF(11, 4))
            half.lineTo(QPointF(11, 18))
            half.lineTo(QPointF(3, 18))
            half.closeSubpath()
            p.fillPath(half, c)
        elif k == "horizontal":     # trapezio coricato
            path = QPainterPath(QPointF(4, 7))
            path.lineTo(QPointF(18, 3))
            path.lineTo(QPointF(18, 19))
            path.lineTo(QPointF(4, 15))
            path.closeSubpath()
            p.drawPath(path)
            half = QPainterPath(QPointF(4, 7))
            half.lineTo(QPointF(18, 3))
            half.lineTo(QPointF(18, 11))
            half.lineTo(QPointF(4, 11))
            half.closeSubpath()
            p.fillPath(half, c)
        elif k == "flip":           # due triangoli specchiati con la freccia sopra
            left = QPainterPath(QPointF(10, 8))
            left.lineTo(QPointF(10, 19))
            left.lineTo(QPointF(3, 19))
            left.closeSubpath()
            p.fillPath(left, c)
            right = QPainterPath(QPointF(12, 8))
            right.lineTo(QPointF(12, 19))
            right.lineTo(QPointF(19, 19))
            right.closeSubpath()
            p.drawPath(right)
            p.drawLine(QPointF(4, 4), QPointF(18, 4))
            p.drawLine(QPointF(4, 4), QPointF(6, 2.5))
            p.drawLine(QPointF(18, 4), QPointF(16, 2.5))
        elif k == "aspect":         # riquadri delle proporzioni
            p.drawRoundedRect(QRectF(3, 5, 16, 12), 2, 2)
            p.fillRect(QRectF(3.5, 5.5, 9, 11), c)
            p.drawLine(QPointF(15.5, 5), QPointF(15.5, 17))
        elif k == "vignette":       # due cerchi
            p.drawEllipse(QPointF(11, 11), 7.5, 7.5)
            p.drawEllipse(QPointF(11, 11), 4.5, 4.5)


class Section(QWidget):
    """Una regolazione: ⌄ icona Nome  ↶ AUTO ◯, e sotto il suo contenuto."""
    toggled_open = Signal(bool)

    def __init__(self, key: str, icon: str, title: str, auto: bool, expanded: bool):
        super().__init__()
        self.key = key
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.chev = QPushButton()
        self.chev.setObjectName("chev")
        ic = SectionIcon(key)
        self.title = QPushButton(title)
        self.title.setToolTip(title)
        self.title.setObjectName("sectitle")
        self.undo = QPushButton("↩︎")
        self.undo.setObjectName("secundo")
        self.undo.setToolTip(tr('Annulla questa regolazione'))
        self.auto = QPushButton(tr('AUTO'))
        self.auto.setObjectName("auto")
        self.auto.setToolTip(tr('Regolazione automatica'))
        self.auto.setVisible(auto)
        self.has_auto = auto
        self.always = expanded   # Luce, Colore, Bianco e nero: AUTO e cerchio sempre in vista, come in Foto
        self._modified = False
        self._hover = False
        self.circle = CircleToggle()
        self.circle.setToolTip(tr('Accendi / spegni questa regolazione (per confrontare)'))
        for b in (self.chev, self.title, self.undo, self.auto):
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
        head.addWidget(self.chev)
        head.addWidget(ic)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.title.setMinimumWidth(40)
        head.addWidget(self.title, 1)
        head.addWidget(self.undo)
        head.addWidget(self.auto)
        head.addWidget(self.circle)
        v.addLayout(head)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 4)
        self.body_lay.setSpacing(5)
        v.addWidget(self.body)
        self.line = QFrame()
        self.line.setFixedHeight(1)
        self.line.setStyleSheet("background: #3a3a3c;")
        v.addWidget(self.line)
        self.chev.clicked.connect(self.toggle)
        self.title.clicked.connect(self.toggle)
        self.set_open(expanded)

    def toggle(self) -> None:
        self.set_open(not self.body.isVisible())
        self.toggled_open.emit(self.body.isVisible())

    def set_open(self, on: bool) -> None:
        self.body.setVisible(on)
        self.chev.setText("⌄" if on else "›")
        self.line.setVisible(not on or not self.always)   # come Foto: le righe tra le voci chiuse

    def is_open(self) -> bool:
        return self.body.isVisible()

    def set_state(self, modified: bool, on: bool) -> None:
        self._modified = modified
        self.circle.set_active(modified and on)
        self.auto.setProperty("on", "true" if modified and on else "false")
        self.auto.style().unpolish(self.auto)
        self.auto.style().polish(self.auto)
        self._update_controls()

    def _update_controls(self) -> None:
        """Come Foto: ↩ AUTO ◯ si vedono se la regolazione è usata o col mouse sopra."""
        show = self.always or self._modified or self._hover
        self.undo.setVisible(self._modified or (self._hover and self.always))
        self.undo.setEnabled(self._modified)
        self.auto.setVisible(self.has_auto and show)
        self.circle.setVisible(show and (self.has_auto or self._modified))

    def enterEvent(self, e):
        self._hover = True
        self._update_controls()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._update_controls()
        super().leaveEvent(e)


class RegolaPanel(QWidget):
    """Tutte le regolazioni del pannello Regola di Foto."""
    changed = Signal(dict)        # la nuova modifica completa
    auto_requested = Signal(str)  # sezione
    redeye_mode = Signal(bool)    # Occhi rossi aperto: un clic sulla foto corregge l'occhio
    reset_all = Signal()

    def __init__(self):
        super().__init__()
        self.edit: dict = {}
        self.bars: dict[str, ValueBar] = {}
        self.scrubbers: dict[str, ThumbScrubber] = {}
        self.sections: dict[str, Section] = {}
        self.sel_hue = "red"
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QLabel(tr('REGOLA'))
        head.setObjectName("panelhead")
        v.addWidget(head)

        def bar(key, label, lo=-1.0, hi=1.0, fmt=None):
            b = ValueBar(label, lo, hi, E.DEFAULTS[key], fmt)
            b.changed.connect(lambda val, k=key: self._set(k, val))
            self.bars[key] = b
            return b

        def options(sec: Section, widgets) -> None:
            btn = QPushButton(tr('›  Opzioni'))
            btn.setObjectName("opts")
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setCursor(Qt.PointingHandCursor)
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(4)
            for w in widgets:
                bl.addWidget(w)
            box.setVisible(False)

            def flip():
                box.setVisible(not box.isVisible())
                btn.setText(("⌄" if box.isVisible() else "›") + tr('  Opzioni'))
            btn.clicked.connect(flip)
            sec.body_lay.addWidget(btn)
            sec.body_lay.addWidget(box)

        def section(key, icon, title, auto=False, expanded=False):
            s = Section(key, icon, title, auto, expanded)
            s.undo.clicked.connect(lambda _=False, k=key: self.reset_section(k))
            s.auto.clicked.connect(lambda _=False, k=key: self.auto_requested.emit(k))
            s.circle.clicked.connect(lambda _=False, k=key: self.toggle_section(k))
            self.sections[key] = s
            v.addWidget(s)
            return s

        pct = lambda val: f"{round(val * 100)}"   # noqa: E731

        # Luce
        s = section("light", "☀︎", tr('Luce'), auto=True, expanded=True)
        sc = ThumbScrubber()
        sc.changed.connect(lambda val: self._set("light", val))
        self.scrubbers["light"] = sc
        s.body_lay.addWidget(sc)
        options(s, [bar("brilliance", tr('Brillantezza')), bar("exposure", tr('Esposizione')),
                    bar("highlights", tr('Luci')), bar("shadows", tr('Ombre')), bar("brightness", tr('Luminosità')),
                    bar("contrast", tr('Contrasto')), bar("blackpoint", tr('Punto di nero'))])
        # Colore
        s = section("color", "◍", tr('Colore'), auto=True, expanded=True)
        sc = ThumbScrubber()
        sc.changed.connect(lambda val: self._set("color", val))
        self.scrubbers["color"] = sc
        s.body_lay.addWidget(sc)
        options(s, [bar("saturation", tr('Saturazione')), bar("vibrance", tr('Vividezza')), bar("cast", tr('Dominante'))])
        # Bianco e nero
        s = section("bw", "◐", tr('Bianco e nero'), auto=True, expanded=True)
        sc = ThumbScrubber()
        sc.changed.connect(lambda val: self._set("bw", val, bw=True))
        self.scrubbers["bw"] = sc
        s.body_lay.addWidget(sc)
        options(s, [bar("bw_intensity", tr('Intensità')), bar("bw_neutrals", tr('Toni neutri')),
                    bar("bw_tone", tr('Tono')), bar("bw_grain", tr('Grana'), 0, 1, pct)])
        for k in ("bw_intensity", "bw_neutrals", "bw_tone", "bw_grain"):
            self.bars[k].changed.connect(lambda _v: self._ensure_bw())
        # Occhi rossi
        s = section("redeye", "👁", tr('Occhi rossi'))
        note = QLabel(tr('Fai clic su ogni occhio rosso nella foto.\nIl cursore regola la misura del cerchio.'))
        note.setObjectName("editnote")
        note.setWordWrap(True)
        s.body_lay.addWidget(note)
        s.body_lay.addWidget(bar("redeye_size", tr('Dimensione'), 0.005, 0.12, lambda val: f"{round(val * 1000)}"))
        rr = QHBoxLayout()
        self.btn_redeye_undo = QPushButton(tr("Togli l'ultimo"))
        self.btn_redeye_undo.setObjectName("small2")
        self.btn_redeye_undo.clicked.connect(self._redeye_undo)
        rr.addWidget(self.btn_redeye_undo)
        rr.addStretch(1)
        s.body_lay.addLayout(rr)
        s.toggled_open.connect(self.redeye_mode.emit)
        # Bilanciamento del bianco
        s = section("wb", "▨", tr('Bilanc. del bianco'), auto=True)
        s.body_lay.addWidget(bar("wb_temp", tr('Temperatura')))
        s.body_lay.addWidget(bar("wb_tint", tr('Tinta')))
        # Curve
        s = section("curves", "⌇", tr('Curve'))
        self.curve_preview = CurvePreview()
        s.body_lay.addWidget(self.curve_preview)
        for k, lab in (("curve_blacks", tr('Neri')), ("curve_shadows", tr('Ombre')), ("curve_mid", tr('Mezzitoni')),
                       ("curve_high", tr('Luci')), ("curve_whites", tr('Cognome'))):
            s.body_lay.addWidget(bar(k, lab))
        # Livelli
        s = section("levels", "▥", "Livelli", auto=True)
        for k, lab, lo, hi in (("lv_black", tr('Nero (ingresso)'), 0, 0.5), ("lv_gamma", tr('Mezzitoni'), -1, 1),
                               ("lv_white", tr('Bianco (ingresso)'), 0.5, 1), ("lv_out_black", tr('Nero (uscita)'), 0, 0.5),
                               ("lv_out_white", tr('Bianco (uscita)'), 0.5, 1)):
            s.body_lay.addWidget(bar(k, lab, lo, hi, pct if k != "lv_gamma" else None))
        # Definizione
        s = section("definition", "◺", tr('Definizione'), auto=True)
        s.body_lay.addWidget(bar("definition", tr('Intensità'), 0, 1, pct))
        # Colore selettivo
        s = section("selective", "⁘", tr('Colore selettivo'))
        sw = QHBoxLayout()
        sw.setSpacing(8)
        self.swatches = QButtonGroup(self)
        for h in E.SEL_HUES:
            b = QPushButton()
            b.setObjectName("swatch")
            b.setCheckable(True)
            b.setToolTip(E.SEL_NAMES[h])
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet(f"background: {E.SEL_COLORS[h]};")
            b.clicked.connect(lambda _=False, hh=h: self._pick_hue(hh))
            self.swatches.addButton(b)
            if h == "red":
                b.setChecked(True)
            sw.addWidget(b)
        sw.addStretch(1)
        s.body_lay.addLayout(sw)
        self.sel_bars = {p: ValueBar(lab) for p, lab in (("h", tr('Tonalità')), ("s", tr('Saturazione')), ("l", tr('Luminanza')))}
        for p, b in self.sel_bars.items():
            b.changed.connect(lambda val, pp=p: self._set(f"sel_{self.sel_hue}_{pp}", val))
            s.body_lay.addWidget(b)
        # Riduzione disturbo, Nitidezza, Vignettatura
        s = section("noise", "▦", tr('Riduz. disturbo'), auto=True)
        s.body_lay.addWidget(bar("noise", tr('Intensità'), 0, 1, pct))
        s = section("deblur", "◌", tr('Sfocatura'), auto=True)
        note = QLabel(tr("Recupera un po' di nitidezza nelle foto sfocate o leggermente mosse.\nAUTO stima quanto è sfocata; Raggio = quanto era sfocata."))
        note.setObjectName("editnote")
        note.setWordWrap(True)
        s.body_lay.addWidget(note)
        s.body_lay.addWidget(bar("deblur", tr('Intensità'), 0, 1, pct))
        s.body_lay.addWidget(bar("deblur_radius", tr('Raggio'), 0, 1, pct))
        s = section("sharpen", "◢", tr('Nitidezza'), auto=True)
        s.body_lay.addWidget(bar("sharp_amount", tr('Intensità'), 0, 1, pct))
        s.body_lay.addWidget(bar("sharp_edges", tr('Bordi'), 0, 1, pct))
        s.body_lay.addWidget(bar("sharp_falloff", tr('Attenuazione'), 0, 1, pct))
        s = section("vignette", "◎", "Vignettatura")
        s.body_lay.addWidget(bar("vig_amount", tr('Intensità')))
        s.body_lay.addWidget(bar("vig_radius", tr('Raggio'), 0, 1, pct))
        s.body_lay.addWidget(bar("vig_soft", tr('Morbidezza'), 0, 1, pct))

        v.addSpacing(6)
        self.btn_reset = QPushButton(tr('Reimposta regolazioni'))
        self.btn_reset.setObjectName("cropbig")   # come Automatico / Reimposta di Ritaglia
        self.btn_reset.setFocusPolicy(Qt.NoFocus)
        self.btn_reset.setToolTip(tr('Toglie tutte le regolazioni di questa foto (il ritaglio resta).'))
        self.btn_reset.clicked.connect(self.reset_all.emit)
        v.addWidget(self.btn_reset)
        self.refresh()

    # -- modello
    def set_edit(self, e: dict) -> None:
        self.edit = copy.deepcopy(e or {})
        self.refresh()

    def refresh(self) -> None:
        e = self.edit
        for k, b in self.bars.items():
            b.set_value(E.get(e, k))
        for k, sc in self.scrubbers.items():
            sc.set_value(E.get(e, k))
        for p, b in self.sel_bars.items():
            b.set_value(E.get(e, f"sel_{self.sel_hue}_{p}"))
        for k, s in self.sections.items():
            s.set_state(E.section_modified(e, k), k not in e.get("off", []))
        self.curve_preview.set_edit(e)
        self.btn_redeye_undo.setEnabled(bool(e.get("redeye")))
        self.btn_reset.setEnabled(E.has_tone(e) or any(E.section_modified(e, s) for s in E.SECTIONS))

    def _emit(self) -> None:
        self.refresh()
        self.changed.emit(copy.deepcopy(self.edit))

    def _section_of(self, key: str) -> str:
        for s, keys in E.SECTIONS.items():
            if key in keys:
                return s
        return ""

    def _set(self, key: str, val: float, bw: bool = False) -> None:
        self.edit[key] = val
        if bw:
            self.edit["bw_on"] = True
        sec = self._section_of(key)
        off = self.edit.get("off", [])
        if sec in off:   # si regola: la sezione torna accesa
            self.edit["off"] = [x for x in off if x != sec]
        self._emit()

    def _ensure_bw(self) -> None:
        if not self.edit.get("bw_on"):
            self.edit["bw_on"] = True
            self._emit()

    def _pick_hue(self, h: str) -> None:
        self.sel_hue = h
        self.refresh()

    def _redeye_undo(self) -> None:
        pts = list(self.edit.get("redeye") or [])
        if pts:
            pts.pop()
            self.edit["redeye"] = pts
            self._emit()

    def add_redeye(self, x: float, y: float) -> None:
        pts = list(self.edit.get("redeye") or [])
        pts.append([x, y, E.get(self.edit, "redeye_size")])
        self.edit["redeye"] = pts
        self.edit["off"] = [s for s in self.edit.get("off", []) if s != "redeye"]
        self._emit()

    def reset_section(self, sec: str) -> None:
        for k in E.SECTIONS[sec]:
            self.edit.pop(k, None)
        if sec == "bw":
            self.edit.pop("bw_on", None)
        if sec == "redeye":
            self.edit.pop("redeye", None)
        self.edit["off"] = [x for x in self.edit.get("off", []) if x != sec]
        self._emit()

    def toggle_section(self, sec: str) -> None:
        if not E.section_modified(self.edit, sec):
            self.auto_requested.emit(sec)   # cerchio vuoto: come in Foto, applica l'automatico
            return
        off = set(self.edit.get("off", []))
        off ^= {sec}
        self.edit["off"] = sorted(off)
        self._emit()

    def apply_auto(self, sec: str, values: dict) -> None:
        for k in E.SECTIONS[sec]:
            self.edit.pop(k, None)
        self.edit.update(values)
        if sec == "bw":
            self.edit["bw_on"] = True
        self.edit["off"] = [x for x in self.edit.get("off", []) if x != sec]
        self._emit()

    def set_thumbs(self, sec: str, thumbs: list[QImage]) -> None:
        self.scrubbers[sec].set_thumbs(thumbs)

    def redeye_open(self) -> bool:
        return self.sections["redeye"].is_open()


# ----------------------------------------------------------------------------- Ritaglia
class RitagliaPanel(QWidget):
    """Raddrizza, prospettiva, capovolgi e proporzioni. Il ritaglio vale solo con OK."""
    changed = Signal(dict)    # bozza del ritaglio (solo le chiavi della geometria)
    aspect_changed = Signal(dict)
    ok = Signal()
    cancel = Signal()
    auto = Signal()

    def __init__(self):
        super().__init__()
        self.draft: dict = {}
        self._landscape_photo = True   # lo imposta l'app: serve per il primo verticale/orizzontale
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QLabel(tr('RITAGLIA'))
        head.setObjectName("panelhead")
        v.addWidget(head)
        v.addSpacing(4)
        self.bars = {
            "straighten": ValueBar(tr('Raddrizza'), -45, 45, 0, _deg),
            "vertical": ValueBar(tr('Verticale'), -1, 1, 0, lambda x: _deg(x * 30)),
            "horizontal": ValueBar(tr('Orizzontale'), -1, 1, 0, lambda x: _deg(x * 30)),
        }
        for k, b in self.bars.items():
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(SectionIcon(k))
            row.addWidget(b, 1)
            b.changed.connect(lambda val, kk=k: self._set(kk, val))
            v.addLayout(row)
        self.bars["straighten"].setToolTip(tr('Ruota la foto (doppio clic = 0°). ⌥ mentre trascini = più preciso.'))
        self.bars["vertical"].setToolTip(tr('Raddrizza le linee verticali che convergono (palazzi).'))
        self.bars["horizontal"].setToolTip(tr('Corregge la prospettiva da sinistra a destra.'))
        v.addSpacing(10)
        frow = QHBoxLayout()
        frow.setSpacing(8)
        frow.addWidget(SectionIcon("flip"))
        self.btn_flip = QPushButton(tr('Capovolgi'))
        self.btn_flip.setObjectName("cropitem")
        self.btn_flip.setFocusPolicy(Qt.NoFocus)
        self.btn_flip.setCursor(Qt.PointingHandCursor)
        self.btn_flip.setToolTip(tr('Specchia la foto da sinistra a destra.'))
        self.btn_flip.clicked.connect(self._flip)
        frow.addWidget(self.btn_flip, 1)
        v.addLayout(frow)
        arow = QHBoxLayout()
        arow.setSpacing(8)
        arow.addWidget(SectionIcon("aspect"))
        lab = QLabel(tr('Proporzioni'))
        lab.setObjectName("cropitemlabel")
        arow.addWidget(lab, 1)
        v.addLayout(arow)
        self.orient: dict[bool, QPushButton] = {}   # verticale / orizzontale: secondo clic sulla voce
        self.aspect_btns: dict[str, QPushButton] = {}
        ag = QButtonGroup(self)
        for key, name, _r in E.ASPECTS:
            b = QPushButton(name)
            b.setObjectName("aspect")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._set_aspect(k))
            if _r and key != "square":
                b.setToolTip(tr('Clic di nuovo per passare da orizzontale a verticale'))
            ag.addButton(b)
            self.aspect_btns[key] = b
            v.addWidget(b)
        cr = QHBoxLayout()
        cr.setContentsMargins(30, 0, 0, 0)
        self.custom_w, self.custom_h = QSpinBox(), QSpinBox()
        for sb in (self.custom_w, self.custom_h):
            sb.setRange(1, 100)
            sb.setValue(1)
            sb.valueChanged.connect(self._custom_changed)
        cr.addWidget(self.custom_w)
        cr.addWidget(QLabel(":"))
        cr.addWidget(self.custom_h)
        cr.addStretch(1)
        self.custom_row = QWidget()
        self.custom_row.setLayout(cr)
        v.addWidget(self.custom_row)
        v.addStretch(1)
        v.addSpacing(16)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_auto = QPushButton(tr('Automatico'))
        self.btn_auto.setToolTip(tr("Raddrizza l'orizzonte e le linee verticali da solo."))
        self.btn_reset = QPushButton(tr('Reimposta'))
        self.btn_reset.setToolTip(tr('Toglie ritaglio, rotazione e prospettiva.'))
        for b in (self.btn_auto, self.btn_reset):
            b.setObjectName("cropbig")
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b, 1)
        self.btn_auto.clicked.connect(self.auto.emit)
        self.btn_reset.clicked.connect(self._reset)
        v.addLayout(row)
        # OK / Annulla stanno in alto (Fine), come in Foto: questi restano solo per compatibilità
        self.btn_cancel = QPushButton(tr('Annulla'))
        self.btn_ok = QPushButton("OK")
        self.btn_cancel.clicked.connect(self.cancel.emit)
        self.btn_ok.clicked.connect(self.ok.emit)
        for b in (self.btn_cancel, self.btn_ok):
            b.setParent(self)
            b.hide()
        self.refresh()

    def set_draft(self, d: dict) -> None:
        self.draft = {k: copy.deepcopy(v) for k, v in (d or {}).items()
                      if k in E.GEOMETRY_KEYS or k in ("aspect_custom", "aspect_portrait")}
        self.refresh()

    def refresh(self) -> None:
        d = self.draft
        for k, b in self.bars.items():
            b.set_value(E.get(d, k))
        key = d.get("aspect", "free")
        self.aspect_btns.get(key, self.aspect_btns["free"]).setChecked(True)
        self.custom_row.setVisible(key == "custom")
        if key == "custom":
            a, b = d.get("aspect_custom") or [1, 1]
            for sb, val in ((self.custom_w, a), (self.custom_h, b)):
                sb.blockSignals(True)
                sb.setValue(val)
                sb.blockSignals(False)
        portrait = d.get("aspect_portrait")
        self.btn_flip.setProperty("on", "true" if d.get("flip") else "false")
        self.btn_flip.style().unpolish(self.btn_flip)
        self.btn_flip.style().polish(self.btn_flip)
        self.btn_reset.setEnabled(E.has_geometry(d) or key != "free")
        for key2, b in self.aspect_btns.items():
            name = dict((k, n) for k, n, _ in E.ASPECTS)[key2]
            if key2 == key and portrait is not None and ":" in name:   # 16:9 ↔ 9:16, come si vedrà
                a_, b_ = name.split(":")
                long_first = int(a_) >= int(b_)
                if long_first == portrait:
                    name = f"{b_}:{a_}"
            b.setText(("✓    " if b.isChecked() else "       ") + name)

    def _emit(self) -> None:
        self.refresh()
        self.changed.emit(copy.deepcopy(self.draft))

    def _set(self, key: str, val: float) -> None:
        self.draft[key] = val
        self._emit()

    def _flip(self) -> None:
        self.draft["flip"] = not self.draft.get("flip")
        c = self.draft.get("crop")
        if c:   # il riquadro resta sulla stessa parte della foto
            self.draft["crop"] = [1 - c[0] - c[2], c[1], c[2], c[3]]
        self._emit()

    def _set_aspect(self, key: str) -> None:
        ratio = dict((k, r) for k, _n, r in E.ASPECTS).get(key)
        if self.draft.get("aspect", "free") == key and ratio and key != "square":
            # secondo clic sulla stessa voce: verticale ↔ orizzontale
            cur = self.draft.get("aspect_portrait")
            if cur is None:
                cur = not self._landscape_photo
            self.draft["aspect_portrait"] = not cur
            self.refresh()
            self.aspect_changed.emit(copy.deepcopy(self.draft))
            return
        self.draft["aspect"] = key
        if key == "custom" and not self.draft.get("aspect_custom"):
            self.draft["aspect_custom"] = [self.custom_w.value(), self.custom_h.value()]
        self.refresh()
        self.aspect_changed.emit(copy.deepcopy(self.draft))

    def _set_orient(self, portrait: bool) -> None:
        self.draft["aspect_portrait"] = portrait
        self.refresh()
        self.aspect_changed.emit(copy.deepcopy(self.draft))

    def _custom_changed(self) -> None:
        self.draft["aspect_custom"] = [self.custom_w.value(), self.custom_h.value()]
        self.aspect_changed.emit(copy.deepcopy(self.draft))

    def _reset(self) -> None:
        self.draft = {}
        self._emit()

    def set_crop(self, crop: list[float]) -> None:
        self.draft["crop"] = crop
        self.refresh()


def scroll(widget: QWidget, name: str) -> QScrollArea:
    """Il contenuto del pannello scorre, come il pannello Info."""
    body = QWidget()
    body.setObjectName(name)
    lay = QVBoxLayout(body)
    lay.setContentsMargins(18, 10, 18, 18)
    lay.addWidget(widget)
    lay.addStretch(1)
    sa = QScrollArea()
    sa.setObjectName("sidescroll")
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sa.setWidget(body)
    body.setMinimumWidth(0)
    widget.setMinimumWidth(0)
    body.setStyleSheet(f"QWidget#{name} {{ background: transparent; }}")
    return sa
