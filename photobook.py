"""Fotolibro nel pannello Info: le ultime 5 foto approvate, impaginate come un album aperto.

A sinistra l'ultima approvata fino alla miniatura selezionata, grande; a destra le 4 prima
(2 × 2). Dà l'idea di come sta venendo la selezione senza uscire dalla foto che stai guardando."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QLabel, QToolTip, QVBoxLayout, QWidget

import thumbcache
from i18n import tr
from scanner import Item
from theme import COLORS as C
from widgets import LruCache

SHOWN = 5
PAPER, PAPER_SHADE = QColor("#f3efe6"), QColor("#d9d3c5")   # carta color avorio, più scura verso il dorso


def last_accepted(session, items: list[Item], upto: int, n: int = SHOWN) -> list[Item]:
    """Le ultime n foto approvate fino all'elemento upto compreso, nell'ordine della cartella (la
    più vicina per prima): tornando indietro nelle miniature il libro torna indietro con te.
    Niente video né foto prese dai video: quelle hanno già la loro galleria."""
    out: list[Item] = []
    if session is None:
        return out
    for it in reversed(items[:upto + 1]):
        d = session.get(it.id)
        if d and d.get("choice") == "yes" and it.kind != "video":
            out.append(it)
            if len(out) == n:
                break
    return out


def pin_below(scroll: QWidget, book: "PhotoBook") -> QWidget:
    """Pagina Info: sopra le Info che scorrono, sotto il fotolibro fisso. Con tante foto prese da
    un video scorre la parte sopra, il fotolibro resta sempre in vista."""
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(scroll, 1)
    wrap = QVBoxLayout()
    wrap.setContentsMargins(18, 0, 18, 14)   # come le Info sopra
    wrap.addWidget(book)
    lay.addLayout(wrap)
    return page


class _Bridge(QObject):
    done = Signal(str, object)   # id dell'elemento, miniatura (QImage)


class PhotoBook(QWidget):
    """Sezione a sé del pannello Info: titolo con la riga sopra (come Selezione e Salvataggio)
    e il libro. Senza approvate resta nascosta."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        head = QLabel(tr('Ultime foto approvate').upper())
        head.setObjectName("subhead")
        lay.addWidget(head)
        self.book = _Book()
        lay.addWidget(self.book)
        self.opened = self.book.opened
        self.setVisible(False)

    @property
    def items(self) -> list[Item]:
        return self.book.items

    def refresh(self, session, items: list[Item], upto: int) -> None:
        self.book.refresh(session, items, upto)
        self.setVisible(bool(self.book.items))

    def setVisible(self, on: bool) -> None:   # la schermata iniziale la spegne; senza foto resta spenta
        super().setVisible(on and bool(self.book.items))


class _Book(QWidget):
    """Album aperto con le ultime foto approvate. Clic su una foto = vai a quella foto."""
    opened = Signal(str)   # id dell'elemento

    def __init__(self):
        super().__init__()
        self.items: list[Item] = []
        self._thumbs: LruCache = LruCache(12)
        self._asked: set[str] = set()
        self._pool = ThreadPoolExecutor(1, thread_name_prefix="photobook")
        self._bridge = _Bridge()
        self._bridge.done.connect(self._arrived)
        self.setMouseTracking(True)
        self.setFixedHeight(0)   # niente approvate: non occupa spazio
        self.setAccessibleName(tr('Fotolibro: ultime foto approvate'))

    def refresh(self, session, items: list[Item], upto: int) -> None:
        items = last_accepted(session, items, upto)
        if [i.id for i in items] == [i.id for i in self.items]:
            return
        self.items = items
        for it in items:
            if it.id not in self._thumbs and it.id not in self._asked:
                self._asked.add(it.id)
                fut = self._pool.submit(thumbcache.cached_thumb, it)
                fut.add_done_callback(lambda f, k=it.id: self._bridge.done.emit(
                    k, None if f.exception() else f.result()))
        self._fit()
        self.update()

    def _arrived(self, key: str, img) -> None:
        self._asked.discard(key)
        if isinstance(img, QImage) and not img.isNull():
            self._thumbs[key] = img
            if any(it.id == key for it in self.items):
                self.update()

    def resizeEvent(self, e):
        self._fit()
        super().resizeEvent(e)

    def _fit(self) -> None:
        h = round(self.width() * 0.62) if self.items else 0
        if h != self.height():
            self.setFixedHeight(h)

    # ---- impaginazione
    def _book(self) -> QRectF:
        return QRectF(self.rect()).adjusted(1, 1, -1, -3)

    def _slots(self) -> list[QRectF]:
        """Caselle delle foto: 0 = grande a sinistra, 1-4 = griglia 2 × 2 a destra."""
        b = self._book().adjusted(5, 5, -5, -5)   # copertina che sporge dalle pagine
        half = b.width() / 2
        m, g = b.width() * 0.05, b.width() * 0.025   # margine della pagina e spazio tra le foto
        left = QRectF(b.left() + m, b.top() + m, half - 1.5 * m, b.height() - 2 * m)
        rx, ry = b.left() + half + m / 2, b.top() + m
        cw, ch = (half - 1.5 * m - g) / 2, (b.height() - 2 * m - g) / 2
        grid = [QRectF(rx + c * (cw + g), ry + r * (ch + g), cw, ch) for r in range(2) for c in range(2)]
        return [left] + grid

    def _at(self, pos) -> int | None:
        for i, r in enumerate(self._slots()[:len(self.items)]):
            if r.contains(pos):
                return i
        return None

    def mouseMoveEvent(self, e):
        i = self._at(e.position())
        self.setCursor(Qt.PointingHandCursor if i is not None else Qt.ArrowCursor)
        if i is None:
            QToolTip.hideText()
        else:
            QToolTip.showText(e.globalPosition().toPoint(),
                              tr('{v0}\nClic: torna a questa foto', v0=self.items[i].main.name), self)

    def mousePressEvent(self, e):
        i = self._at(e.position())
        if i is not None and e.button() == Qt.LeftButton:
            self.opened.emit(self.items[i].id)

    def paintEvent(self, e):
        if not self.items:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        book = self._book()
        # ombra e copertina
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(book.translated(0, 2), 7, 7)
        p.setBrush(QColor(C["bg_hover"]))
        p.drawRoundedRect(book, 7, 7)
        # due pagine, più scure verso il dorso
        pages = book.adjusted(5, 5, -5, -5)
        mid = pages.center().x()
        for page, edge in ((QRectF(pages.left(), pages.top(), mid - pages.left(), pages.height()), 1),
                           (QRectF(mid, pages.top(), pages.right() - mid, pages.height()), 0)):
            g = QLinearGradient(page.left(), 0, page.right(), 0)
            g.setColorAt(edge, PAPER_SHADE)
            g.setColorAt(0.82 if edge else 0.18, PAPER)
            g.setColorAt(1 - edge, PAPER)
            p.setBrush(g)
            p.drawRoundedRect(page, 3, 3)
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.drawLine(QPointF(mid, pages.top()), QPointF(mid, pages.bottom()))
        # le foto, ritagliate al centro per riempire la casella
        for i, r in enumerate(self._slots()):
            p.setPen(Qt.NoPen)
            if i >= len(self.items):   # casella ancora libera: un segno leggero sulla carta
                p.setPen(QPen(PAPER_SHADE, 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
                continue
            p.setBrush(QColor(0, 0, 0, 45))
            p.drawRect(r.translated(0.8, 1.2))
            im = self._thumbs.get(self.items[i].id)
            if im is None:
                p.setBrush(PAPER_SHADE)
                p.drawRect(r)
                continue
            k = max(r.width() / im.width(), r.height() / im.height())
            sw, sh = r.width() / k, r.height() / k
            p.drawImage(r, im, QRectF((im.width() - sw) / 2, (im.height() - sh) / 2, sw, sh))
        p.end()

