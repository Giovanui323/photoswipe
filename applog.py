"""Log su file: ~/Library/Logs/PhotoSwipe/photoswipe.log (macOS) o accanto all'utente su altri sistemi."""
from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


def log_path() -> Path:
    override = os.environ.get("PHOTOSWIPE_LOG_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs" / "PhotoSwipe"
    else:
        base = Path.home() / ".photoswipe"
    base.mkdir(parents=True, exist_ok=True)
    return base / "photoswipe.log"


def setup(version: str) -> logging.Logger:
    log = logging.getLogger("photoswipe")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    try:
        h = RotatingFileHandler(log_path(), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s [%(threadName)s] %(message)s"))
        log.addHandler(h)
    except OSError:
        pass
    log.info("==== avvio %s | Python %s | %s", version, sys.version.split()[0], sys.platform)

    def hook(exc_type, exc, tb):
        log.error("ERRORE NON GESTITO", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = hook
    threading.excepthook = lambda a: log.error("ERRORE nel thread %s", a.thread.name if a.thread else "?",
                                               exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return log
