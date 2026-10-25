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


def snap_html(rows: list[tuple[str, str]]) -> str:
    """Tabella dei metadati e stampabilità per una foto estratta da un video."""
    plain = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    out = []
    for k, v in rows:
        hot = k == tr('Stampabilità')
        vs = f"<span style='color:{C['text_ok']}; font-weight:700'>{plain(v)}</span>" if hot else plain(v)
        out.append(f"<tr><td width='78' style='color:{C['text_2']}; padding:3px 10px 3px 0; vertical-align:top'>"
                   f"{plain(k)}</td><td style='color:{C['text']}; padding:3px 0'>{vs}</td></tr>")
    return "<table cellspacing='0'>" + "".join(out) + "</table>"


def file_status(d: dict | None, choice_color: dict[str, str]) -> tuple[str, str, list[tuple[str, str]]]:
    """Cosa è successo ai file dell'elemento: (colore, testo, link 'Apri …')."""
    if not d:
        return C["text_2"], tr('da decidere · niente copiato né spostato'), []
    choice = d["choice"]
    if choice == "no":
        return choice_color["no"], tr("✗ scartata · niente copiato, l'originale resta al suo posto"), []
    if choice == "skip":
        return choice_color["skip"], tr('↪ saltata · niente copiato né spostato'), []
    if choice == "trash":
        moved = [dst for _, dst in d.get("moved", [])]
        return (choice_color["trash"], tr('🗑 originale SPOSTATO in “cancellare” (Z lo rimette a posto)'),
                open_links(moved))
    if choice == "yes" and d.get("noexport"):
        return choice_color["yes"], tr('✓ approvata · video non copiato (tenute solo le foto prese)'), []
    if d.get("export_failed"):
        return (C["text_warn"],
                tr('⚠ copia non riuscita: {v0}\n(si riprova alla prossima apertura)', v0=d['export_failed']), [])
    files = d.get("files") or []
    if not files:
        return C["text_warn"], tr('⏳ copia in export in corso…'), []
    return (choice_color["yes"], tr("✓ approvata · COPIATA in export (l'originale resta al suo posto)"),
            open_links(files))


def save_info_html(ses, short_folder, short_path, export_dir) -> tuple[str, str]:
    """Testo HTML e tooltip per lo stato del salvataggio automatico."""
    from datetime import date
    saved = ses.path.exists()
    when = ses.updated[11:19] if saved and len(ses.updated) >= 19 else ""
    day = ses.updated[:10] if saved else ""
    if saved and day != date.today().isoformat():
        when = f"{day[8:10]}/{day[5:7]} {when}"
    state = (tr("<span style='color:{c}'>✓ Salvato alle {when}</span>", c=C["text_ok"], when=when) if saved else
             tr("<span style='color:{c}'>Non ancora salvato</span>", c=C["text_warn"]))
    where = short_folder(str(ses.path.parent))
    tip = tr('Si salva da solo a ogni scelta: puoi chiudere quando vuoi e riprendere da qui.\n'
             'Progressi: {v1}/{v2}\nFoto scelte: {v3}',
             v1=where, v2=ses.path.name, v3=short_path(export_dir))
    return state, tip


def done_html(done: int, total: int) -> str:
    """Riga di avanzamento nella sidebar ('X di Y già fatte · ne mancano Z')."""
    rest = (f"<span style='font-size:12px; color:{C['text_2']};'>"
            + tr('  ·  ne mancano {n}', n=total - done) + "</span>"
            if done < total else
            f"<span style='font-size:12px; color:{C['yes']};'>" + tr('  ·  tutte decise') + "</span>")
    return tr("<span style='font-size:13px; font-weight:600; color:{c};'>{done} di {v1} già fatte</span>",
              c=C["text"], done=done, v1=total) + rest


def counter_text(c: dict, busy: int, hidden: int) -> str:
    """Riepilogo compatto delle scelte nella sidebar."""
    extra = tr('   ⏳ export {busy}', busy=busy) if busy else ""
    if hidden:
        extra += tr('   ({hidden} nascosti dal filtro)', hidden=hidden)
    return (tr('{v2} approvate · {v3} scartate · {v4} saltate', v2=c['yes'], v3=c['no'], v4=c['skip'])
            + (tr(' · {v0} in “cancellare”', v0=c['trash']) if c.get("trash") else "")
            + (tr(' · {v0} dai video', v0=c['snap']) if c.get("snap") else "")
            + (f"\n{extra.strip()}" if extra else ""))


def end_summary_text(c: dict, hidden: int, left: int) -> str:
    """Testo di riepilogo a fine cartella."""
    rest = tr('manca 1 elemento') if left == 1 else tr('mancano {n} elementi', n=left)
    head = tr('Sei in fondo, ma {rest} da decidere più indietro.', rest=rest) if left else tr('Finito!')
    counts = tr('✓ {yes} approvate    ✗ {no} scartate    ↪ {skip} saltate',
                yes=c['yes'], no=c['no'], skip=c['skip'])
    return (f"{head}\n\n{counts}"
            + (tr('\n\n🎬 {hidden} nascosti dal filtro attivo', hidden=hidden) if hidden else "")
            + tr('\n\n← = torna indietro a rivedere'))


def download_message_text(dl_files: list[Path], elapsed: float, speed: float, prefetch: int) -> str:
    """Testo di avanzamento durante il download da iCloud."""
    secs = int(elapsed)
    names = "\n".join(f"{p.name}  ·  {p.stat().st_size / 1e6:.0f} MB" if p.exists() else p.name
                      for p in dl_files)
    dots = "." * (secs % 4)
    total_mb = sum(p.stat().st_size for p in dl_files if p.exists()) / 1e6
    expected = max(1.0, total_mb / speed + 2)
    pct = min(95, int(100 * elapsed / expected))
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    left = max(0, int(expected - elapsed))
    eta = tr('circa {left} s rimanenti', left=left) if left else tr('quasi finito…')
    return tr('☁️  Scarico da iCloud{dots}\n\n{names}\n\n{bar}  ≈ {pct}%\n⏱  {secs} s  ·  {eta}   '
              '(stima su {speed:.1f} MB/s)\nmacOS non dice la percentuale vera: la stima usa la velocità '
              'dei download già fatti.\nI prossimi {PREFETCH} elementi si stanno già scaricando in automatico.\n\n'
              'Intanto puoi premere  S = salta,  N = no,  X = sposta in “cancellare”.',
              dots=dots, names=names, bar=bar, pct=pct, secs=secs, eta=eta, speed=speed, PREFETCH=prefetch)


def saved_work_detail(info: dict, fmt_when) -> str:
    """Dettaglio per il dialogo di ripresa sessione."""
    c = info["counts"]
    total = info["total"] or "?"
    return (tr('Decise: {v0} su {v1}\n', v0=info['decided'], v1=total)
            + tr('✓ {v0} approvate   ✗ {v1} scartate   ↪ {v2} saltate', v0=c['yes'], v1=c['no'], v2=c['skip'])
            + (tr('   🗑 {v0} in “cancellare”', v0=c['trash']) if c.get("trash") else "")
            + (tr('   📷 {v0} foto da video', v0=c['snap']) if c.get("snap") else "")
            + tr('\n\nIniziato il {v0}\nUltima modifica il {v1}\nExport: {v2}',
                 v0=fmt_when(info['created']), v1=fmt_when(info['updated']), v2=info['export'])
            + ("" if info.get("export_ok", True) else
               tr("\n(questa cartella export non c'è su questo computer: riprendendo ti chiedo dove copiare)")))
