"""Raffiche: foto quasi uguali scattate una dopo l'altra. Per il Sì / No conta sapere se questa è
la più nitida del gruppo o se ce n'è una migliore poco più avanti (o indietro)."""
from __future__ import annotations

from datetime import timedelta

from i18n import tr

GAP = timedelta(seconds=30)   # due foto della stessa raffica sono a meno di 30 s l'una dall'altra
DIST = 12                     # bit diversi su 64 nell'impronta: fino a qui sono "quasi uguali"
RADIUS = 6                    # vicini da guardare per parte (e di cui leggere i metadati)


def neighbors(items, idx: int) -> list[int]:
    """Indici vicini di cui serve la qualità per riconoscere la raffica attorno a idx."""
    return [i for i in range(max(0, idx - RADIUS), min(len(items), idx + RADIUS + 1)) if i != idx]


def _close(a, qa, b, qb) -> bool:
    return (qa is not None and qb is not None and abs(a.taken - b.taken) <= GAP
            and bin(qa.dhash ^ qb.dhash).count("1") <= DIST)


def burst(items, idx: int, quality_of) -> list[int]:
    """Indici (in ordine) della raffica che contiene idx; [idx] se la foto non ha simili.
    quality_of(item) dà la Quality già letta, o None (non ancora letta, video, file su iCloud)."""
    members = [idx]
    for step in (-1, 1):
        i = idx
        while 0 <= i + step < len(items) and abs(i + step - idx) <= RADIUS \
                and _close(items[i], quality_of(items[i]), items[i + step], quality_of(items[i + step])):
            i += step
            members.append(i)
    return sorted(members)


def info_html(items, idx: int, quality_of) -> str:
    """Riga per il pannello Info, o "" se la foto non fa parte di una raffica."""
    members = burst(items, idx, quality_of)
    if len(members) < 2:
        return ""
    best = max(members, key=lambda i: quality_of(items[i]).sharpness)
    pos = members.index(idx) + 1
    if best == idx:
        text, color = tr('{v0} foto simili: questa ({v1}ª) è la più nitida', v0=len(members), v1=pos), "#30d158"
    else:
        text = tr('{v0} foto simili: la più nitida è la {v1}ª ({v2}), questa è la {v3}ª',
                  v0=len(members), v1=members.index(best) + 1, v2=f"{items[best].taken:%H:%M:%S}", v3=pos)
        color = "#ffb340"
    return f"<div style='color:{color}; margin-top:4px; font-size:12px'>{text}</div>"
