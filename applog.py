"""Log su file con rotazione: ~/Library/Logs/PhotoSwipe/photoswipe.log (macOS) o ~/.photoswipe/photoswipe.log (Windows/altri)."""
from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler sicuro che non crasha su Windows se il file di log è aperto in lettura."""

    def doRollover(self):
        try:
            super().doRollover()
        except (PermissionError, OSError):
            # Su Windows se il file è correntemente aperto (es. Blocco Note), non interrompe l'app
            pass


def log_path() -> Path:
    override = os.environ.get("PHOTOSWIPE_LOG_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs" / "PhotoSwipe"
    else:
        # Su Windows e Linux usa ~/.photoswipe
        base = Path.home() / ".photoswipe"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return base / "photoswipe.log"


def reveal_log() -> None:
    """Apre la cartella dei log evidenziando il file di log su macOS (Finder) o Windows (Esplora File)."""
    import subprocess
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
    except OSError:
        pass

    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform == "win32":
        try:
            # Su Windows explorer /select,percorso evidenzia il file nella cartella
            subprocess.Popen(["explorer", f"/select,{path}"])
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def setup(version: str) -> logging.Logger:
    log = logging.getLogger("photoswipe")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    try:
        # Dimensione massima 1.5 MB per file, 2 backup: al massimo ~4.5 MB in totale
        h = SafeRotatingFileHandler(log_path(), maxBytes=1_500_000, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)-5s [%(threadName)s] %(message)s",
                                         datefmt="%Y-%m-%d %H:%M:%S"))
        log.addHandler(h)
    except OSError:
        pass

    sys_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
    log.info("==== avvio %s | Python %s | %s | %s ====", version, sys.version.split()[0], sys.platform, sys_info)

    # Intercetta eccezioni non gestite nel MainThread
    def hook(exc_type, exc, tb):
        log.critical("ERRORE NON GESTITO (MainThread): %s: %s", exc_type.__name__, exc, exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = hook

    # Intercetta eccezioni non gestite nei thread di background
    def thread_hook(args):
        tname = args.thread.name if args.thread else "?"
        log.critical("ERRORE nel thread [%s]: %s: %s", tname, args.exc_type.__name__, args.exc_value,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = thread_hook

    # Intercetta avvisi ed errori critici di Qt/PySide6
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType

        def qt_msg_handler(msg_type, context, message):
            if msg_type == QtMsgType.QtFatalMsg:
                log.critical("Qt FATAL: %s", message)
            elif msg_type == QtMsgType.QtCriticalMsg:
                log.error("Qt CRITICAL: %s", message)
            elif msg_type == QtMsgType.QtWarningMsg:
                # Ignora warning grafici innocui e frequenti
                if not any(ign in message for ign in ("QPainter", "libpng", "iCCP", "skipping QEvent")):
                    log.warning("Qt: %s", message)

        qInstallMessageHandler(qt_msg_handler)
    except Exception:
        pass

    return log
