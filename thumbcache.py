"""Miniature della striscia in basso: come si fanno, e una cache su disco così, riaprendo la
cartella, sono già pronte invece di rileggere ogni HEIC o video."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader

import cloud
import frames
from scanner import Item, raw_preview
from widgets import ThumbStrip, pil_to_qimage

MAX_FILES = 20000   # ~15 KB l'una: la cache resta sotto i 300 MB


def cache_dir() -> Path:
    return Path(os.environ.get("PHOTOSWIPE_THUMB_CACHE") or Path.home() / "Library/Caches/PhotoSwipe/thumbs")


def _cache_path(item: Item) -> Path | None:
    """Il file della miniatura in cache: cambia se cambia il file (dimensione o data di modifica)."""
    try:
        st = item.main.stat()
    except OSError:
        return None
    raw = f"{item.main.resolve()}|{st.st_size}|{st.st_mtime_ns}|{ThumbStrip.THUMB_SIDE}"
    key = hashlib.sha1(raw.encode()).hexdigest()
    return cache_dir() / key[:2] / f"{key}.jpg"


def cached_thumb(item: Item) -> QImage:
    """La miniatura dalla cache, oppure fatta ora e messa in cache."""
    path = _cache_path(item)
    if path is not None and path.exists():
        img = QImage(str(path))
        if not img.isNull():
            try:
                os.utime(path)   # usata adesso: la pulizia toglie prima le altre
            except OSError:
                pass
            return img
    img = make_thumb(item)
    if path is not None and not img.isNull():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".jpg")
            os.close(fd)
            if img.save(tmp, "JPG", 88):
                os.replace(tmp, path)   # mai un file a metà in cache
            else:
                os.unlink(tmp)
        except OSError:
            pass   # disco pieno o cartella non scrivibile: la miniatura c'è lo stesso
    return img


def prune(max_files: int = MAX_FILES) -> None:
    """Toglie le miniature usate meno di recente quando la cache ne ha troppe."""
    try:
        files = [(p.stat().st_mtime, p) for p in cache_dir().glob("*/*.jpg")]
    except OSError:
        return
    if len(files) <= max_files:
        return
    files.sort()
    for _, p in files[:len(files) - max_files]:
        try:
            p.unlink()
        except OSError:
            pass


def make_thumb(item: Item) -> QImage:
    if item.is_clip:
        if item.screennail and cloud.is_local(item.screennail):
            img = QImageReader(str(item.screennail)).read()
            if not img.isNull():
                return img
        src = item.proxy if item.proxy and cloud.is_local(item.proxy) else item.video
        ims = frames.strip_thumbs(src, frames.probe(src), count=1, height=208)
        return pil_to_qimage(ims[0]) if ims else QImage()
    # la miniatura deve RIEMPIRE la casella (ritaglio centrale) senza essere ingrandita, anche
    # su Retina: il lato corto arriva a THUMB_SIDE. Quadrato, così vale anche per le foto
    # ruotate dall'EXIF (la misura si sceglie prima della rotazione) e per i panorami.
    side = ThumbStrip.THUMB_SIDE
    r = QImageReader(str(item.image or item.raw))
    r.setAutoTransform(True)
    size = r.size()
    if size.isValid() and min(size.width(), size.height()) > side:
        r.setScaledSize(size.scaled(side, side, Qt.KeepAspectRatioByExpanding))
    img = r.read()
    if img.isNull() and item.raw:
        pil = raw_preview(item.raw)
        if pil is not None:
            k = side / min(pil.size)
            if k < 1:
                pil.thumbnail((max(1, round(pil.width * k)), max(1, round(pil.height * k))))
            img = pil_to_qimage(pil)
    return img
