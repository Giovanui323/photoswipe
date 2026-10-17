"""File su iCloud Drive (o OneDrive su Windows) non ancora scaricati: rilevamento e download."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("photoswipe")

# Velocità misurate dei download iCloud (MB/s): servono per stimare la percentuale,
# perché macOS consegna il file tutto insieme e non dice quanto manca.
speed_samples: list[float] = []
DEFAULT_SPEED_MBS = 1.5


def estimated_speed() -> float:
    recent = sorted(speed_samples[-8:])
    return recent[len(recent) // 2] if recent else DEFAULT_SPEED_MBS

SF_DATALESS = 0x40000000                       # macOS: file presente solo nel cloud
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000      # Windows: file "solo online"
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000


def stub_for(path: Path) -> Path:
    """Vecchio formato iCloud: 'foto.jpg' diventa '.foto.jpg.icloud'."""
    return path.with_name(f".{path.name}.icloud")


def real_name_of_stub(name: str) -> str | None:
    if name.startswith(".") and name.endswith(".icloud"):
        return name[1:-len(".icloud")]
    return None


def is_local(path: Path) -> bool:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False  # esiste solo lo stub .icloud
    if sys.platform == "darwin":
        return not (getattr(st, "st_flags", 0) & SF_DATALESS)
    if sys.platform == "win32":
        attrs = getattr(st, "st_file_attributes", 0)
        return not (attrs & (FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS))
    return True


def download(path: Path, timeout: float = 900) -> bool:
    """Scarica il file se serve. Blocca finché è disponibile in locale (da usare in un thread).

    Leggere il file ne forza il download ed è risultato ~2 volte più veloce di 'brctl download'.
    'brctl' resta per i vecchi stub '.nome.icloud', dove il file vero non esiste ancora.
    """
    if is_local(path):
        return True
    t0 = time.monotonic()
    log.info("iCloud: inizio download %s", path)
    if path.exists():
        try:
            with open(path, "rb") as f:
                while f.read(8 * 1024 * 1024):
                    pass
            mb, secs = path.stat().st_size / 1e6, time.monotonic() - t0
            if mb > 3 and secs > 0.5:
                speed_samples.append(mb / secs)
            log.info("iCloud: scaricato %s (%.1f MB) in %.1f s", path.name, mb, secs)
            return True
        except OSError as e:
            log.warning("iCloud: lettura di %s non riuscita (%s), provo brctl", path.name, e)
    if sys.platform == "darwin":
        try:
            subprocess.run(["brctl", "download", str(path)], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if is_local(path):
                log.info("iCloud: scaricato con brctl %s in %.1f s", path.name, time.monotonic() - t0)
                return True
            time.sleep(0.3)
    ok = is_local(path)
    if not ok:
        log.error("iCloud: download NON riuscito %s dopo %.0f s", path, time.monotonic() - t0)
    return ok
