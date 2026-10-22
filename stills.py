"""Foto pronte da mostrare: le prossime si decodificano in anticipo, fuori dal thread
dell'interfaccia (un panorama da 100 MP richiede secondi), così passando alla foto dopo
l'interfaccia non si blocca. In memoria al massimo MAX_BYTES."""
from __future__ import annotations

from PySide6.QtGui import QImage, QImageReader

from scanner import Item, raw_preview
from widgets import LruCache, pil_to_qimage

AHEAD = 2                   # foto decodificate in anticipo
MAX_BYTES = 400_000_000     # ~ due foto da 50 MP


def decode(item: Item) -> QImage:
    """La foto come si vede (rotazione EXIF compresa); per un DNG senza anteprima per Qt, quella
    incorporata. Nulla se non si apre."""
    reader = QImageReader(str(item.image or item.raw))
    reader.setAutoTransform(True)
    img = reader.read()
    if img.isNull() and item.raw and not item.image:  # solo DNG: Qt non legge i RAW
        pil = raw_preview(item.raw)
        if pil is not None:
            img = pil_to_qimage(pil)
    return img


def _stamp(item: Item):
    try:
        st = item.main.stat()
        return st.st_size, st.st_mtime_ns
    except OSError:
        return None


class Stills:
    def __init__(self):
        self.cache: LruCache = LruCache(AHEAD + 1)
        self.pending: set[str] = set()

    def want(self, item: Item) -> bool:
        """Da decodificare in anticipo? (foto, non già pronta né in corso)"""
        return not item.is_clip and item.id not in self.pending and item.id not in self.cache

    def put(self, item: Item | None, img) -> None:
        if item is None:
            return
        self.pending.discard(item.id)
        if isinstance(img, QImage) and not img.isNull() and img.sizeInBytes() <= MAX_BYTES // 2:
            self.cache[item.id] = (_stamp(item), img)
            while sum(v[1].sizeInBytes() for v in self.cache.values()) > MAX_BYTES:
                self.cache.popitem(last=False)

    def take(self, item: Item) -> QImage:
        """La foto pronta se c'è (e il file non è cambiato), se no si decodifica adesso."""
        hit = self.cache.pop(item.id, None)
        if hit is not None and hit[0] == _stamp(item):
            return hit[1]
        return decode(item)

    def clear(self) -> None:
        self.cache.clear()
        self.pending.clear()
