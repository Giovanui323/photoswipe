"""Qualità di una foto, come aiuto per il Sì / No: nitidezza ed esposizione.

Si guarda una copia ridotta in grigi (veloce, anche per foto da 50 MP). La nitidezza è quella del
riquadro più nitido: un soggetto a fuoco con lo sfondo sfocato (ritratti, bokeh) resta "nitida"."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from i18n import tr

SIDE = 1024        # lato lungo della copia analizzata: le soglie sono tarate su questa misura
GRID = 6           # riquadri per lato: si prende il più nitido
# Soglie della nitidezza (log10 della varianza del laplaciano), tarate su 200 foto di build/train:
# nitide ≥ 3,2 (5° percentile); sfocate di 1 px ≈ 2,5; sfocate di 2 px ≤ 1,6 (95° percentile).
SHARP = 2.7
SOFT = 1.6
CLIP = 0.02        # oltre il 2% di pixel bruciati (o chiusi) l'esposizione merita un avviso


@dataclass
class Quality:
    sharpness: float      # log10 della varianza del laplaciano nel riquadro più nitido
    highlights: float     # frazione di pixel bruciati (≥ 250)
    shadows: float        # frazione di pixel chiusi (≤ 5)
    dhash: int = 0        # impronta a 64 bit (dHash): foto quasi uguali hanno impronte vicine

    @property
    def focus(self) -> str:
        if self.sharpness >= SHARP:
            return "sharp"
        return "soft" if self.sharpness >= SOFT else "blurry"

    def summary(self) -> tuple[str, bool]:
        """(testo per il pannello Info, True se c'è qualcosa che non va)."""
        parts = [{"sharp": tr('Nitida'), "soft": tr('Poco nitida'), "blurry": tr('Sfocata')}[self.focus]]
        if self.highlights > CLIP:
            parts.append(tr('alte luci bruciate {v0}%', v0=round(self.highlights * 100)))
        if self.shadows > CLIP:
            parts.append(tr('ombre chiuse {v0}%', v0=round(self.shadows * 100)))
        bad = self.focus != "sharp" or len(parts) > 1
        if len(parts) == 1:
            parts.append(tr('esposizione buona'))
        return "  ·  ".join(parts), bad

    def info_html(self) -> str:
        """Riga per la scheda del pannello Info: verde se va tutto bene, arancione se no."""
        text, bad = self.summary()
        color = "#ffb340" if bad else "#30d158"
        return (f"<div style='color:{color}; margin-top:8px; font-size:12px'>"
                f"{tr('Qualità')}: {text}</div>")


def _gray(img: Image.Image) -> np.ndarray:
    g = img.convert("L")
    if max(g.size) > SIDE:
        g.thumbnail((SIDE, SIDE), Image.Resampling.BILINEAR)
    return np.asarray(g, np.float32)


def sharpness(gray: np.ndarray) -> float:
    lap = (gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4 * gray[1:-1, 1:-1])
    h, w = lap.shape
    best = 0.0
    for i in range(GRID):
        for j in range(GRID):
            tile = lap[i * h // GRID:(i + 1) * h // GRID, j * w // GRID:(j + 1) * w // GRID]
            if tile.size:
                best = max(best, float(tile.var()))
    return float(np.log10(best + 1.0))


def dhash(gray: np.ndarray) -> int:
    """Impronta per riconoscere le foto simili: ogni bit dice se un punto è più chiaro del vicino."""
    small = np.asarray(Image.fromarray(gray.astype(np.uint8)).resize((9, 8), Image.Resampling.BILINEAR),
                       np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def assess(img: Image.Image) -> Quality:
    gray = _gray(img)
    return Quality(sharpness(gray), float((gray >= 250).mean()), float((gray <= 5).mean()), dhash(gray))


def assess_file(path: Path) -> Quality | None:
    """Qualità della foto sul disco (JPEG, PNG, HEIC, panorami, DNG), o None se non si legge."""
    import edits
    from scanner import raw_preview
    try:
        if path.suffix.lower() == ".dng":
            img = raw_preview(path)
            return assess(img) if img is not None else None
        edits.register_heif()
        with edits.open_unbounded(path) as im:
            im.draft("L", (SIDE, SIDE))   # JPEG: si decodifica già ridotta, molto più veloce
            return assess(im)
    except Exception:  # noqa: BLE001 - formato non leggibile: niente giudizio, non è un errore
        return None
