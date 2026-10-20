"""Coda delle miniature della striscia in basso: una coda tutta sua, non dietro l'analisi.

- si chiedono dal centro verso i bordi: la miniatura accanto a quella che guardi arriva prima
- quelle uscite dalla striscia (sei andato altrove) si tolgono dalla coda prima di partire
- una miniatura non riuscita si riprova, qualche volta e non subito
"""
from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable


class ThumbQueue:
    TRIES = 3        # tentativi per miniatura, poi resta il nome del file
    RETRY_S = 5.0    # attesa tra un tentativo e il successivo

    def __init__(self, workers: int = 2):
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.futs: dict[str, Future] = {}               # chieste e non ancora arrivate
        self.fails: dict[str, tuple[int, float]] = {}   # id -> (tentativi falliti, quando l'ultimo)

    def can_try(self, key: str) -> bool:
        if key in self.futs:
            return False
        n, t = self.fails.get(key, (0, 0.0))
        return n < self.TRIES and (n == 0 or time.monotonic() - t >= self.RETRY_S)

    def sync(self, wanted: list[str], submit: Callable[[str], Future]) -> None:
        """wanted: le miniature che servono, già in ordine dal centro verso i bordi.
        Toglie dalla coda quelle che non servono più e chiede quelle nuove."""
        keep = set(wanted)
        for k, f in list(self.futs.items()):
            if k not in keep and f.cancel():   # non ancora partita: non serve più
                del self.futs[k]
        for k in wanted:
            if self.can_try(k):
                self.futs[k] = submit(k)

    def arrived(self, key: str, ok: bool) -> None:
        self.futs.pop(key, None)
        if ok:
            self.fails.pop(key, None)
        else:
            n, _ = self.fails.get(key, (0, 0.0))
            self.fails[key] = (n + 1, time.monotonic())

    def gave_up(self, key: str) -> bool:
        return self.fails.get(key, (0, 0.0))[0] >= self.TRIES

    def clear(self) -> None:
        """Altra cartella: le richieste di prima non valgono più."""
        for f in self.futs.values():
            f.cancel()
        self.futs.clear()
        self.fails.clear()
