"""Fotolibro nel pannello Info: le ultime 5 foto approvate, impaginate come un album aperto.

A sinistra l'ultima approvata fino alla miniatura selezionata, grande; a destra le 4 prima
(2 × 2). Contano anche le foto prese dai video con 📷 Prendi foto. Dà l'idea di come sta
venendo la selezione senza uscire dalla foto che stai guardando. "Apri l'album" (o il clic sulla
carta del libro) apre l'album con tutte le approvate, da sfogliare (album.py)."""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolTip, QVBoxLayout, QWidget

import thumbcache
from i18n import tr
from scanner import Item
from theme import COLORS as C
from widgets import LruCache

SHOWN = 5
PAPER, PAPER_SHADE = QColor("#f3efe6"), QColor("#d9d3c5")   # carta color avorio, più scura verso il dorso


class Page(NamedTuple):
    """Una foto del libro: approvata, oppure presa da un video (key = id#fN, path = la copia in export)."""
    key: str           # chiave nella sessione (e della miniatura)
    id: str            # elemento a cui tornare col clic (per una foto presa: il suo video)
    main: Path         # file da cui prende il nome nel suggerimento
    item: Item
    path: str | None   # foto presa: la copia in export (None finché l'export non è finito)


IMAGE_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp")


def _snaps(session, it: Item) -> list[Page]:
    """Foto prese da questo video (o Live), dall'ultimo fotogramma al primo."""
    out = []
    for key, d in session.decisions.items():
        if key.startswith(it.id + "#f") and d.get("choice") == "snap":
            files = [f for f in d.get("files") or [] if Path(f).suffix.lower() in (".jpg", ".png")]
            name = Path(files[0]) if files else it.main.with_name(f"{it.main.stem}_f{d.get('frame', 0) + 1}.jpg")
            out.append((d.get("frame") or 0, Page(key, it.id, name, it, files[0] if files else None)))
    return [p for _, p in sorted(out, key=lambda x: -x[0])]


def _exported_photo_path(session, it: Item, d: dict) -> str | None:
    """Se la foto è modificata o è una Live con fotogramma scelto, usa il file esportato su disco."""
    edit = (session.get_edit(it.id) if hasattr(session, "get_edit")
            else (getattr(session, "edits", None) or {}).get(it.id))
    edited = bool(edit)
    live_frame = it.kind == "live" and d.get("frame") is not None
    if edited or live_frame:
        for f in d.get("files") or []:
            p = Path(f)
            if p.suffix.lower() in IMAGE_EXT and p.exists():
                return f
    return None


def last_accepted(session, items: list[Item], upto: int, n: int = SHOWN) -> list[Page]:
    """Le ultime n foto approvate fino all'elemento upto compreso, nell'ordine della cartella (la
    più vicina per prima): tornando indietro nelle miniature il libro torna indietro con te.
    Contano le foto prese dai video (anche se il video è NO: restano in export), non i video."""
    out: list[Page] = []
    if session is None:
        return out
    for it in reversed(items[:upto + 1]):
        if it.is_clip:
            out += _snaps(session, it)
        d = session.get(it.id)
        if d and d.get("choice") == "yes" and it.kind != "video":
            out.append(Page(it.id, it.id, it.main, it, _exported_photo_path(session, it, d)))
        if len(out) >= n:
            break
    return out[:n]


def all_accepted(session, items: list[Item]) -> list[Page]:
    """Tutte le foto del libro, dalla prima all'ultima della cartella: le pagine dell'album."""
    return last_accepted(session, items, len(items) - 1, sys.maxsize)[::-1]


def _thumb(page: Page) -> QImage:
    """Miniatura: della copia in export per le foto prese, della cache delle miniature per le altre."""
    if page.path is None:
        return thumbcache.cached_thumb(page.item)
    reader = QImageReader(page.path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():   # JPEG: si decodifica già ridotto
        reader.setScaledSize(size.scaled(QSize(480, 360), Qt.KeepAspectRatioByExpanding))
    return reader.read()


def go_to(win, key: str, tries: int = 40) -> None:
    """Clic su una foto del libro: torna a quell'elemento, per rivederlo o cambiare scelta. Una
    foto presa da un video riporta al video fermo su quel fotogramma (come la sua galleria)."""
    item_id, _, frame = key.partition("#f")
    cur = win.current()
    if cur is None or cur.id != item_id:
        win.jump_to(next((i for i, it in enumerate(win.items) if it.id == item_id), -1))
        cur = win.current()
    if not frame.isdigit() or cur is None or cur.id != item_id or cur.kind != "video":
        return
    if item_id in win.infos:
        win.review_snap(int(frame))
    elif tries:   # video appena aperto: il fotogramma si può scegliere quando l'analisi è pronta
        QTimer.singleShot(100, lambda: go_to(win, key, tries - 1))


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
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        head = QLabel(tr('Ultime foto approvate').upper())
        head.setObjectName("subhead")
        self.open_btn = QPushButton(tr("Apri l'album ›"))
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setToolTip(tr("Sfoglia tutte le foto approvate impaginate come un album."))
        self.open_btn.setStyleSheet(f"QPushButton {{ background: transparent; border: none; padding: 12px 0 0 0;"
                                    f" color: {C['link']}; font-size: 12px; }}"
                                    f" QPushButton:hover {{ color: {C['link_hover']}; }}")
        self.open_btn.clicked.connect(self.open_album)
        row.addWidget(head)
        row.addStretch(1)
        row.addWidget(self.open_btn, 0, Qt.AlignBottom)
        lay.addLayout(row)
        self.book = _Book()
        self.book.blank_clicked.connect(self.open_album)
        lay.addWidget(self.book)
        self.opened = self.book.opened
        self.album = None
        self._session, self._items = None, []
        self.setVisible(False)

    @property
    def items(self) -> list[Page]:
        return self.book.items

    def refresh(self, session, items: list[Item], upto: int) -> None:
        self._session, self._items = session, items
        self.book.refresh(session, items, upto)
        self.setVisible(bool(self.book.items))

    def open_album(self) -> None:
        import album   # album importa questo modulo
        pages = all_accepted(self._session, self._items)
        if not pages:
            return
        self.album = album.AlbumDialog(self.window(), self._session, pages)
        self.album.opened.connect(self.opened.emit)   # clic su una foto: si torna lì, come nel libro
        self.album.show()
        self.album.raise_()
        self.album.activateWindow()

    def clear(self) -> None:
        self._session, self._items = None, []
        self.book._thumbs.clear()
        self.book._asked.clear()
        self.book._paths.clear()
        self.book.items = []
        self.book._fit()
        self.book.update()
        self.setVisible(False)

    def shutdown(self) -> None:
        self.book._pool.shutdown(wait=False, cancel_futures=True)

    def setVisible(self, on: bool) -> None:   # la schermata iniziale la spegne; senza foto resta spenta
        super().setVisible(on and bool(self.book.items))


class _Book(QWidget):
    """Album aperto con le ultime foto approvate. Clic su una foto = vai a quella foto."""
    opened = Signal(str)   # chiave della foto (id, o id#fN per una foto presa da un video)
    blank_clicked = Signal()   # clic sulla carta, fuori dalle foto: apri l'album

    def __init__(self):
        super().__init__()
        self.items: list[Page] = []
        self._thumbs: LruCache = LruCache(12)
        self._asked: set[str] = set()
        self._paths: dict[str, tuple[str | None, int | None]] = {}
        self._hover_i: int | None = -1
        self._pool = ThreadPoolExecutor(1, thread_name_prefix="photobook")
        self._bridge = _Bridge()
        self._bridge.done.connect(self._arrived)
        self.setMouseTracking(True)
        self.setFixedHeight(0)   # niente approvate: non occupa spazio
        self.setAccessibleName(tr('Fotolibro: ultime foto approvate'))

    @staticmethod
    def _path_sig(path: str | None) -> tuple[str | None, int | None]:
        if not path:
            return (None, None)
        try:
            return (path, Path(path).stat().st_mtime_ns)
        except OSError:
            return (path, None)

    def refresh(self, session, items: list[Item], upto: int) -> None:
        pages = last_accepted(session, items, upto)
        # anche con le stesse foto: una foto presa ha la miniatura solo a export finito
        for pg in pages:
            sig = self._path_sig(pg.path)
            if self._paths.get(pg.key) != sig:
                self._thumbs.pop(pg.key, None)
                self._asked.discard(pg.key)
            is_snap = "#f" in pg.key
            ready = (pg.path is not None and Path(pg.path).exists()) if is_snap else (pg.path is None or Path(pg.path).exists())
            if pg.key not in self._thumbs and pg.key not in self._asked and ready:
                self._paths[pg.key] = sig
                self._asked.add(pg.key)
                fut = self._pool.submit(_thumb, pg)
                fut.add_done_callback(lambda f, k=pg.key: self._bridge.done.emit(
                    k, None if f.exception() else f.result()))
        if [(p.key, p.path) for p in pages] != [(p.key, p.path) for p in self.items]:
            self.items = pages
            self._fit()
            self.update()

    def _arrived(self, key: str, img) -> None:
        self._asked.discard(key)
        if isinstance(img, QImage) and not img.isNull():
            self._thumbs[key] = img
            if any(pg.key == key for pg in self.items):
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
        self.setCursor(Qt.PointingHandCursor)
        if i != self._hover_i:
            self._hover_i = i
            if i is None:
                QToolTip.showText(e.globalPosition().toPoint(), tr("Clic: apri l'album"), self)
            else:
                QToolTip.showText(e.globalPosition().toPoint(),
                                  tr('{v0}\nClic: torna a questa foto', v0=self.items[i].main.name), self)

    def leaveEvent(self, e):
        self._hover_i = -1
        QToolTip.hideText()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        i = self._at(e.position())
        if e.button() != Qt.LeftButton:
            return
        if i is not None:
            self.opened.emit(self.items[i].key)
        elif self.items:
            self.blank_clicked.emit()

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
            im = self._thumbs.get(self.items[i].key)
            if im is None:
                p.setBrush(PAPER_SHADE)
                p.drawRect(r)
                continue
            k = max(r.width() / im.width(), r.height() / im.height())
            sw, sh = r.width() / k, r.height() / k
            p.drawImage(r, im, QRectF((im.width() - sw) / 2, (im.height() - sh) / 2, sw, sh))
        p.end()

