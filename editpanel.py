"""Pannelli Regola e Ritaglia (come in Foto di macOS) e il selettore Info · Regola · Ritaglia."""
from __future__ import annotations

import copy

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

import edits as E

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
QFrame#side QPushButton#opts { background: transparent; border: none; padding: 2px 0 2px 18px; font-size: 13px;
    color: #d1d1d6; text-align: left; }
QFrame#side QPushButton#reset, QFrame#side QPushButton#cropbtn { background: #3a3a3c; border: none; border-radius: 15px;
    padding: 7px 14px; font-size: 13px; text-align: center; }
QFrame#side QPushButton#reset:hover, QFrame#side QPushButton#cropbtn:hover { background: #48484a; }
QFrame#side QPushButton#reset:disabled, QFrame#side QPushButton#cropbtn:disabled { color: #6e6e73; background: #2c2c2e; }
QFrame#side QPushButton#cropok { background: #ffd60a; color: #1c1c1e; border: none; border-radius: 15px;
    padding: 7px 14px; font-size: 14px; font-weight: 700; text-align: center; }
QFrame#side QPushButton#cropok:hover { background: #ffe14d; }
QFrame#side QPushButton#aspect { background: transparent; border: none; border-radius: 6px; padding: 3px 6px;
    font-size: 14px; color: #d1d1d6; text-align: left; }
QFrame#side QPushButton#aspect:hover { background: #2f2f31; color: #ffffff; }
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
        p.setPen(QPen(QColor("#8e8e93"), 2))
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
        ic = QLabel(icon)
        ic.setFixedWidth(20)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet("font-size: 15px; color: #d1d1d6;")
        self.title = QPushButton(title)
        self.title.setToolTip(title)
        self.title.setObjectName("sectitle")
        self.undo = QPushButton("↶")
        self.undo.setObjectName("secundo")
        self.undo.setToolTip("Annulla questa regolazione")
        self.auto = QPushButton("AUTO")
        self.auto.setObjectName("auto")
        self.auto.setToolTip("Regolazione automatica")
        self.auto.setVisible(auto)
        self.circle = CircleToggle()
        self.circle.setToolTip("Accendi / spegni questa regolazione (per confrontare)")
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
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #3a3a3c;")
        v.addWidget(line)
        self.chev.clicked.connect(self.toggle)
        self.title.clicked.connect(self.toggle)
        self.set_open(expanded)

    def toggle(self) -> None:
        self.set_open(not self.body.isVisible())
        self.toggled_open.emit(self.body.isVisible())

    def set_open(self, on: bool) -> None:
        self.body.setVisible(on)
        self.chev.setText("⌄" if on else "›")

    def is_open(self) -> bool:
        return self.body.isVisible()

    def set_state(self, modified: bool, on: bool) -> None:
        self.undo.setVisible(modified)
        self.circle.set_active(modified and on)
        self.circle.setVisible(modified or self.auto.isVisible())


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
        head = QLabel("REGOLA")
        head.setObjectName("section")
        v.addWidget(head)

        def bar(key, label, lo=-1.0, hi=1.0, fmt=None):
            b = ValueBar(label, lo, hi, E.DEFAULTS[key], fmt)
            b.changed.connect(lambda val, k=key: self._set(k, val))
            self.bars[key] = b
            return b

        def options(sec: Section, widgets) -> None:
            btn = QPushButton("›  Opzioni")
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
                btn.setText(("⌄" if box.isVisible() else "›") + "  Opzioni")
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
        s = section("light", "☀︎", "Luce", auto=True, expanded=True)
        sc = ThumbScrubber()
        sc.changed.connect(lambda val: self._set("light", val))
        self.scrubbers["light"] = sc
        s.body_lay.addWidget(sc)
        options(s, [bar("brilliance", "Brillantezza"), bar("exposure", "Esposizione"),
                    bar("highlights", "Luci"), bar("shadows", "Ombre"), bar("brightness", "Luminosità"),
                    bar("contrast", "Contrasto"), bar("blackpoint", "Punto di nero")])
        # Colore
        s = section("color", "◍", "Colore", auto=True, expanded=True)
        sc = ThumbScrubber()
        sc.changed.connect(lambda val: self._set("color", val))
        self.scrubbers["color"] = sc
        s.body_lay.addWidget(sc)
        options(s, [bar("saturation", "Saturazione"), bar("vibrance", "Vividezza"), bar("cast", "Dominante")])
        # Bianco e nero
        s = section("bw", "◐", "Bianco e nero", auto=True, expanded=True)
        sc = ThumbScrubber()
        sc.changed.connect(lambda val: self._set("bw", val, bw=True))
        self.scrubbers["bw"] = sc
        s.body_lay.addWidget(sc)
        options(s, [bar("bw_intensity", "Intensità"), bar("bw_neutrals", "Toni neutri"),
                    bar("bw_tone", "Tono"), bar("bw_grain", "Grana", 0, 1, pct)])
        for k in ("bw_intensity", "bw_neutrals", "bw_tone", "bw_grain"):
            self.bars[k].changed.connect(lambda _v: self._ensure_bw())
        # Occhi rossi
        s = section("redeye", "👁", "Occhi rossi")
        note = QLabel("Fai clic su ogni occhio rosso nella foto.\nIl cursore regola la misura del cerchio.")
        note.setObjectName("editnote")
        note.setWordWrap(True)
        s.body_lay.addWidget(note)
        s.body_lay.addWidget(bar("redeye_size", "Dimensione", 0.005, 0.12, lambda val: f"{round(val * 1000)}"))
        rr = QHBoxLayout()
        self.btn_redeye_undo = QPushButton("Togli l'ultimo")
        self.btn_redeye_undo.setObjectName("small2")
        self.btn_redeye_undo.clicked.connect(self._redeye_undo)
        rr.addWidget(self.btn_redeye_undo)
        rr.addStretch(1)
        s.body_lay.addLayout(rr)
        s.toggled_open.connect(self.redeye_mode.emit)
        # Bilanciamento del bianco
        s = section("wb", "▨", "Bilanc. del bianco", auto=True)
        s.body_lay.addWidget(bar("wb_temp", "Temperatura"))
        s.body_lay.addWidget(bar("wb_tint", "Tinta"))
        # Curve
        s = section("curves", "⌇", "Curve")
        self.curve_preview = CurvePreview()
        s.body_lay.addWidget(self.curve_preview)
        for k, lab in (("curve_blacks", "Neri"), ("curve_shadows", "Ombre"), ("curve_mid", "Mezzitoni"),
                       ("curve_high", "Luci"), ("curve_whites", "Cognome")):
            s.body_lay.addWidget(bar(k, lab))
        # Livelli
        s = section("levels", "▥", "Livelli", auto=True)
        for k, lab, lo, hi in (("lv_black", "Nero (ingresso)", 0, 0.5), ("lv_gamma", "Mezzitoni", -1, 1),
                               ("lv_white", "Bianco (ingresso)", 0.5, 1), ("lv_out_black", "Nero (uscita)", 0, 0.5),
                               ("lv_out_white", "Bianco (uscita)", 0.5, 1)):
            s.body_lay.addWidget(bar(k, lab, lo, hi, pct if k != "lv_gamma" else None))
        # Definizione
        s = section("definition", "◺", "Definizione", auto=True)
        s.body_lay.addWidget(bar("definition", "Intensità", 0, 1, pct))
        # Colore selettivo
        s = section("selective", "⁘", "Colore selettivo")
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
        self.sel_bars = {p: ValueBar(lab) for p, lab in (("h", "Tonalità"), ("s", "Saturazione"), ("l", "Luminanza"))}
        for p, b in self.sel_bars.items():
            b.changed.connect(lambda val, pp=p: self._set(f"sel_{self.sel_hue}_{pp}", val))
            s.body_lay.addWidget(b)
        # Riduzione disturbo, Nitidezza, Vignettatura
        s = section("noise", "▦", "Riduz. disturbo", auto=True)
        s.body_lay.addWidget(bar("noise", "Intensità", 0, 1, pct))
        s = section("deblur", "◌", "Sfocatura", auto=True)
        note = QLabel("Recupera un po' di nitidezza nelle foto sfocate o leggermente mosse.\n"
                      "AUTO stima quanto è sfocata; Raggio = quanto era sfocata.")
        note.setObjectName("editnote")
        note.setWordWrap(True)
        s.body_lay.addWidget(note)
        s.body_lay.addWidget(bar("deblur", "Intensità", 0, 1, pct))
        s.body_lay.addWidget(bar("deblur_radius", "Raggio", 0, 1, pct))
        s = section("sharpen", "◢", "Nitidezza", auto=True)
        s.body_lay.addWidget(bar("sharp_amount", "Intensità", 0, 1, pct))
        s.body_lay.addWidget(bar("sharp_edges", "Bordi", 0, 1, pct))
        s.body_lay.addWidget(bar("sharp_falloff", "Attenuazione", 0, 1, pct))
        s = section("vignette", "◎", "Vignettatura")
        s.body_lay.addWidget(bar("vig_amount", "Intensità"))
        s.body_lay.addWidget(bar("vig_radius", "Raggio", 0, 1, pct))
        s.body_lay.addWidget(bar("vig_soft", "Morbidezza", 0, 1, pct))

        v.addSpacing(6)
        self.btn_reset = QPushButton("Reimposta regolazioni")
        self.btn_reset.setObjectName("reset")
        self.btn_reset.setFocusPolicy(Qt.NoFocus)
        self.btn_reset.setToolTip("Toglie tutte le regolazioni di questa foto (il ritaglio resta).")
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
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QLabel("RITAGLIA")
        head.setObjectName("section")
        v.addWidget(head)
        self.bars = {
            "straighten": ValueBar("Raddrizza", -45, 45, 0, _deg),
            "vertical": ValueBar("Verticale", -1, 1, 0, lambda x: _deg(x * 30)),
            "horizontal": ValueBar("Orizzontale", -1, 1, 0, lambda x: _deg(x * 30)),
        }
        for icon, (k, b) in zip(("⊖", "⏃", "⏛"), self.bars.items()):
            row = QHBoxLayout()
            row.setSpacing(8)
            ic = QLabel(icon)
            ic.setFixedWidth(20)
            ic.setAlignment(Qt.AlignCenter)
            ic.setStyleSheet("font-size: 15px; color: #d1d1d6;")
            row.addWidget(ic)
            row.addWidget(b, 1)
            b.changed.connect(lambda val, kk=k: self._set(kk, val))
            v.addLayout(row)
        self.bars["straighten"].setToolTip("Ruota la foto (doppio clic = 0°). ⌥ mentre trascini = più preciso.")
        self.bars["vertical"].setToolTip("Raddrizza le linee verticali che convergono (palazzi).")
        self.bars["horizontal"].setToolTip("Corregge la prospettiva da sinistra a destra.")
        v.addSpacing(4)
        self.btn_flip = QPushButton("⇋   Capovolgi")
        self.btn_flip.setObjectName("flip")
        self.btn_flip.setFocusPolicy(Qt.NoFocus)
        self.btn_flip.setCursor(Qt.PointingHandCursor)
        self.btn_flip.setToolTip("Specchia la foto da sinistra a destra.")
        self.btn_flip.clicked.connect(self._flip)
        v.addWidget(self.btn_flip)
        ph = QHBoxLayout()
        lab = QLabel("▦   Proporzioni")
        lab.setStyleSheet("font-size: 15px; color: #d1d1d6;")
        ph.addWidget(lab, 1)
        self.orient: dict[bool, QPushButton] = {}
        og = QButtonGroup(self)
        for portrait, text, tip in ((False, "▭", "Orizzontale"), (True, "▯", "Verticale")):
            b = QPushButton(text)
            b.setObjectName("orient")
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, pp=portrait: self._set_orient(pp))
            og.addButton(b)
            self.orient[portrait] = b
            ph.addWidget(b)
        v.addLayout(ph)
        self.aspect_btns: dict[str, QPushButton] = {}
        ag = QButtonGroup(self)
        for key, name, _r in E.ASPECTS:
            b = QPushButton(name)
            b.setObjectName("aspect")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._set_aspect(k))
            ag.addButton(b)
            self.aspect_btns[key] = b
            v.addWidget(b)
        cr = QHBoxLayout()
        cr.setContentsMargins(26, 0, 0, 0)
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
        hint = QLabel("Trascina gli angoli o i lati del riquadro sulla foto; trascina dentro per spostarlo.\n"
                      "Poi OK per confermare il ritaglio (o Annulla).")
        hint.setObjectName("editnote")
        hint.setWordWrap(True)
        v.addWidget(hint)
        row = QHBoxLayout()
        self.btn_auto = QPushButton("Automatico")
        self.btn_auto.setToolTip("Raddrizza l'orizzonte da solo.")
        self.btn_reset = QPushButton("Reimposta")
        self.btn_reset.setToolTip("Toglie ritaglio, rotazione e prospettiva.")
        for b in (self.btn_auto, self.btn_reset):
            b.setObjectName("cropbtn")
            b.setFocusPolicy(Qt.NoFocus)
            row.addWidget(b, 1)
        self.btn_auto.clicked.connect(self.auto.emit)
        self.btn_reset.clicked.connect(self._reset)
        v.addLayout(row)
        row2 = QHBoxLayout()
        self.btn_cancel = QPushButton("Annulla")
        self.btn_cancel.setObjectName("cropbtn")
        self.btn_cancel.setToolTip("Lascia la foto com'era prima di aprire Ritaglia (Esc).")
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setObjectName("cropok")
        self.btn_ok.setToolTip("Conferma il ritaglio (Invio). Poi con ✓ Sì si esporta la foto ritagliata.")
        for b in (self.btn_cancel, self.btn_ok):
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            row2.addWidget(b, 1)
        self.btn_cancel.clicked.connect(self.cancel.emit)
        self.btn_ok.clicked.connect(self.ok.emit)
        v.addLayout(row2)
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
        for p, b in self.orient.items():
            b.setEnabled(key not in ("free", "original", "square", "custom"))
            b.setChecked(portrait is not None and p == portrait)
        self.btn_flip.setText("⇋   Capovolgi" + ("  ✓" if d.get("flip") else ""))
        self.btn_reset.setEnabled(E.has_geometry(d) or key != "free")
        for key2, b in self.aspect_btns.items():
            name = dict((k, n) for k, n, _ in E.ASPECTS)[key2]
            b.setText(("✓   " if b.isChecked() else "      ") + name)

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
