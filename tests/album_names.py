"""Nome atteso nell'album, calcolato a parte (non con exporter.dated): una sola data davanti,
la data DJI scritta nel nome originale (DJI_20260730132210_0002_D) tolta."""
import re


def nodate(name: str) -> str:
    return re.sub(r"_(?:19|20)\d{12}(?=_|\.)", "", name)
