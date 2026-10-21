"""Pannello Info: i testi (HTML) di data, scheda della fotocamera e righe sotto, per un elemento.

Solo testo: i widget restano in app.py, qui si decide cosa mostrare e come."""
from __future__ import annotations

from pathlib import Path

import places
from datefmt import _GIORNI_LUNGHI, _MESI_LUNGHI
from i18n import tr
from theme import COLORS as C

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".dng"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}


def esc(x) -> str:
    """Testo sicuro per l'HTML del pannello; _ e / possono andare a capo (nomi e percorsi lunghi)."""
    return (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>").replace("_", "_​").replace("/", "/​"))


def short_name(name: str, keep: int = 30) -> str:
    """Nome di file lungo accorciato nel mezzo (inizio e fine restano: si riconosce la foto)."""
    if len(name) <= keep:
        return name
    return name[:keep // 2 - 1] + "…" + name[-(keep // 2):]


def details_html(taken, kind_label: str, color: str, status: str, links: list[tuple[str, str]],
                 tz: str = "") -> str:
    """In alto: giorno; ora, tipo e fuso; poi lo stato dei file con un puntino del colore della scelta."""
    link_html = "".join(f" · <a style='color:{C['link']}' href='{url}'>{label}</a>" for label, url in links)
    head, _, rest = status.partition(" · ")
    rest = f"<div style='color:{C['text_2']}; margin-left:14px; margin-top:2px'>{esc(rest)}</div>" if rest else ""
    t = taken
    when = "  ·  ".join(x for x in (f"{t:%H:%M:%S}", kind_label.capitalize(), tz) if x)
    return (f"<div style='font-size:17px; font-weight:600; color:{C['text']}'>"
            f"{_GIORNI_LUNGHI[t.weekday()]} {t.day} {_MESI_LUNGHI[t.month - 1]} {t.year}</div>"
            f"<div style='color:{C['text_2']}; margin-top:4px'>{when}</div>"
            f"<div style='margin-top:12px'><span style='color:{color}'>●</span> "
            f"<span style='color:{C['text_detail']}; font-weight:600'>{esc(head[:1].upper() + head[1:])}</span>"
            f"{link_html}</div>{rest}")


def card_html(m, extra: list[str], burst_html) -> str:
    """Scheda grigia: fotocamera, obiettivo, misure, scatto e qualità (come l'Info di Foto)."""
    rows = dict(m.rows) if m else {}
    card = []
    if rows.get(tr('Fotocamera')):
        card.append(f"<div style='color:{C['text']}; font-size:13px; font-weight:600'>{esc(rows[tr('Fotocamera')])}</div>")
    if rows.get(tr('Obiettivo')):
        card.append(f"<div style='color:{C['text_detail']}'>{esc(rows[tr('Obiettivo')])}</div>")
    size = rows.get(tr('Video')) or rows.get(tr('Dimensioni'))
    if size:
        size = size.replace("  (", "  ·  ").rstrip(")")   # "1728 × 3072  ·  5.3 MP"
        files = rows.get(tr('File'), "").split("\n")
        if len(files) == 1 and "  ·  " in files[0]:
            size += "  ·  " + files[0].partition("  ·  ")[2]   # un solo file: il peso va accanto ai MP
        card.append(f"<div style='color:{C['text_detail']}; margin-top:6px'>{esc(size)}</div>")
    tech = [rows[k] for k in (tr('Scatto'), tr('Durata'), tr('Bitrate'), tr('Audio')) if rows.get(k)]
    if tech:
        card.append(f"<div style='color:{C['text_2']}; margin-top:6px; font-size:12px'>"
                    + esc("  ·  ".join(tech)) + "</div>")
    if m and m.quality:
        card.append(m.quality.info_html() + burst_html())
    if not m and extra:
        card.append(f"<div style='color:{C['text_2']}; font-size:12px'>" + esc("  ·  ".join(extra)) + "</div>")
    return "".join(card)


def more_html(m, extra: list[str], warn: list[str], short_folder, favorite: bool) -> str:
    """Sotto la scheda, in piccolo: luogo, file, cartella, note e avvisi."""
    rows = dict(m.rows) if m else {}
    more = []
    if m:   # anche senza GPS: "Luogo non registrato"
        more.append(places.info_html(m, C['text_detail'], C['link'], esc))
    if rows.get(tr('File')):
        names = []
        for line in rows[tr('File')].split("\n"):
            name, _, size = line.partition("  ·  ")
            single = "\n" not in rows[tr('File')]   # il peso di un file solo è già nella scheda
            names.append(short_name(name) + (f"  ·  {size}" if size and not single else ""))
        more.append(f"<div style='color:{C['text_2']}'>{esc(chr(10).join(names))}</div>")
    if rows.get(tr('Cartella')):
        folder = esc(short_folder(rows[tr('Cartella')]).replace("/", " › ").replace("\\", " › "))
        more.append(f"<div style='color:{C['text_2']}; margin-top:2px'>{folder}</div>")
    small = [(k, v) for k, v in rows.items() if k == tr('Colore')]   # il fuso è in alto, accanto all'ora
    small += [(tr('Nota'), x) for x in extra if x.startswith("anteprima")]
    if favorite:
        small.append((tr('Preferita'), "♥"))
    if small:
        more.append(f"<div style='color:{C['text_2']}; margin-top:2px'>"
                    + "  ·  ".join(f"{esc(k)} {esc(v)}" for k, v in small) + "</div>")
    if warn:
        more.append(f"<div style='color:{C['text_warn']}; margin-top:6px'>" + "<br>".join(map(esc, warn)) + "</div>")
    return "".join(more)

def open_links(files: list[str]) -> list[tuple[str, str]]:
    """Un link per la prima foto e uno per il primo video tra i file indicati."""
    links = []
    for exts, label in ((IMAGE_EXTS, tr('Apri foto')), (VIDEO_EXTS, tr('Apri video'))):
        f = next((f for f in files if Path(f).suffix.lower() in exts and Path(f).exists()), None)
        if f:
            links.append((label, f))
    return links
