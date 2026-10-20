"""Lavori di Regola / Ritaglia che girano fuori dalla finestra: anteprima, foto intera, stampa."""
import inspect

import edits as E
import printprep

EDIT_PROXY = 1600          # Regola / Ritaglia: anteprima veloce, poi la foto intera
EDIT_FULL_MAX = 30_000_000  # oltre (panorami enormi) a schermo resta l'anteprima; l'export è sempre intero


def print_takes_edit() -> bool:
    """printprep.improve accetta le modifiche (parametro edit)? Le versioni vecchie no."""
    try:
        return "edit" in inspect.signature(printprep.improve).parameters
    except (TypeError, ValueError):
        return False


def render_edit_job(img, e: dict, crop_mode: bool):
    """In Ritaglia si vede la foto intera (raddrizzata) con il riquadro sopra; altrimenti finita."""
    if crop_mode:
        base = E.geometry_base(img.convert("RGB"), e)
        return E.render_tone(base, uncropped_tone_edit(e, *base.size))
    return E.render(img, e)


def uncropped_tone_edit(e: dict, w: int, h: int) -> dict:
    """Le regolazioni per la foto intera (Ritaglia mostra tutto, con il riquadro sopra).
    Gli occhi rossi sono segnati nel riquadro di quel momento: si riportano sulla foto intera,
    nello stesso posto e della stessa misura in cui finiranno nella foto ritagliata."""
    t = dict(e)
    t.pop("crop", None)
    pts = e.get("redeye") or []
    if pts:
        c = e.get("crop") or [0.0, 0.0, 1.0, 1.0]
        k = max(c[2] * w, c[3] * h) / max(1, w, h)   # misura relativa al lato lungo del ritaglio
        flip = 1.0 if e.get("flip") else 0.0
        t["redeye"] = []
        for p in pts:
            x, y = E.redeye_point(p, e)          # nel riquadro di adesso
            size = p[2] if len(p) > 2 else E.get(e, "redeye_size")
            t["redeye"].append([c[0] + x * c[2], c[1] + y * c[3], size * k,
                                flip, 0.0, 0.0, 1.0, 1.0])
    return t
