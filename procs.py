"""Processi figli dell'app (ffmpeg dei fotogrammi, Real-ESRGAN della stampa), da fermare all'uscita."""
from __future__ import annotations

import logging

import frames
import printprep

log = logging.getLogger("photoswipe")


def stop_child_processes() -> None:
    """Ferma i processi figli ancora in corso (ffmpeg dei fotogrammi, Real-ESRGAN della stampa):
    con os._exit resterebbero orfani e potrebbero lasciare file a metà."""
    for name, kill in (("ffmpeg", frames.kill_running),
                       ("stampa", getattr(printprep, "kill_running", lambda: None))):
        try:
            n = kill()
            if n:
                log.info("uscita: fermati %s processi %s", n, name)
        except Exception as e:  # noqa: BLE001 - l'uscita non si blocca per questo
            log.warning("uscita: non riesco a fermare %s: %r", name, e)
