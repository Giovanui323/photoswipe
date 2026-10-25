"""Widget dell'interfaccia, separati da app.py: visore, strisce, etichette, pulsanti."""
from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from concurrent.futures import Future
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QGraphicsOpacityEffect, QGraphicsPixmapItem, QGraphicsScene,
                               QGraphicsView, QLabel, QProxyStyle, QPushButton, QSizePolicy, QStyle, QStyleOption,
                               QWidget)

from PIL import Image

import cloud
from i18n import tr
from theme import COLORS as C


class TipStyle(QProxyStyle):
    """Suggerimenti meno frequenti: compaiono dopo un attimo più lungo e, passando da un pulsante
    all'altro, non si riaprono subito (Qt li farebbe comparire senza attesa entro 2 secondi)."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ToolTip_WakeUpDelay:
            return 1000  # ms prima della comparsa (default Qt: 700)
        if hint == QStyle.SH_ToolTip_FallAsleepDelay:
            return 0     # nessuna riapertura immediata passando da un pulsante a un altro
        return super().styleHint(hint, option, widget, returnData)


def hide_keep_space(w: QWidget, on: bool) -> None:
    """Rende w invisibile senza togliergli lo spazio: durante una modifica la foto non salta."""
    if on and w.graphicsEffect() is None:
        eff = QGraphicsOpacityEffect(w)
        eff.setOpacity(0.0)
        w.setGraphicsEffect(eff)
    elif not on:
        w.setGraphicsEffect(None)


class ElidedLabel(QLabel):
    """Etichetta su una riga che non allarga mai la finestra: se il testo non ci sta lo accorcia
    con "…" e lo mostra intero nel suggerimento."""

    def __init__(self, text: str = "", mode=Qt.ElideRight):
        super().__init__(text)
        self._mode = mode
        self._tip = ""
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)  # minimo 0: mai più larga

    def setToolTip(self, tip: str) -> None:
        self._tip = tip
        super().setToolTip(tip)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 8, super().sizeHint().height())

    def paintEvent(self, e):
        r = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), self._mode, r.width())
        tip = self.text() if text != self.text() else self._tip
        if self.toolTip() != tip:
            QLabel.setToolTip(self, tip)
        p = QPainter(self)
        opt = QStyleOption()   # sfondo e bordo del foglio di stile (es. il riquadro del percorso)
        opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        self.style().drawItemText(p, r, int(self.alignment()) | Qt.AlignVCenter, self.palette(),
                                  self.isEnabled(), text, self.foregroundRole())


def trash_pixmap(color: str, size: int = 22, dpr: float = 2.0) -> QPixmap:
    """Cestino disegnato a linee, di un solo colore come gli altri simboli (l'emoji 🗑 è grigia)."""
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), size / 11)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    u = size / 22
    p.drawLine(QPointF(4 * u, 6 * u), QPointF(18 * u, 6 * u))          # coperchio
    p.drawLine(QPointF(9 * u, 3.5 * u), QPointF(13 * u, 3.5 * u))       # maniglia
    p.drawLine(QPointF(9 * u, 3.5 * u), QPointF(9 * u, 6 * u))
    p.drawLine(QPointF(13 * u, 3.5 * u), QPointF(13 * u, 6 * u))
    body = QPainterPath(QPointF(6 * u, 6 * u))
    body.lineTo(7 * u, 18.5 * u)
    body.lineTo(15 * u, 18.5 * u)
    body.lineTo(16 * u, 6 * u)
    p.drawPath(body)
    p.drawLine(QPointF(9.5 * u, 9 * u), QPointF(9.8 * u, 15.5 * u))
    p.drawLine(QPointF(12.5 * u, 9 * u), QPointF(12.2 * u, 15.5 * u))
    p.end()
    return pm


def chevron_file() -> str:
    """Freccia ⌄ dei menu a tendina, disegnata e salvata in un PNG temporaneo (il foglio di stile
    vuole un file); senza, i menu sembrano normali pulsanti."""
    import tempfile
    uid = f"-{os.getuid()}" if hasattr(os, "getuid") else ""
    path = Path(tempfile.gettempdir()) / f"photoswipe-chevron{uid}.png"
    pm = QPixmap(20, 12)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(C["text_2"]), 2.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(3, 3), QPointF(10, 9), QPointF(17, 3)])
    p.end()
    pm.save(str(path), "PNG")
    return path.as_posix()


class TrashButton(QPushButton):
    """Pulsante rotondo con il cestino disegnato: viola (anche col cerchio tinto, al passaggio del
    mouse o a scelta già fatta), spento se disattivato. Stessi colori del foglio di stile."""
    COLORS = {"normal": C["trash"], "filled": C["trash"], "off": C["text_off"]}

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setIconSize(QSize(22, 22))
        self.refresh_icon()

    def refresh_icon(self, size: int | None = None) -> None:
        sz = size if size is not None else max(22, self.iconSize().width())
        if size is not None and self.iconSize().width() != size:
            self.setIconSize(QSize(size, size))
        state = ("off" if not self.isEnabled()
                 else "filled" if self.underMouse() or self.property("chosen") == "true" else "normal")
        if getattr(self, "_state", None) != state or getattr(self, "_icon_sz", None) != sz:
            self._state = state
            self._icon_sz = sz
            self.setIcon(trash_pixmap(self.COLORS[state], sz, max(2.0, self.devicePixelRatioF())))

    def enterEvent(self, e):
        super().enterEvent(e)
        self.refresh_icon()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.refresh_icon()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.EnabledChange:
            self.refresh_icon()


class OverlayLabel(QLabel):
    """Etichetta sopra la foto (avvisi in alto a destra, messaggi in basso al centro, come le
    notifiche di Foto). Vuota = nascosta; si riposiziona da sola a ogni testo nuovo.
    Con hide_after_ms il messaggio sparisce da solo (così non resta sopra la foto)."""

    def __init__(self, parent: QWidget, anchor: str, hide_after_ms: int = 0):
        super().__init__("", parent)
        self.anchor = anchor
        self.hide_after_ms = hide_after_ms
        self.avoid: list[QWidget] = []   # altre etichette sopra la foto da non coprire (la data)
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._clear)
        self.hide()

    def _clear(self) -> None:
        self._auto_color = False
        self.setStyleSheet("")
        self.setText("")

    def setText(self, text: str, ms: int | None = None, color: str = "") -> None:
        if color:
            self.setStyleSheet(f"color:{color};")
            self._auto_color = True
        elif getattr(self, "_auto_color", False) or not text:
            self._auto_color = False
            self.setStyleSheet("")
        super().setText(text)
        self.place()
        ms = self.hide_after_ms if ms is None else ms
        if text and ms:
            self.timer.start(ms)
        else:
            self.timer.stop()

    def place(self) -> None:
        par = self.parentWidget()
        if not self.text():
            self.hide()
            return
        self.ensurePolished()
        maxw = max(160, par.width() - 80)
        self.setWordWrap(False)
        hint = self.sizeHint()
        w = min(hint.width(), maxw)
        self.setWordWrap(w < hint.width())
        h = max(hint.height(), self.heightForWidth(w)) if self.wordWrap() else hint.height()
        self.resize(w, h)
        if self.anchor == "top-right":
            x, y = par.width() - w - 14, 12
            for o in self.avoid:   # se si sovrappone alla data, va sotto
                if o.isVisible() and o.geometry().intersects(QRect(x, y, w, h)):
                    y = max(y, o.geometry().bottom() + 8)
            self.move(x, y)
        else:
            self.move((par.width() - w) // 2, par.height() - h - 16)
        self.show()
        self.raise_()


class StaleResult(Exception):
    """Risultato di un lavoro chiesto per la cartella aperta prima: si scarta."""


class _MoveFailed(OSError):
    """Gli originali non si sono spostati in “cancellare” (niente è cambiato)."""


class AbandonedWait(StaleResult):
    """Attesa di un download lasciata a metà: l'elemento non è più quello che guardi
    (o non è più tra i prossimi da anticipare). Si scarta senza mostrare nulla."""


def wait_downloads(files: list[Path], abandon: threading.Event, delay: float = 0.0) -> bool:
    """Scarica i file dell'elemento corrente, ognuno nel suo thread: non si mette mai in coda
    dietro ai download degli elementi passati di corsa. Se l'elemento viene lasciato
    (abandon), l'attesa finisce subito; dopo un breve ritardo (delay) per non avviare
    download per gli elementi solo sfiorati scorrendo veloce."""
    if delay and abandon.wait(delay):
        raise AbandonedWait()
    futs: list[tuple[Path, Future]] = []
    for p in files:
        f: Future = Future()

        def run(p=p, f=f):
            try:
                try:
                    res = cloud.download(p, abandon=abandon)
                except TypeError:
                    res = cloud.download(p)
                f.set_result(res)
            except BaseException as e:  # noqa: BLE001 - riportato dall'attesa
                f.set_exception(e)
        threading.Thread(target=run, name=f"icloud-{p.name}", daemon=True).start()
        futs.append((p, f))
    for p, f in futs:
        while True:
            if abandon.is_set():
                raise AbandonedWait()
            try:
                ok = f.result(timeout=0.2)
                break
            except TimeoutError:
                continue
        if not ok:
            raise RuntimeError(tr('{v0} non disponibile', v0=p.name))
    return True


class Bridge(QObject):
    """Riporta nel thread dell'interfaccia i risultati dei lavori in background."""
    done = Signal(str, object, object)  # tipo, chiave, risultato (o eccezione)
    progress = Signal(object, float)    # chiave, avanzamento 0..1 (dal motore di stampa)


class ImageView(QGraphicsView):
    zoom_changed = Signal(float)   # 0 = adattata, 1 = ingrandimento massimo (per il cursore in alto)
    view_changed = Signal()        # la foto ha cambiato posto/dimensione a schermo (per la data sopra)
    crop_changed = Signal(list)    # Ritaglia: nuovo riquadro [x, y, l, a] (0..1 della foto)
    picked = Signal(float, float)  # Occhi rossi: clic sulla foto (0..1)
    clicked = Signal()             # clic semplice sulla foto (Live / video: play e stop)

    tr("Foto adattata alla finestra; due dita su/giù o pizzico = zoom, doppio clic = adatta.\n\n    Adattata: l'immagine viene ridotta UNA volta, con filtro di alta qualità, ai pixel reali dello\n    schermo (Retina compreso), invece di lasciarla ridurre al volo (più morbido/scalettato).\n    Con lo zoom si passa all'originale a piena risoluzione.")

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.loading = self.scene().addSimpleText("")
        self.loading.setBrush(QColor(C["text_2"]))
        f = self.loading.font()
        f.setPointSize(16)
        self.loading.setFont(f)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)
        self.full = QImage()
        self.zoomed = False
        # Ritaglia: riquadro sopra la foto con angoli e lati da trascinare
        self.crop_mode = False
        self.crop = [0.0, 0.0, 1.0, 1.0]
        self.crop_ratio: float | None = None   # larghezza/altezza in pixel della foto (None = libero)
        self._crop_drag: tuple[str, QPointF, list[float]] | None = None
        self._crop_hover: str | None = None
        self._grid_dense: bool = False
        self._badge_text: str = ""
        self.pick_enabled = False              # Occhi rossi: un clic indica l'occhio
        self._press_pos: QPointF | None = None
        # clic semplice: si aspetta un attimo, così il doppio clic (foto intera) non lo fa scattare
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(QApplication.doubleClickInterval())
        self._click_timer.timeout.connect(self.clicked.emit)

    def set_badge(self, text: str) -> None:
        text = text or ""
        if self._badge_text != text:
            self._badge_text = text
            self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate if (self.crop_mode or self._badge_text)
                                       else QGraphicsView.MinimalViewportUpdate)
            self.viewport().update()

    def set_grid_dense(self, dense: bool) -> None:
        dense = bool(dense)
        if self._grid_dense != dense:
            self._grid_dense = dense
            self.viewport().update()

    # ---- Ritaglia
    CROP_MARGIN = 28   # Ritaglia: spazio intorno alla foto, così angoli e lati sul bordo si prendono

    def set_crop_mode(self, on: bool, crop: list[float] | None = None, ratio: float | None = None) -> None:
        was_on, self.crop_mode = self.crop_mode, on
        self.crop = list(crop or [0.0, 0.0, 1.0, 1.0])
        self.crop_ratio = ratio
        if not on:
            self._crop_drag = None
            self._crop_hover = None
            self._grid_dense = False
            self.viewport().unsetCursor()
        self.setDragMode(QGraphicsView.NoDrag if on else QGraphicsView.ScrollHandDrag)
        # il riquadro e l'ombra intorno coprono tutta la vista: si ridisegna sempre tutta
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate if (on or self._badge_text)
                                   else QGraphicsView.MinimalViewportUpdate)
        if on or (was_on and not self.zoomed):   # all'uscita la foto torna a tutta finestra
            self.fit()
        self.viewport().update()

    def _img_rect(self) -> QRectF:
        """Dove sta la foto nel riquadro della vista (coordinate del viewport)."""
        return QRectF(self.mapFromScene(self.item.sceneBoundingRect()).boundingRect())

    def _crop_view_rect(self) -> QRectF:
        r = self._img_rect()
        x, y, w, h = self.crop
        return QRectF(r.left() + x * r.width(), r.top() + y * r.height(), w * r.width(), h * r.height())

    def _crop_hit(self, pos: QPointF) -> str | None:
        c = self._crop_view_rect()
        m = 12
        near = lambda a, b: abs(a - b) <= m   # noqa: E731
        inside_x = c.left() - m <= pos.x() <= c.right() + m
        inside_y = c.top() - m <= pos.y() <= c.bottom() + m
        if not (inside_x and inside_y):
            return None
        mode = ""
        if near(pos.y(), c.top()):
            mode += "t"
        elif near(pos.y(), c.bottom()):
            mode += "b"
        if near(pos.x(), c.left()):
            mode += "l"
        elif near(pos.x(), c.right()):
            mode += "r"
        if mode:
            return mode
        return "move" if c.contains(pos) else None

    def _aspect_n(self) -> float | None:
        """Rapporto larghezza/altezza in coordinate 0..1 (la foto non è quadrata)."""
        if not self.crop_ratio or self.full.isNull():
            return None
        return self.crop_ratio * self.full.height() / self.full.width()

    def _drag_crop(self, mode: str, d: QPointF, start: list[float]) -> list[float]:
        r = self._img_rect()
        dx, dy = d.x() / max(1.0, r.width()), d.y() / max(1.0, r.height())
        x, y, w, h = start
        mn = 0.04
        if mode == "move":
            x = max(0.0, min(1 - w, x + dx))
            y = max(0.0, min(1 - h, y + dy))
            return [x, y, w, h]
        x0, y0, x1, y1 = x, y, x + w, y + h
        if "l" in mode:
            x0 = max(0.0, min(x1 - mn, x0 + dx))
        if "r" in mode:
            x1 = min(1.0, max(x0 + mn, x1 + dx))
        if "t" in mode:
            y0 = max(0.0, min(y1 - mn, y0 + dy))
        if "b" in mode:
            y1 = min(1.0, max(y0 + mn, y1 + dy))
        a = self._aspect_n()
        if a:
            nw, nh = x1 - x0, y1 - y0
            min_nh = max(mn, mn / a)
            if mode in ("t", "b"):          # lato orizzontale: la larghezza segue, centrata
                cx = start[0] + start[2] / 2
                max_nh = min(y1 if mode == "t" else 1.0 - y0, 2.0 * min(cx, 1.0 - cx) / a)
                nh = max(min(min_nh, max_nh), min(nh, max_nh))
                nw = nh * a
                x0, x1 = cx - nw / 2, cx + nw / 2
                if mode == "t":
                    y0 = y1 - nh
                else:
                    y1 = y0 + nh
            elif mode in ("l", "r"):        # lato verticale: l'altezza segue, centrata
                cy = start[1] + start[3] / 2
                max_nw = min(x1 if mode == "l" else 1.0 - x0, 2.0 * min(cy, 1.0 - cy) * a)
                min_nw = min_nh * a
                nw = max(min(min_nw, max_nw), min(nw, max_nw))
                nh = nw / a
                y0, y1 = cy - nh / 2, cy + nh / 2
                if mode == "l":
                    x0 = x1 - nw
                else:
                    x1 = x0 + nw
            else:                           # angolo: l'angolo opposto resta fermo
                if nw / max(nh, 1e-6) > a:
                    nh = nw / a
                else:
                    nw = nh * a
                max_w = x1 if "l" in mode else 1.0 - x0
                max_h = y1 if "t" in mode else 1.0 - y0
                max_nw = min(max_w, max_h * a)
                min_nw = min_nh * a
                nw = max(min(min_nw, max_nw), min(nw, max_nw))
                nh = nw / a
                if "l" in mode:
                    x0 = x1 - nw
                else:
                    x1 = x0 + nw
                if "t" in mode:
                    y0 = y1 - nh
                else:
                    y1 = y0 + nh
        return [x0, y0, x1 - x0, y1 - y0]

    def drawForeground(self, painter: QPainter, rect) -> None:
        super().drawForeground(painter, rect)
        has_crop = self.crop_mode and not self.full.isNull()
        if not has_crop and not self._badge_text:
            return
        painter.save()
        painter.resetTransform()
        vr = QRectF(self.viewport().rect())
        if has_crop:
            c = self._crop_view_rect()
            outside = QPainterPath()
            outside.addRect(vr)
            hole = QPainterPath()
            hole.addRect(c)
            painter.fillPath(outside.subtracted(hole), QColor(0, 0, 0, 150))
            if self._grid_dense:
                painter.setPen(QPen(QColor(255, 255, 255, 65), 1))
                for i in range(1, 9):
                    if i % 3 == 0:
                        continue
                    painter.drawLine(QPointF(c.left() + c.width() * i / 9, c.top()),
                                     QPointF(c.left() + c.width() * i / 9, c.bottom()))
                    painter.drawLine(QPointF(c.left(), c.top() + c.height() * i / 9),
                                     QPointF(c.right(), c.top() + c.height() * i / 9))
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
            for i in (1, 2):   # regola dei terzi
                painter.drawLine(QPointF(c.left() + c.width() * i / 3, c.top()),
                                 QPointF(c.left() + c.width() * i / 3, c.bottom()))
                painter.drawLine(QPointF(c.left(), c.top() + c.height() * i / 3),
                                 QPointF(c.right(), c.top() + c.height() * i / 3))
            active_handle = self._crop_drag[0] if self._crop_drag else self._crop_hover
            painter.setPen(QPen(QColor(C["accent"] if active_handle == "move" else C["text_strong"]), 1.5))
            painter.drawRect(c)
            L = min(22.0, c.width() / 3, c.height() / 3)
            for name, px, py, sx, sy in (("tl", c.left(), c.top(), 1, 1),
                                         ("tr", c.right(), c.top(), -1, 1),
                                         ("bl", c.left(), c.bottom(), 1, -1),
                                         ("br", c.right(), c.bottom(), -1, -1)):
                col = QColor(C["accent"] if active_handle == name else C["text_strong"])
                painter.setPen(QPen(col, 4, Qt.SolidLine, Qt.SquareCap))
                painter.drawLine(QPointF(px, py), QPointF(px + sx * L, py))
                painter.drawLine(QPointF(px, py), QPointF(px, py + sy * L))
            hs = min(8.0, c.width() / 6, c.height() / 6)
            cx, cy = c.center().x(), c.center().y()
            for name, p1, p2 in (("t", QPointF(cx - hs, c.top()), QPointF(cx + hs, c.top())),
                                 ("b", QPointF(cx - hs, c.bottom()), QPointF(cx + hs, c.bottom())),
                                 ("l", QPointF(c.left(), cy - hs), QPointF(c.left(), cy + hs)),
                                 ("r", QPointF(c.right(), cy - hs), QPointF(c.right(), cy + hs))):
                col = QColor(C["accent"] if active_handle == name else C["text_strong"])
                painter.setPen(QPen(col, 4, Qt.SolidLine, Qt.SquareCap))
                painter.drawLine(p1, p2)
        if self._badge_text:
            f = painter.font()
            f.setPixelSize(12)
            f.setWeight(QFont.DemiBold)
            painter.setFont(f)
            tw = painter.fontMetrics().horizontalAdvance(self._badge_text)
            bw, bh = tw + 24, 26
            br = QRectF((vr.width() - bw) / 2, 14, bw, bh)
            painter.setPen(QPen(QColor(255, 255, 255, 45), 1))
            painter.setBrush(QColor(28, 28, 30, 210))
            painter.drawRoundedRect(br, 13, 13)
            painter.setPen(QColor(C["accent"]))
            painter.drawText(br, Qt.AlignCenter, self._badge_text)
        painter.restore()

    def mousePressEvent(self, e):
        self._press_pos = e.position()
        if self.crop_mode and e.button() == Qt.LeftButton:
            mode = self._crop_hit(e.position())
            if mode:
                self._crop_drag = (mode, e.position(), list(self.crop))
                self.viewport().update()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.crop_mode:
            if self._crop_drag:
                mode, p0, start = self._crop_drag
                self.crop = self._drag_crop(mode, e.position() - p0, start)
                self.viewport().update()
            else:
                hit = self._crop_hit(e.position())
                if hit != self._crop_hover:
                    self._crop_hover = hit
                    self.viewport().update()
                cur = {"move": Qt.SizeAllCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
                       "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "tl": Qt.SizeFDiagCursor,
                       "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor}
                self.viewport().setCursor(cur.get(hit, Qt.ArrowCursor))
            return
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if self._crop_hover is not None:
            self._crop_hover = None
            self.viewport().update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.crop_mode:
            if e.button() == Qt.LeftButton and self._crop_drag:
                self._crop_drag = None
                self.crop_changed.emit(list(self.crop))
                self.viewport().update()
            return
        super().mouseReleaseEvent(e)
        still = self._press_pos is not None and (e.position() - self._press_pos).manhattanLength() < 4
        if self.pick_enabled and still and not self.full.isNull():
            sp = self.mapToScene(e.position().toPoint())
            br = self.item.sceneBoundingRect()
            if br.contains(sp):
                self.picked.emit((sp.x() - br.left()) / br.width(), (sp.y() - br.top()) / br.height())
        elif still and e.button() == Qt.LeftButton:
            self._click_timer.start()

    def set_loading(self, text: str) -> None:
        self.full = QImage()
        self.zoomed = False  # la prossima immagine arriva adattata, non ingrandita
        self.item.setPixmap(QPixmap())
        self.loading.setText(text)
        self.resetTransform()
        self.scene().setSceneRect(self.loading.boundingRect())
        self.centerOn(self.loading)

    def set_image(self, img: QImage, keep_zoom: bool = False) -> None:
        self.loading.setText("")
        self.full = img
        if keep_zoom and self.zoomed:
            # stessa grandezza a schermo anche se cambia la risoluzione (anteprima -> 4K)
            same = self.item.pixmap().size() == img.size()
            self._show_full(keep_view=same)
        else:
            self.fit()

    def _show_full(self, keep_view: bool = False) -> None:
        if self.full.isNull():
            return
        if not keep_view:  # stessa dimensione a schermo di prima, ma con tutti i pixel
            shown_w = self.item.boundingRect().width() * self.transform().m11()
            self.item.setPixmap(QPixmap.fromImage(self.full))
            self.resetTransform()
            k = shown_w / self.full.width() if self.full.width() else 1
            self.scale(k, k)
        else:
            self.item.setPixmap(QPixmap.fromImage(self.full))
        self.scene().setSceneRect(self.item.boundingRect())

    def _fit_k(self) -> float:
        """Scala (punti per pixel dell'immagine) che riempie la finestra: ingrandisce anche le
        foto piccole, come Foto. Nessun limite a 1 pixel fisico per pixel."""
        m = 2 * self.CROP_MARGIN if self.crop_mode else 0
        return min(max(1, self.viewport().width() - m) / self.full.width(),
                   max(1, self.viewport().height() - m) / self.full.height())

    def _limits(self) -> tuple[float, float]:
        """Zoom minimo (adattata) e massimo: 4 pixel dello schermo per pixel della foto."""
        dpr = self.devicePixelRatioF()
        fit_k = self._fit_k()
        return fit_k, max(fit_k * 2, 4 / dpr)

    def zoom_level(self) -> float:
        if self.full.isNull() or not self.zoomed:
            return 0.0
        lo, hi = self._limits()
        k = self.transform().m11() * self.item.pixmap().width() / max(1, self.full.width())
        return 0.0 if hi <= lo else max(0.0, min(1.0, math.log(k / lo) / math.log(hi / lo)))

    def set_zoom_level(self, t: float) -> None:
        """Cursore dello zoom: 0 = foto intera, 1 = 4 pixel dello schermo per pixel. Centro fisso."""
        if self.full.isNull():
            return
        if t <= 0:
            self.fit()
            return
        lo, hi = self._limits()
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        if not self.zoomed:
            self.zoomed = True
            self._show_full()
        k = lo * (hi / lo) ** t
        self.scale(k / self.transform().m11(), k / self.transform().m11())
        self.setTransformationAnchor(anchor)
        self.view_changed.emit()

    def fit(self) -> None:
        self.zoomed = False
        self.zoom_changed.emit(0.0)
        self.resetTransform()
        if self.full.isNull():
            return
        dpr = self.devicePixelRatioF()
        k = self._fit_k()
        target_w = max(1, round(self.full.width() * k * dpr))
        target_h = max(1, round(self.full.height() * k * dpr))
        pm = QPixmap.fromImage(self.full.scaled(target_w, target_h, Qt.KeepAspectRatio,
                                                Qt.SmoothTransformation))
        pm.setDevicePixelRatio(dpr)
        self.item.setPixmap(pm)
        # il pixmap è già alla dimensione della finestra: niente fitInView, che aggiunge un margine
        # e lascia la foto qualche pixel più piccola della misura calcolata
        self.scene().setSceneRect(self.item.boundingRect())
        self.view_changed.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.zoomed:
            self.fit()

    MAX_STEP = 1.08   # ogni evento (scatto di rotella, pezzo di pizzico) cambia al massimo l'8%

    def wheelEvent(self, e):
        if self.crop_mode:
            return
        self.zoom_by(1.0015 ** e.angleDelta().y())

    def event(self, e):
        if e.type() == QEvent.NativeGesture and e.gestureType() == Qt.ZoomNativeGesture:
            if self.crop_mode:
                return True
            self.zoom_by(1.0 + e.value() * 0.5)  # pizzico sul trackpad, più dolce
            return True
        return super().event(e)

    def zoom_by(self, factor: float) -> None:
        if self.full.isNull():
            return
        factor = max(1 / self.MAX_STEP, min(self.MAX_STEP, factor))
        if not self.zoomed:
            if factor <= 1:
                return  # già adattata: non si rimpicciolisce oltre
            self.zoomed = True
            self._show_full()
        fit_k = self._fit_k()
        k = min(self.transform().m11() * factor, self._limits()[1])
        if k <= fit_k:
            self.fit()  # tornati alla dimensione intera: di nuovo adattata
            return
        self.scale(k / self.transform().m11(), k / self.transform().m11())
        self.zoom_changed.emit(self.zoom_level())
        self.view_changed.emit()

    def mouseDoubleClickEvent(self, e):
        self._click_timer.stop()   # era un doppio clic: niente play / stop
        if not self.crop_mode:
            self.fit()


class FilmStrip(QWidget):
    """Striscia di fotogrammi come in Foto di macOS: clic o trascina per scegliere il momento.

    Il riquadro bianco è il fotogramma scelto/mostrato, la linea sottile segue il video mentre va,
    i segni verdi sono le foto già salvate con 📷."""
    picked = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(72)   # in alto c'è posto per il pallino della foto originale
        self.setMinimumWidth(200)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.owner: str | None = None
        self.frames = 0
        self.thumbs: list[QImage] = []
        self.selected: int | None = None
        self.playhead: int | None = None
        self.marks: list[int] = []
        self.original: int | None = None   # Live: foto scelta dalla fotocamera (pallino)
        self._drag = False
        self._last: int | None = None
        self._hover_x: float | None = None

    def set_video(self, frames_: int, owner: str | None = None) -> None:
        self.owner, self.frames, self.thumbs = owner, frames_, []
        self.selected = self.playhead = self.original = None
        self.marks = []
        self.update()

    def set_thumbs(self, thumbs: list[QImage]) -> None:
        self.thumbs = thumbs
        self.update()

    def set_state(self, selected: int | None, marks: list[int], original: int | None = None) -> None:
        self.selected, self.marks, self.original = selected, marks, original
        if selected is not None:
            self.playhead = None   # fermi su una foto: niente linea di riproduzione
        self.update()

    def set_playhead(self, n: int | None) -> None:
        self.playhead = n
        self.update()

    def _strip(self) -> QRectF:
        return QRectF(5, 10, max(1, self.width() - 10), self.height() - 16)   # attaccata alle parentesi

    def frame_at_x(self, x: float) -> int:
        r = self._strip()
        t = min(1.0, max(0.0, (x - r.left()) / r.width()))
        return round(t * (self.frames - 1))

    def x_of(self, n: int) -> float:
        r = self._strip()
        return r.left() + (n / max(1, self.frames - 1)) * r.width()

    def _emit(self, x: float) -> None:
        if self.frames <= 0:
            return
        n = self.frame_at_x(x)
        if n != self._last:
            self._last = n
            self.picked.emit(n)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag, self._last = True, None
            self._emit(e.position().x())

    def mouseMoveEvent(self, e):
        self._hover_x = e.position().x()
        if self._drag:
            self._emit(e.position().x())
        self.update()

    def leaveEvent(self, e):
        if self._hover_x is not None:
            self._hover_x = None
            self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = False

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self._strip()
        clip = QPainterPath()
        clip.addRoundedRect(r, 6, 6)
        p.fillPath(clip, QColor(C["bg_control"]))
        if self.thumbs:
            p.save()
            p.setClipPath(clip)
            w = r.width() / len(self.thumbs)
            for i, im in enumerate(self.thumbs):  # ogni miniatura riempie la sua casella (ritaglio centrale)
                cell = QRectF(r.left() + i * w, r.top(), w + 0.5, r.height())
                k = max(cell.width() / im.width(), cell.height() / im.height())
                sw, sh = cell.width() / k, r.height() / k
                p.drawImage(cell, im, QRectF((im.width() - sw) / 2, (im.height() - sh) / 2, sw, sh))
            p.restore()
        else:
            p.save()
            p.setClipPath(clip)
            p.setPen(QPen(QColor(255, 255, 255, 24), 1))
            step = 16
            x_tick = r.left() + step
            while x_tick < r.right():
                p.drawLine(QPointF(x_tick, r.top() + 6), QPointF(x_tick, r.bottom() - 6))
                x_tick += step
            p.restore()
        if self._hover_x is not None and r.left() <= self._hover_x <= r.right():
            p.setPen(QPen(QColor(255, 255, 255, 110), 1.5))
            p.drawLine(QPointF(self._hover_x, r.top()), QPointF(self._hover_x, r.bottom()))
        if self.frames <= 0:
            return
        for n in self.marks:  # foto già salvate
            x = self.x_of(n)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C["yes"]))
            p.drawRoundedRect(QRectF(x - 2, r.bottom() - 9, 4, 12), 2, 2)
        if self.original is not None:  # pallino sopra la striscia, come la "foto chiave" di Foto
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C["text_strong"] if self.original == self.selected else C["accent"]))
            p.drawEllipse(QPointF(self.x_of(self.original), 2.75), 2.25, 2.25)
        if self.playhead is not None and self.selected is None:
            x = self.x_of(self.playhead)
            p.setPen(QPen(QColor(C["text_strong"]), 2))
            p.drawLine(int(x), int(r.top()) - 3, int(x), int(r.bottom()) + 3)
        if self.selected is not None:
            x = self.x_of(self.selected)
            bw = r.height() * 0.75
            box = QRectF(x - bw / 2, r.top() - 4, bw, r.height() + 8)
            p.setPen(QPen(QColor(C["text_strong"]), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box, 5, 5)


class LruCache(OrderedDict):
    """Dizionario con un numero massimo di elementi: quando è pieno toglie quello usato meno di
    recente. Per le miniature: si rifanno da sole se servono di nuovo, la memoria resta limitata."""

    def __init__(self, maxsize: int):
        super().__init__()
        self.maxsize = maxsize

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def get(self, key, default=None):
        return self[key] if key in self else default

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self.maxsize:
            self.popitem(last=False)


class SnapGallery(QWidget):
    """Le foto prese dal video che stai guardando, in miniatura (pannello a destra, in basso).
    Clic = il video torna su quel fotogramma per rivederlo; doppio clic = la foto intera, con la
    stampabilità e le correzioni; ✕ sulla miniatura = la toglie da export."""
    picked = Signal(int)        # fotogramma
    viewed = Signal(str)        # chiave della foto (id#fN): doppio clic
    removed = Signal(str)       # chiave della foto (id#fN)
    COLS, GAP, CAP = 2, 8, 16

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.entries: list[tuple[str, int, str | None]] = []   # (chiave, fotogramma, file)
        self.current: int | None = None
        self._hover: int | None = None
        self._cache: LruCache = LruCache(40)   # ~0,5 MB l'una
        self.setFixedHeight(0)

    def set_entries(self, entries: list[tuple[str, int, str | None]], current: int | None) -> None:
        self.entries, self.current = sorted(entries, key=lambda e: e[1]), current
        rows = math.ceil(len(self.entries) / self.COLS)
        self.setFixedHeight(rows * (self._cell_h() + self.CAP + self.GAP) if rows else 0)
        self.update()

    def _cell_w(self) -> float:
        return (self.width() - self.GAP * (self.COLS - 1)) / self.COLS

    def _cell_h(self) -> int:
        return round((max(200, self.width()) - self.GAP * (self.COLS - 1)) / self.COLS * 9 / 16)

    def _rect(self, i: int) -> QRectF:
        r, c = divmod(i, self.COLS)
        return QRectF(c * (self._cell_w() + self.GAP), r * (self._cell_h() + self.CAP + self.GAP),
                      self._cell_w(), self._cell_h())

    def _close_rect(self, i: int) -> QRectF:
        r = self._rect(i)
        return QRectF(r.right() - 24, r.top() + 4, 20, 20)

    def _at(self, pos) -> int | None:
        for i in range(len(self.entries)):
            if self._rect(i).adjusted(0, 0, 0, self.CAP).contains(pos):
                return i
        return None

    def invalidate(self, path: str | None = None) -> None:
        if path is None:
            self._cache.clear()
        else:
            for k in [k for k in self._cache if (k[0] if isinstance(k, tuple) else k) == path]:
                self._cache.pop(k, None)
        self.update()

    def _thumb(self, path: str | None) -> QImage | None:
        if not path:
            return None
        try:
            mtime_ns = os.stat(path).st_mtime_ns
        except OSError:
            return None
        ckey = (path, mtime_ns)
        if ckey not in self._cache:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():   # JPEG: si decodifica già ridotto, è veloce anche col 4K
                reader.setScaledSize(size.scaled(QSize(480, 270), Qt.KeepAspectRatioByExpanding))
            im = reader.read()
            if im.isNull():
                return None      # export non ancora finito: si riprova al prossimo aggiornamento
            self._cache[ckey] = im
        return self._cache[ckey]

    def mouseMoveEvent(self, e):
        i = self._at(e.position())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        i = self._at(e.position())
        if i is None or e.button() != Qt.LeftButton:
            return
        key, frame, _ = self.entries[i]
        if self._close_rect(i).contains(e.position()):
            self.removed.emit(key)
        else:
            self.picked.emit(frame)

    def mouseDoubleClickEvent(self, e):
        i = self._at(e.position())
        if i is not None and self.entries[i][2] and not self._close_rect(i).contains(e.position()):
            self.viewed.emit(self.entries[i][0])

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        for i, (key, frame, path) in enumerate(self.entries):
            r = self._rect(i)
            clip = QPainterPath()
            clip.addRoundedRect(r, 6, 6)
            p.fillPath(clip, QColor(C["bg_control"]))
            im = self._thumb(path)
            if im is not None:
                k = max(r.width() / im.width(), r.height() / im.height())
                sw, sh = r.width() / k, r.height() / k
                p.save()
                p.setClipPath(clip)
                p.drawImage(r, im, QRectF((im.width() - sw) / 2, (im.height() - sh) / 2, sw, sh))
                p.restore()
            else:
                p.setPen(QColor(C["text_2"]))
                p.drawText(r, Qt.AlignCenter, tr('salvo…'))
            if frame == self.current:  # è il fotogramma che stai guardando
                p.setPen(QPen(QColor(C["text_strong"]), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
            if i == self._hover:
                c = self._close_rect(i)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 170))
                p.drawEllipse(c)
                p.setPen(QPen(QColor(C["text_strong"]), 1.6))
                p.drawLine(c.center() + QPointF(-4, -4), c.center() + QPointF(4, 4))
                p.drawLine(c.center() + QPointF(-4, 4), c.center() + QPointF(4, -4))
            p.setPen(QColor(C["text_2"]))
            f = p.font()
            f.setPixelSize(11)
            p.setFont(f)
            p.drawText(QRectF(r.left(), r.bottom() + 2, r.width(), self.CAP - 2),
                       Qt.AlignLeft | Qt.AlignVCenter, tr('fotogramma {v0}', v0=frame + 1))


class ThumbStrip(QWidget):
    """Miniature degli elementi prima e dopo quello che guardi, come la striscia in fondo a Foto.
    Quella attuale è al centro, più grande e con il bordo; un pallino colorato dice la scelta già
    fatta. Clic = vai a quell'elemento."""
    picked = Signal(int)
    wanted = Signal(list)   # indici delle miniature in vista, dal centro verso i bordi: vanno caricate
    CELL_W, CELL_H, GAP = 74, 52, 6
    THUMB_SIDE = 184   # lato corto delle miniature: copre la casella grande (×1,18) su Retina (×2)
    DOT = {"yes": C["yes"], "no": C["no"], "skip": C["skip"], "trash": C["trash"], "snap": C["yes"]}
    # simbolo nel pallino: la scelta si capisce anche senza distinguere rosso e verde
    DOT_GLYPH = {"yes": "✓", "no": "✕", "skip": "↪", "trash": "⌫", "snap": "✓"}

    def __init__(self):
        super().__init__()
        self.setFixedHeight(self.CELL_H + 18)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.entries: list[tuple[int, QImage | None, str | None, bool, str]] = []
        self.current: int | None = None
        self._rects: list[tuple[QRectF, int]] = []
        self._hover_idx: int | None = None
        self.frame_color = C["selected"]   # bordo della miniatura attuale (vedi update_thumb_strip)
        self.outside = False          # quella attuale non rientra nel filtro: bordo grigio tratteggiato
        self._shown: list[int] = []   # ultime miniature in vista (vedi wanted)
        self.pan = 0.0            # spostamento attuale (pixel): la striscia si muove da qui
        self._target = 0.0        # dove deve arrivare: lo scorrimento è morbido, come in Foto
        self._vel = 0.0           # velocità del trascinamento, poi l'inerzia la fa decrescere
        self._press = None        # (x iniziale, pan iniziale, x precedente) mentre si trascina
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_entries(self, entries, current: int | None) -> None:
        """entries: (indice, miniatura o None, scelta o None, è un video/Live, nome file)."""
        if current != self.current:
            self.pan = self._target = 0.0   # cambia la foto guardata: la striscia torna centrata
            self._vel = 0.0
        self.entries, self.current = entries, current
        self.update()

    def set_thumb(self, i: int, img: QImage) -> None:
        """È arrivata la miniatura dell'elemento i: solo lei, senza ricostruire la striscia."""
        for k, en in enumerate(self.entries):
            if en[0] == i:
                self.entries[k] = (i, img) + tuple(en[2:])
                self.update()
                return

    def ask_shown(self) -> None:
        """Richiede di nuovo le miniature in vista (per riprovare quelle non riuscite)."""
        if self._shown:
            self.wanted.emit(list(self._shown))

    def _limit(self) -> float:
        """Quanto si può spostare: fino all'ultima miniatura da una parte e dall'altra."""
        return max(0.0, (len(self.entries) * (self.CELL_W + self.GAP) - self.width()) / 2 + self.CELL_W)

    def _clamp(self, v: float) -> float:
        lim = self._limit()
        return max(-lim, min(lim, v))

    def _start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        """Un passo di animazione: inerzia dopo il trascinamento, e avvicinamento al punto di arrivo."""
        if self._press is None:
            if abs(self._vel) > 0.2:
                self._target = self._clamp(self._target + self._vel)
                self._vel *= 0.92                  # l'inerzia si spegne piano, come sul trackpad
            else:
                self._vel = 0.0
        self.pan += (self._target - self.pan) * 0.22   # arriva al punto con un movimento morbido
        self.update()
        if self._press is None and abs(self._target - self.pan) < 0.3 and self._vel == 0.0:
            self.pan = self._target
            self._timer.stop()
            self.update()

    def nudge(self, px: float) -> None:
        """Sposta la striscia di px pixel (positivo = verso destra), con movimento morbido."""
        self._target = self._clamp(self._target + px)
        self._vel = 0.0
        self._start()

    def recenter(self) -> None:
        """Riporta la striscia centrata sulla foto che stai guardando."""
        self._target = 0.0
        self._vel = 0.0
        self._start()

    def wheelEvent(self, e):
        pd = e.pixelDelta()
        if not pd.isNull():                        # trackpad: segue le dita, l'inerzia la dà il sistema
            d = pd.x() or pd.y()
            self._target = self.pan = self._clamp(self.pan + d)
            self._vel = 0.0
            self.update()
        else:                                      # rotella: uno scatto = una finestra di miniature
            steps = (e.angleDelta().x() or e.angleDelta().y()) / 120
            self.nudge(-steps * 2.5 * (self.CELL_W + self.GAP))
        self._start()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            x = e.position().x()
            self._press = (x, self.pan, x)
            self._vel = 0.0

    def mouseMoveEvent(self, e):
        if self._press is None:
            hov = next((i for r, i in self._rects if r.contains(e.position())), None)
            if hov != self._hover_idx:
                self._hover_idx = hov
                self.update()
            return
        x0, pan0, last = self._press
        x = e.position().x()
        if abs(x - x0) > 3:                        # trascinamento: la striscia segue il dito
            self.pan = self._target = self._clamp(pan0 + (x - x0))
            self._vel = x - last                   # serve per l'inerzia al rilascio
            self._press = (x0, pan0, x)
            self.update()

    def leaveEvent(self, e):
        if self._hover_idx is not None:
            self._hover_idx = None
            self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._press is None:
            return
        x0, _, _ = self._press
        self._press = None
        if abs(e.position().x() - x0) <= 3:        # un clic, non un trascinamento
            self._vel = 0.0
            for r, i in self._rects:
                if r.contains(e.position()):
                    self.picked.emit(i)
                    break
        self._vel = max(-60.0, min(60.0, self._vel * 1.5))
        self._start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self._rects = []
        if not self.entries:
            self._shown = []
            return
        cw, ch, gap = self.CELL_W, self.CELL_H, self.GAP
        big = 1.18
        cx = self.width() / 2 + self.pan
        cy = self.height() / 2
        pos = [k for k, en in enumerate(self.entries) if en[0] == self.current]
        center_k = pos[0] if pos else len(self.entries) - 0.5
        for k, (i, img, choice, clip, name) in enumerate(self.entries):
            scale = big if i == self.current else 1.0
            w, h = cw * scale, ch * scale
            off = (k - center_k) * (cw + gap)
            if pos and k != center_k:  # spazio in più attorno a quella grande
                off += (cw * (big - 1) / 2 + 2) * (1 if k > center_k else -1)
            r = QRectF(cx + off - w / 2, cy - h / 2, w, h)
            if r.right() < 0 or r.left() > self.width():
                continue
            self._rects.append((r, i))
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            p.fillPath(path, QColor(C["bg_control"]))
            if img is not None and not img.isNull():
                p.save()
                p.setClipPath(path)
                k_ = max(r.width() / img.width(), r.height() / img.height())
                sw, sh = r.width() / k_, r.height() / k_
                p.drawImage(r, img, QRectF((img.width() - sw) / 2, (img.height() - sh) / 2, sw, sh))
                p.restore()
            else:
                p.setPen(QPen(QColor(C["text_2"]), 1.2))
                p.setBrush(Qt.NoBrush)
                ic = QRectF(r.center().x() - 9, r.top() + 9, 18, 13)
                p.drawRoundedRect(ic, 2.5, 2.5)
                if clip:
                    tri = QPainterPath(QPointF(ic.center().x() - 2, ic.center().y() - 3))
                    tri.lineTo(QPointF(ic.center().x() + 3, ic.center().y()))
                    tri.lineTo(QPointF(ic.center().x() - 2, ic.center().y() + 3))
                    tri.closeSubpath()
                    p.fillPath(tri, QColor(C["text_2"]))
                else:
                    p.drawEllipse(ic.center(), 3.2, 3.2)
                p.setPen(QColor(C["text_2"]))
                f = p.font()
                f.setPixelSize(10)
                p.setFont(f)
                tr_rect = QRectF(r.left() + 4, r.bottom() - 16, r.width() - 8, 13)
                elided = p.fontMetrics().elidedText(name, Qt.ElideMiddle, max(10, int(tr_rect.width())))
                p.drawText(tr_rect, Qt.AlignCenter, elided)
            if i != self.current:
                alpha = 30 if i == self._hover_idx else (70 if choice is None else 120)
                p.fillPath(path, QColor(0, 0, 0, alpha))  # già decise: più scure
            if clip:   # ▶ su un dischetto scuro: leggibile anche su miniature chiare
                disc = QRectF(r.left() + 4, r.bottom() - 18, 14, 14)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 140))
                p.drawEllipse(disc)
                p.setPen(QColor(C["text_strong"]))
                f = p.font()
                f.setPixelSize(8)
                p.setFont(f)
                p.drawText(disc.adjusted(1, 0, 1, 0), Qt.AlignCenter, "▶")
            if choice in self.DOT:
                dot = QRectF(r.right() - 16, r.top() + 3, 13, 13)
                p.setPen(QPen(QColor(C["bg_window"]), 1.5))
                p.setBrush(QColor(self.DOT[choice]))
                p.drawEllipse(dot)
                f = p.font()
                f.setPixelSize(9)
                f.setBold(True)
                p.setFont(f)
                p.setPen(QColor(C["bg_window"]))
                p.drawText(dot, Qt.AlignCenter, self.DOT_GLYPH[choice])
            if i == self.current:   # miniatura attuale: bordo del colore del tipo scelto
                pen = QPen(QColor(C["text_2"] if self.outside else self.frame_color), 2.5)
                if self.outside:
                    pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 7, 7)
        # quelle in vista, dal centro: se sono cambiate (scorrendo, o cambiate le voci) si caricano
        mid = self.width() / 2
        shown = [i for r, i in sorted(self._rects, key=lambda ri: abs(ri[0].center().x() - mid))]
        if shown != self._shown:
            self._shown = shown
            QTimer.singleShot(0, self.ask_shown)
        # ai bordi le miniature sfumano nello sfondo invece di finire tagliate di netto
        fade = 40
        for x0, x1 in ((0, fade), (self.width(), self.width() - fade)):
            g = QLinearGradient(x0, 0, x1, 0)
            bg = QColor(C["bg_window"])
            g.setColorAt(0, bg)
            bg.setAlpha(0)
            g.setColorAt(1, bg)
            p.fillRect(QRectF(min(x0, x1), 0, fade, self.height()), g)


def qimage_to_pil(q: QImage) -> "Image.Image":
    q = q.convertToFormat(QImage.Format_RGB888)
    w, h, bpl = q.width(), q.height(), q.bytesPerLine()
    buf = bytes(q.constBits())[:bpl * h]
    return Image.frombuffer("RGB", (w, h), buf, "raw", "RGB", bpl, 1)


def pil_to_qimage(img) -> QImage:
    img = img.convert("RGB")
    data = img.tobytes()
    return QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888).copy()
