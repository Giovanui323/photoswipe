"""Album delle foto approvate: si apre dal fotolibro del pannello Info e si sfoglia a doppia pagina.

Tutte le approvate (e le foto prese dai video) nell'ordine della cartella, come stampe incollate
su carta avorio, da 2 a 5 per pagina, raccolte per momento e luogo (vedi plan): le foto dello
stesso posto e dello stesso giorno insieme, un altro posto o un altro giorno su un'altra pagina
quando ci sono abbastanza foto da riempirla. Una foto da sola su una pagina è l'eccezione: solo
per una foto lontana settimane da tutte le altre. Sotto: data e luogo. ← → (o la rotella, o le frecce ai lati) girano la pagina;
clic su una foto = chiudi l'album e torna a quella foto; Esc chiude. All'apertura la copertina
si apre sul dorso (poi non si vede più: da lì in poi solo foto, dalla prima all'ultima) e alla
chiusura si richiude, con la finestra in dissolvenza. Si vede la versione
esportata (con ritaglio e regolazioni) quando c'è, altrimenti l'originale."""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QImageIOHandler, QImageReader, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QToolTip, QVBoxLayout, QWidget

import cloud
import metadata
import places
import thumbcache
from datefmt import _MESI_LUNGHI
from i18n import tr
from photobook import PAPER, PAPER_SHADE, Page
from theme import COLORS as C
from widgets import LruCache

PAGE_MAX = 5   # foto in una pagina
PAGE_COST = {1: 8.0, 2: 1.2, 3: 0.3, 4: 0.0, 5: 0.0}   # una foto da sola solo in mancanza d'altro
PLACE_KM = 2   # entro questa distanza: lo stesso luogo
FAR_COST = 2 * PAGE_COST[1] + 1   # oltre due settimane: meglio due pagine da una foto che insieme
LONG_SIDE = 1600               # lato lungo delle foto caricate: nitide anche a tutto schermo
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp")
SPREAD_ASPECT = 1.5            # due pagine 3 × 4 affiancate


def source(session, page: Page) -> str | None:
    """Il file da mostrare: la copia in export (con le modifiche) se c'è, se no l'originale."""
    if page.path:
        return page.path if Path(page.path).exists() else None
    d = (session.get(page.key) if session else None) or {}
    for f in d.get("files") or []:
        if Path(f).suffix.lower() in IMAGE_EXT and Path(f).exists():
            return f
    img = page.item.image
    return str(img) if img and cloud.is_local(img) else None


def aspect(src: str | None) -> float:
    """Larghezza / altezza come si vedrà (rotazione EXIF compresa), letta solo dall'intestazione."""
    if not src:
        return 4 / 3
    r = QImageReader(src)
    s = r.size()
    if not s.isValid() or s.height() <= 0:
        return 4 / 3
    a = s.width() / s.height()
    turned = bool(r.transformation() & QImageIOHandler.TransformationRotate90)
    if not turned:   # Qt non sempre legge l'orientamento (HEIC, alcune foto di iPhone): lo chiede a PIL
        try:
            from PIL import Image
            with Image.open(src) as im:
                turned = im.getexif().get(0x0112) in (5, 6, 7, 8)
        except Exception:
            pass
    return 1 / a if turned else a


def load(src: str | None, page: Page) -> QImage:
    if src:
        r = QImageReader(src)
        r.setAutoTransform(True)
        size = r.size()
        if size.isValid() and max(size.width(), size.height()) > LONG_SIDE:
            r.setScaledSize(size.scaled(LONG_SIDE, LONG_SIDE, Qt.KeepAspectRatio))
        img = r.read()
        if not img.isNull():
            return img
    return thumbcache.cached_thumb(page.item)   # DNG, file su iCloud, …: almeno la miniatura


def gps_of(page: Page) -> tuple[float, float] | None:
    """Coordinate dello scatto, dall'originale (le copie in export possono non averle)."""
    src = page.item.image or page.item.raw
    if src is None or not cloud.is_local(src):
        return None
    return metadata.read_image(src).gps


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(min(1.0, h)))


def _by_place(day: list[int], gps: list) -> list[tuple[list[int], tuple | None]]:
    """Le foto di un giorno raccolte per luogo (anche se non sono una dopo l'altra), nell'ordine
    in cui compare ogni luogo. Una foto senza GPS sta col luogo della foto prima."""
    groups: list[list[int]] = []
    where: list = []
    prev = None
    for i in day:
        g = gps[i]
        if g is None:
            c = prev if prev is not None else (0 if groups else None)
        else:
            c = next((k for k, a in enumerate(where) if a and km(a, g) <= PLACE_KM), None)
            if c is None:   # un gruppo cominciato con foto senza GPS prende questo luogo
                c = next((k for k, a in enumerate(where) if a is None), None)
        if c is None:
            groups.append([])
            where.append(g)
            c = len(groups) - 1
        groups[c].append(i)
        where[c] = where[c] or g
        prev = c
    return list(zip(groups, where))


def _link(a: Page, b: Page, pa, pb) -> tuple[float, float]:
    """Due foto una dopo l'altra: (quanto costa tenerle sulla stessa pagina, quanto costa
    separarle). Stesso momento: separarle costa; altro posto o altro giorno: metterle insieme
    costa, tanto più quanto sono lontane (oltre due settimane più di due pagine da una foto:
    due foto lontane mesi o anni non finiscono mai sulla stessa pagina)."""
    dt = abs((b.item.taken - a.item.taken).total_seconds())
    days = abs((b.item.taken.date() - a.item.taken.date()).days)
    away = pa is not None and pb is not None and km(pa, pb) > PLACE_KM
    if days == 0:
        if away:
            return 1.0, 0.0
        return 0.2 * min(1.0, dt / 10800), 0.6 / (1 + dt / 1200)   # dopo ore: un altro momento
    if days <= 3:
        return (3.0 if away else 1.5), 0.0
    if days <= 14:
        return (6.0 if away else 4.0), 0.0
    return FAR_COST, 0.0


def plan(photos: list[Page], gps: list | None = None) -> list[list[int]]:
    """Le foto divise in pagine come in un album fatto a mano. Nel giorno le foto si raccolgono
    per luogo (anche se non sono una dopo l'altra); poi fra tutti i modi di tagliare la fila in
    pagine da 1 a PAGE_MAX si sceglie quello che costa meno: separare foto dello stesso momento
    costa, tenere insieme posti o giorni diversi costa, e una pagina con una foto sola costa più
    di quasi tutto, così resta solo per una foto lontana settimane da tutte le altre. Le pagine
    di uno stesso gruppo si dividono in parti simili (11 = 4 + 4 + 3, non 5 + 5 + 1), tagliando
    dove c'è più distanza tra una foto e l'altra. Senza GPS: solo le date e le ore."""
    gps = gps or [None] * len(photos)
    days: list[list[int]] = []
    # in ordine di scatto (la data può cambiare dopo il download da iCloud: la fila no)
    for i in sorted(range(len(photos)), key=lambda k: photos[k].item.taken):
        pg = photos[i]
        if days and photos[days[-1][-1]].item.taken.date() == pg.item.taken.date():
            days[-1].append(i)
        else:
            days.append([i])
    seq: list[int] = []
    where: list = []   # luogo del gruppo di ogni foto (anche di quelle senza GPS)
    for day in days:
        for group, at in _by_place(day, gps):
            seq += group
            where += [at] * len(group)
    n = len(seq)
    links = [_link(photos[seq[k]], photos[seq[k + 1]], where[k], where[k + 1]) for k in range(n - 1)]
    inside = [0.0]   # inside[k]: costo dei legami fra le prime k + 1 foto, tutte su una pagina
    for keep, _ in links:
        inside.append(inside[-1] + keep)
    best = [0.0] + [math.inf] * n   # best[j]: il costo minore per le prime j foto
    cut = [0] * (n + 1)
    for j in range(1, n + 1):
        for size in range(1, min(PAGE_MAX, j) + 1):
            i = j - size
            c = best[i] + PAGE_COST[size] + inside[j - 1] - inside[i] + (links[i - 1][1] if i else 0.0)
            if c < best[j] - 1e-9:
                best[j], cut[j] = c, i
    pages: list[list[int]] = []
    j = n
    while j:
        pages.append(seq[cut[j]:j])
        j = cut[j]
    return pages[::-1]


def _short_place(at: tuple[float, float]) -> str:
    try:
        name = places.offline(*at)
    except Exception:
        return ""
    prefix = tr('vicino a {v0}', v0="")
    near = name.startswith(prefix)
    short = (name[len(prefix):] if near else name).split(" · ")[0].split(",")[0]
    return tr('vicino a {v0}', v0=short) if near else short


def place_name(gps: list, idx: list[int]) -> str:
    """I luoghi della pagina in breve ("Los Angeles · Universal City"), dall'elenco incluso:
    niente rete. Al massimo due, nell'ordine delle foto."""
    names: list[str] = []
    for i in idx:
        if gps[i]:
            n = _short_place(gps[i])
            if n and n not in names:
                names.append(n)
    return " · ".join(names[:2])


def caption(photos: list[Page], idx: list[int], place: str = "") -> str:
    """Sotto la pagina: il giorno, o i giorni (3 – 5 luglio 2026), e il luogo."""
    when = date_range([photos[i] for i in idx])
    return f"{when} · {place}" if place else when


def _trees(lo: int, hi: int, memo: dict) -> list:
    """Tutti i modi di impaginare le foto lo..hi-1 tagliando la pagina in due, e ogni parte ancora
    in due, in orizzontale ("h": affiancate) o in verticale ("v": una sopra l'altra), senza
    cambiarne l'ordine. Con 5 foto sono 224: righe, colonne e tutte le combinazioni miste
    (una verticale grande accanto a due orizzontali una sopra l'altra, …)."""
    if (lo, hi) not in memo:
        memo[lo, hi] = [lo] if hi - lo == 1 else [
            (way, a, b) for k in range(lo + 1, hi) for a in _trees(lo, k, memo)
            for b in _trees(k, hi, memo) for way in "hv"]
    return memo[lo, hi]


def _shape(t, aspects: list[float], g: float) -> tuple[float, float]:
    """Forma di un pezzo di pagina come larghezza = a × altezza + b (b: gli spazi tra le foto)."""
    if isinstance(t, int):
        return aspects[t], 0.0
    way, l, r = t
    (a1, b1), (a2, b2) = _shape(l, aspects, g), _shape(r, aspects, g)
    if way == "h":   # stessa altezza, larghezze sommate
        return a1 + a2, b1 + b2 + g
    a = 1 / (1 / a1 + 1 / a2)   # stessa larghezza, altezze sommate
    return a, (b1 / a1 + b2 / a2 - g) * a


def _place(t, aspects: list[float], g: float, x: float, y: float, w: float, h: float, out: dict) -> None:
    if isinstance(t, int):
        out[t] = QRectF(x, y, w, h)
        return
    way, l, r = t
    (a1, b1) = _shape(l, aspects, g)
    if way == "h":
        w1 = a1 * h + b1
        _place(l, aspects, g, x, y, w1, h, out)
        _place(r, aspects, g, x + w1 + g, y, w - w1 - g, h, out)
    else:
        h1 = (w - b1) / a1
        _place(l, aspects, g, x, y, w, h1, out)
        _place(r, aspects, g, x, y + h1 + g, w, h - h1 - g, out)


def slots(r: QRectF, aspects: list[float]) -> list[QRectF]:
    """Caselle delle foto, già con le proporzioni giuste (orizzontali e verticali intere, mai
    schiacciate): fra tutte le impaginazioni possibili tiene quella che riempie di più la pagina
    con foto di grandezza simile."""
    if not aspects:
        return []
    g = r.width() * 0.04
    best = None
    for t in _trees(0, len(aspects), {}):
        a, b = _shape(t, aspects, g)
        h = r.height() if a * r.height() + b <= r.width() else (r.width() - b) / a
        w = a * h + b
        if h <= 0 or w <= 0:
            continue
        out: dict = {}
        _place(t, aspects, g, r.left() + (r.width() - w) / 2, r.top() + (r.height() - h) / 2, w, h, out)
        rects = [out[i] for i in range(len(aspects))]
        if min(min(q.width(), q.height()) for q in rects) <= 0:
            continue
        areas = [q.width() * q.height() for q in rects]
        score = sum(areas) / (r.width() * r.height()) - 0.04 * (max(areas) / min(areas) - 1)
        if best is None or score > best[0]:
            best = (score, rects)
    return best[1] if best else [r] * len(aspects)


def fit(slot: QRectF, a: float) -> QRectF:
    """La foto intera dentro la casella, al centro (niente ritagli: è una stampa)."""
    w = min(slot.width(), slot.height() * a)
    h = w / a
    return QRectF(slot.center().x() - w / 2, slot.center().y() - h / 2, w, h)


def date_range(pages: list[Page]) -> str:
    if not pages:
        return ""
    d0, d1 = min(p.item.taken for p in pages), max(p.item.taken for p in pages)
    one = lambda d: f"{d.day} {_MESI_LUNGHI[d.month - 1]} {d.year}"  # noqa: E731
    if d0.date() == d1.date():
        return one(d0)
    if (d0.year, d0.month) == (d1.year, d1.month):
        return f"{d0.day} – {one(d1)}"
    return f"{one(d0)} – {one(d1)}"


class _Bridge(QObject):
    sized = Signal(object)        # aspetti di tutte le foto
    loaded = Signal(int, object)  # indice della foto, QImage


class _Spread(QWidget):
    """Il libro aperto: disegna la doppia pagina corrente e l'animazione della pagina che gira."""
    picked = Signal(int)   # indice della foto cliccata

    def __init__(self, dlg: "AlbumDialog"):
        super().__init__()
        self.dlg = dlg
        self.spread = 0
        self.setMouseTracking(True)
        self.setMinimumSize(480, 320)
        self._anim = QVariantAnimation(self, duration=420, startValue=0.0, endValue=1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self.update)
        self._anim.finished.connect(self._flip_done)
        self._flip: tuple[QPixmap, QPixmap, int] | None = None   # vecchia, nuova, verso (+1 avanti)
        self._then = None   # cosa fare a pagina girata (chiusura: chiudere la finestra)
        self._hover_key: str | None = None

    # ---- geometria
    def book(self) -> QRectF:
        r = QRectF(self.rect()).adjusted(24, 16, -24, -16)
        w = min(r.width(), r.height() * SPREAD_ASPECT)
        h = w / SPREAD_ASPECT
        return QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)

    def _photos(self, spread: int) -> list[tuple[QRectF, int]]:
        """(rettangolo della foto, indice) per le foto della doppia pagina."""
        out = []
        b = self.book().adjusted(8, 8, -8, -8)
        half = b.width() / 2
        for side in (0, 1):
            pg = spread * 2 + side
            if pg >= len(self.dlg.pages):
                continue
            idx = self.dlg.pages[pg]
            m = half * 0.08
            page = QRectF(b.left() + side * half, b.top(), half, b.height())
            inner = page.adjusted(m if side else m * 1.2, m, -m * 1.2 if not side else -m, -m * 1.25)
            aspects = [self.dlg.aspects[i] for i in idx]
            for s, i in zip(slots(inner, aspects), idx):
                out.append((fit(s.adjusted(4, 4, -4, -4), self._real_aspect(i)), i))
        return out

    def _real_aspect(self, i: int) -> float:
        im = self.dlg.images.get(i)
        return im.width() / im.height() if im is not None and im.height() else self.dlg.aspects[i]

    def at(self, pos) -> int | None:
        if self._flip:
            return None
        for r, i in self._photos(self.spread):
            if r.adjusted(-6, -6, 6, 6).contains(pos):
                return i
        return None

    # ---- disegno
    def render_spread(self, p: QPainter, spread: int) -> None:
        book = self.book()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawRoundedRect(book.translated(0, 5), 10, 10)
        p.setBrush(QColor(C["bg_pressed"]))   # copertina
        p.drawRoundedRect(book, 10, 10)
        b = book.adjusted(8, 8, -8, -8)
        mid = b.center().x()
        for side, page in enumerate((QRectF(b.left(), b.top(), mid - b.left(), b.height()),
                                     QRectF(mid, b.top(), b.right() - mid, b.height()))):
            g = QLinearGradient(page.left(), 0, page.right(), 0)
            edge = 0 if side else 1   # più scura verso il dorso
            g.setColorAt(edge, PAPER_SHADE)
            g.setColorAt(0.9 if edge else 0.1, PAPER)
            g.setColorAt(1 - edge, PAPER)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(page, 4, 4)
            pg = spread * 2 + side
            if pg < len(self.dlg.pages):
                p.setPen(QColor(0, 0, 0, 110))
                f = QFont(self.font())
                f.setPointSizeF(max(8.0, page.height() * 0.022))
                p.setFont(f)
                num = page.adjusted(page.width() * 0.08, 0, -page.width() * 0.08, -page.height() * 0.025)
                p.drawText(num, Qt.AlignBottom | (Qt.AlignRight if side else Qt.AlignLeft), str(pg + 1))
                f.setItalic(True)
                p.setFont(f)
                text = caption(self.dlg.photos, self.dlg.pages[pg],
                               self.dlg.places[pg] if pg < len(self.dlg.places) else "")
                fm = QFontMetrics(f)   # dentro la pagina, senza coprire il numero (centrato: spazio ai due lati)
                free = num.width() - 2 * (fm.horizontalAdvance(str(pg + 1)) + fm.horizontalAdvance("  "))
                p.drawText(num, Qt.AlignBottom | Qt.AlignHCenter, fm.elidedText(text, Qt.ElideRight, max(0, int(free))))
        p.setPen(QPen(QColor(0, 0, 0, 70), 1))
        p.drawLine(QPointF(mid, b.top()), QPointF(mid, b.bottom()))
        for r, i in self._photos(spread):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 55))   # ombra della stampa
            p.drawRect(r.adjusted(-3, -3, 3, 3).translated(1.5, 2.5))
            p.setBrush(QColor("#fcfbf8"))      # bordo bianco della stampa
            p.drawRect(r.adjusted(-3, -3, 3, 3))
            im = self.dlg.images.get(i)
            if im is None:
                p.setBrush(PAPER_SHADE)
                p.drawRect(r)
            else:
                p.drawImage(r, im, QRectF(im.rect()))   # r ha già le proporzioni della foto

    def _grab(self, spread: int) -> QPixmap:
        pm = QPixmap(self.size() * self.devicePixelRatioF())
        pm.setDevicePixelRatio(self.devicePixelRatioF())
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self.render_spread(p, spread)
        p.end()
        return pm

    def _grab_cover(self) -> QPixmap:
        """Il libro chiuso: solo la copertina, a destra del dorso (si apre verso sinistra)."""
        pm = QPixmap(self.size() * self.devicePixelRatioF())
        pm.setDevicePixelRatio(self.devicePixelRatioF())
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        b = self.book()
        cover = QRectF(b.center().x(), b.top(), b.width() / 2, b.height())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawRoundedRect(cover.translated(0, 5), 10, 10)
        g = QLinearGradient(cover.left(), 0, cover.right(), 0)
        g.setColorAt(0, QColor(C["bg_window"]))
        g.setColorAt(0.06, QColor(C["bg_pressed"]))
        g.setColorAt(1, QColor(C["bg_hover"]))
        p.setBrush(g)
        p.drawRoundedRect(cover, 10, 10)
        gold = QColor("#c9a961")
        p.setPen(QPen(gold, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(cover.adjusted(cover.width() * 0.1, cover.width() * 0.1, -cover.width() * 0.1, -cover.width() * 0.1))
        f = QFont("Georgia")
        f.setPointSizeF(max(14.0, cover.height() * 0.055))
        p.setFont(f)
        p.drawText(cover.adjusted(0, cover.height() * 0.36, 0, 0), Qt.AlignHCenter | Qt.AlignTop, tr('Foto approvate'))
        f.setPointSizeF(max(9.0, cover.height() * 0.026))
        f.setItalic(True)
        p.setFont(f)
        n = len(self.dlg.photos)
        p.drawText(cover.adjusted(0, cover.height() * 0.48, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                   f"{tr('{n} foto', n=n) if n != 1 else tr('1 foto')}\n{date_range(self.dlg.photos)}")
        p.end()
        return pm

    def _play(self, old: QPixmap, new: QPixmap, way: int, then=None) -> None:
        self._flip, self._then = (old, new, way), then
        self._anim.start()

    def turn(self, to: int) -> None:
        to = max(0, min(to, self.dlg.spreads() - 1))
        if to == self.spread or self._flip:
            return
        old = self._grab(self.spread)
        self.spread, way = to, (1 if to > self.spread else -1)
        self._play(old, self._grab(to), way)
        self.dlg.spread_changed()

    def open_book(self) -> None:
        """La copertina si apre girando sul dorso, come la prima pagina."""
        self._play(self._grab_cover(), self._grab(self.spread), 1)

    def close_book(self, then) -> None:
        """Le pagine si richiudono sotto la copertina; poi then()."""
        if self._flip:   # pagina che sta girando: si chiude dalla pagina dove arriva
            self._anim.stop()
        self._play(self._grab(self.spread), self._grab_cover(), -1, then)

    def refresh_flip(self) -> None:
        """Una foto della pagina nuova è arrivata durante l'animazione: si ridisegna la nuova."""
        if self._flip and self._then is None and self._anim.state() == QVariantAnimation.Running:
            self._flip = (self._flip[0], self._grab(self.spread), self._flip[2])

    def _flip_done(self) -> None:
        then, self._then = self._then, None
        if then:   # chiusura: resta disegnato il libro chiuso mentre la finestra sparisce
            then()
            return
        self._flip = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self._flip:
            self.render_spread(p, self.spread)
            p.end()
            return
        old, new, way = self._flip
        t = float(self._anim.currentValue() or 0.0) if self._anim.state() == QVariantAnimation.Running else 1.0
        b = self.book()
        mid = b.center().x()
        dpr = old.devicePixelRatio()
        full = QRectF(self.rect())
        # sotto: la metà che resta ferma della vecchia e la metà già scoperta della nuova
        left, right = QRectF(0, 0, mid, full.height()), QRectF(mid, 0, full.width() - mid, full.height())
        src = lambda r: QRectF(r.x() * dpr, r.y() * dpr, r.width() * dpr, r.height() * dpr)  # noqa: E731
        stay, shown = (left, right) if way > 0 else (right, left)
        p.drawPixmap(stay, old, src(stay))
        p.drawPixmap(shown, new, src(shown))
        # sopra: il foglio che gira sul dorso, prima il retro della vecchia, poi il fronte della nuova
        sheet, img, k = (shown, old, 1 - 2 * t) if t < 0.5 else (stay, new, 2 * t - 1)
        w = sheet.width() * k
        dst = QRectF(mid, 0, w, full.height()) if sheet is right else QRectF(mid - w, 0, w, full.height())
        if w > 0.5:
            p.drawPixmap(dst, img, src(sheet))
            self._fold_shadows(p, dst, b, sheet is right, 1 - k)
        p.end()

    @staticmethod
    def _fold_shadows(p: QPainter, sheet: QRectF, book: QRectF, on_right: bool, bend: float) -> None:
        """Ombre del foglio che gira (come StPageFlip e paperflip): più scuro verso la piega,
        un filo di luce sul bordo libero e l'ombra che il foglio getta sulla pagina sotto."""
        sheet = sheet.intersected(book)
        if sheet.width() < 1 or bend <= 0:
            return
        free = sheet.right() if on_right else sheet.left()   # bordo libero del foglio
        spine = sheet.left() if on_right else sheet.right()
        g = QLinearGradient(spine, 0, free, 0)
        g.setColorAt(0, QColor(0, 0, 0, int(25 * bend)))
        g.setColorAt(0.6, QColor(0, 0, 0, int(45 * bend)))
        g.setColorAt(1, QColor(0, 0, 0, int(110 * bend)))
        p.fillRect(sheet, g)
        p.setPen(QPen(QColor(255, 255, 255, int(90 * bend)), 1.2))
        x = free - 1 if on_right else free + 1
        p.drawLine(QPointF(x, sheet.top()), QPointF(x, sheet.bottom()))
        reach = book.width() * 0.08 * bend   # ombra proiettata, oltre il bordo libero
        cast = QRectF(free, sheet.top(), reach, sheet.height()) if on_right \
            else QRectF(free - reach, sheet.top(), reach, sheet.height())
        cast = cast.intersected(book)
        if cast.width() >= 1:
            c = QLinearGradient(free, 0, free + reach if on_right else free - reach, 0)
            c.setColorAt(0, QColor(0, 0, 0, int(120 * bend)))
            c.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(cast, c)

    # ---- mouse
    def mouseMoveEvent(self, e):
        i = self.at(e.position())
        self.setCursor(Qt.PointingHandCursor if i is not None else Qt.ArrowCursor)
        key = self.dlg.photos[i].key if i is not None and i < len(self.dlg.photos) else None
        if key != self._hover_key:
            self._hover_key = key
            if key is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(e.globalPosition().toPoint(),
                                  tr('{v0}\nClic: chiudi l\'album e torna a questa foto', v0=self.dlg.photos[i].main.name), self)

    def leaveEvent(self, e):
        if self._hover_key is not None:
            self._hover_key = None
            QToolTip.hideText()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        i = self.at(e.position())
        if i is not None:
            self.picked.emit(i)
        elif self.book().contains(e.position()):   # clic sulla carta: gira la pagina da quel lato
            self.turn(self.spread + (1 if e.position().x() > self.book().center().x() else -1))

    def wheelEvent(self, e):
        d = e.angleDelta()
        step = d.y() or -d.x()
        if abs(step) >= 60:
            self.turn(self.spread + (1 if step < 0 else -1))


class AlbumDialog(QDialog):
    """Finestra dell'album. opened = chiave della foto cliccata (come il fotolibro)."""
    opened = Signal(str)

    def __init__(self, parent: QWidget, session, photos: list[Page]):
        super().__init__(parent)
        self.setWindowTitle(tr('Album delle foto approvate'))
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowModality(Qt.ApplicationModal)
        self.setStyleSheet(f"QDialog {{ background: {C['bg_window']}; }}")
        self.photos = photos
        self.pages: list[list[int]] = []
        self.places: list[str] = []   # luogo di ogni pagina (vuoto senza GPS)
        self.aspects: list[float] = []
        self.sources: list[str | None] = []
        self.images: LruCache = LruCache(48)
        self._asked: set[int] = set()
        self._pool = ThreadPoolExecutor(2, thread_name_prefix="album")
        self._bridge = _Bridge()
        self._bridge.sized.connect(self._sized)
        self._bridge.loaded.connect(self._loaded)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        head = QHBoxLayout()
        title = QLabel(tr('Album delle foto approvate'))
        title.setStyleSheet(f"color: {C['text_strong']}; font-size: 15px; font-weight: 600;")
        self.where = QLabel()
        self.where.setStyleSheet(f"color: {C['text_2']}; font-size: 13px;")
        close = QPushButton(tr('Chiudi'))
        close.clicked.connect(self.close_album)
        head.addWidget(title)
        head.addSpacing(12)
        head.addWidget(self.where)
        head.addStretch(1)
        head.addWidget(close)
        v.addLayout(head)
        self.view = _Spread(self)
        self.view.picked.connect(self._picked)
        self.view.setAccessibleName(tr('Album delle foto approvate'))
        mid = QHBoxLayout()
        mid.setSpacing(8)
        self.prev = QPushButton("‹")
        self.next = QPushButton("›")
        mid.addWidget(self.prev, 0, Qt.AlignVCenter)
        mid.addWidget(self.view, 1)
        mid.addWidget(self.next, 0, Qt.AlignVCenter)
        v.addLayout(mid, 1)
        for b, way, tip in ((self.prev, -1, tr('Pagina precedente (←)')), (self.next, 1, tr('Pagina successiva (→)'))):
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            b.setFixedSize(52, 52)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ background: {C['bg_control']}; color: {C['text']}; border: none;"
                            f" border-radius: 26px; font-size: 30px; padding-bottom: 4px; }}"
                            f" QPushButton:hover {{ background: {C['bg_hover']}; color: {C['text_strong']}; }}"
                            f" QPushButton:disabled {{ background: transparent; color: {C['bg_hover']}; }}")
            b.setFocusPolicy(Qt.NoFocus)   # le frecce della tastiera restano all'album
            b.clicked.connect(lambda _=False, w=way: self.view.turn(self.view.spread + w))
        hint = QLabel(tr('← → per sfogliare · clic su una foto per tornarci · Esc per chiudere'))
        hint.setStyleSheet(f"color: {C['text_2']}; font-size: 12px;")
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)

        avail = parent.window().geometry() if parent else self.screen().availableGeometry()
        self.resize(max(720, int(avail.width() * 0.9)), max(520, int(avail.height() * 0.9)))
        self.spread_changed()
        self._closing = False
        self._shown_once = False
        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self, duration=180)
        sources = {pg.key: source(session, pg) for pg in photos}
        def prepare(sources=sources):   # in sottofondo: file da mostrare, proporzioni, GPS, pagine e luoghi
            srcs = [sources.get(pg.key) for pg in photos]
            gps = [gps_of(pg) for pg in photos]
            pages = plan(photos, gps)
            return srcs, [aspect(s) for s in srcs], pages, [place_name(gps, idx) for idx in pages]
        fut = self._pool.submit(prepare)
        fut.add_done_callback(lambda f: self._bridge.sized.emit(None if f.exception() else f.result()))

    def showEvent(self, e):
        super().showEvent(e)
        if self._shown_once:
            return
        self._shown_once = True
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        cover = self.view._grab_cover()
        self.view._flip = (cover, cover, 1)   # fino all'apertura si vede il libro chiuso
        QTimer.singleShot(120, self.view.open_book)   # la copertina si apre quando la finestra c'è

    def close_album(self) -> None:
        """Chiusura con garbo: il libro si richiude, poi la finestra sparisce."""
        if self._closing:
            return
        self._closing = True
        self.view.close_book(self._fade_out)

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.close)
        self._fade.start()

    def reject(self):   # Esc (e la chiusura vera, a libro richiuso, passa di qui)
        if self._closing:
            super().reject()
        else:
            self.close_album()

    def spreads(self) -> int:
        return max(1, (len(self.pages) + 1) // 2)

    def spread_changed(self) -> None:
        s, n = self.view.spread, self.spreads()
        self.prev.setEnabled(s > 0)
        self.next.setEnabled(s < n - 1)
        if self.pages:
            last = min(s * 2 + 2, len(self.pages))
            pages = f"{s * 2 + 1}–{last}" if last > s * 2 + 1 else str(s * 2 + 1)
            self.where.setText(tr('Pagine {v0} di {v1}', v0=pages, v1=len(self.pages)))
        self._want(s)

    def _sized(self, res) -> None:
        if res is None:   # qualcosa è andato storto: almeno le pagine per data
            res = [None] * len(self.photos), [4 / 3] * len(self.photos), plan(self.photos), []
        self.sources, self.aspects, self.pages, self.places = res
        self.spread_changed()
        self.view.update()

    def _want(self, spread: int) -> None:
        """Carica le foto di questa doppia pagina e delle due vicine (girando sono già pronte)."""
        if not self.aspects:
            return
        for s in (spread, spread + 1, spread - 1):
            for pg in (s * 2, s * 2 + 1):
                if not (0 <= pg < len(self.pages)):
                    continue
                for i in self.pages[pg]:
                    if i in self.images or i in self._asked:
                        continue
                    self._asked.add(i)
                    fut = self._pool.submit(load, self.sources[i], self.photos[i])
                    fut.add_done_callback(lambda f, i=i: self._bridge.loaded.emit(
                        i, None if f.exception() else f.result()))

    def _loaded(self, i: int, img) -> None:
        self._asked.discard(i)
        if isinstance(img, QImage) and not img.isNull():
            self.images[i] = img
            real = img.width() / img.height()
            if abs(real - self.aspects[i]) > 0.02:   # orientamento letto male: conta la foto vera
                self.aspects[i] = real
            self.view.refresh_flip()
            self.view.update()

    def _picked(self, i: int) -> None:
        self.opened.emit(self.photos[i].key)   # subito: sotto l'album l'app va già a quella foto
        self.close_album()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Right, Qt.Key_PageDown, Qt.Key_Space, Qt.Key_Down):
            self.view.turn(self.view.spread + 1)
        elif k in (Qt.Key_Left, Qt.Key_PageUp, Qt.Key_Backspace, Qt.Key_Up):
            self.view.turn(self.view.spread - 1)
        elif k == Qt.Key_Home:
            self.view.turn(0)
        elif k == Qt.Key_End:
            self.view.turn(self.spreads() - 1)
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        if not self._closing:   # pallino rosso della finestra: prima il libro si richiude
            e.ignore()
            self.close_album()
            return
        self._pool.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(e)
