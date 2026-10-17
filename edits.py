"""Regola e Ritaglia (come in Foto di macOS): le modifiche di una foto e il loro calcolo.

Una modifica è un dizionario semplice (salvato nella sessione): solo i valori diversi da quelli
predefiniti. Lo stesso calcolo serve per l'anteprima (foto ridotta) e per l'export (piena
risoluzione): i raggi di sfocatura e nitidezza sono in proporzione alla misura della foto.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

# valore predefinito di ogni regolazione (tutte da -1 a 1 o da 0 a 1, salvo dove indicato)
DEFAULTS: dict[str, float] = {
    # Luce
    "light": 0.0, "brilliance": 0.0, "exposure": 0.0, "highlights": 0.0, "shadows": 0.0,
    "brightness": 0.0, "contrast": 0.0, "blackpoint": 0.0,
    # Colore
    "color": 0.0, "saturation": 0.0, "vibrance": 0.0, "cast": 0.0,
    # Bianco e nero (attivo solo se "bw" è nelle sezioni accese)
    "bw": 0.0, "bw_intensity": 0.0, "bw_neutrals": 0.0, "bw_tone": 0.0, "bw_grain": 0.0,
    # Bilanciamento del bianco
    "wb_temp": 0.0, "wb_tint": 0.0,
    # Curve (spostamento dei 5 punti)
    "curve_blacks": 0.0, "curve_shadows": 0.0, "curve_mid": 0.0, "curve_high": 0.0, "curve_whites": 0.0,
    # Livelli
    "lv_black": 0.0, "lv_gamma": 0.0, "lv_white": 1.0, "lv_out_black": 0.0, "lv_out_white": 1.0,
    # Definizione, riduzione disturbo, nitidezza, vignettatura, occhi rossi
    "definition": 0.0, "noise": 0.0,
    "deblur": 0.0, "deblur_radius": 0.3,   # Sfocatura: deconvoluzione Richardson-Lucy
    "sharp_amount": 0.0, "sharp_edges": 0.5, "sharp_falloff": 0.5,
    "vig_amount": 0.0, "vig_radius": 0.5, "vig_soft": 0.5,
    "redeye_size": 0.04,
    # Ritaglia
    "straighten": 0.0,   # gradi, da -45 a 45
    "vertical": 0.0, "horizontal": 0.0,   # prospettiva, da -1 a 1
}
SEL_HUES = ("red", "yellow", "green", "cyan", "blue", "magenta")   # Colore selettivo
SEL_NAMES = {"red": "Rosso", "yellow": "Giallo", "green": "Verde", "cyan": "Ciano", "blue": "Blu",
             "magenta": "Magenta"}
SEL_COLORS = {"red": "#ff453a", "yellow": "#ffd60a", "green": "#32d74b", "cyan": "#64d2ff",
              "blue": "#0a84ff", "magenta": "#bf5af2"}
for _h in SEL_HUES:
    for _p in ("h", "s", "l"):
        DEFAULTS[f"sel_{_h}_{_p}"] = 0.0

# sezioni del pannello Regola e le chiavi che appartengono a ciascuna
SECTIONS: dict[str, tuple[str, ...]] = {
    "light": ("light", "brilliance", "exposure", "highlights", "shadows", "brightness", "contrast", "blackpoint"),
    "color": ("color", "saturation", "vibrance", "cast"),
    "bw": ("bw", "bw_intensity", "bw_neutrals", "bw_tone", "bw_grain"),
    "redeye": ("redeye_size",),
    "wb": ("wb_temp", "wb_tint"),
    "curves": ("curve_blacks", "curve_shadows", "curve_mid", "curve_high", "curve_whites"),
    "levels": ("lv_black", "lv_gamma", "lv_white", "lv_out_black", "lv_out_white"),
    "definition": ("definition",),
    "selective": tuple(f"sel_{h}_{p}" for h in SEL_HUES for p in ("h", "s", "l")),
    "noise": ("noise",),
    "deblur": ("deblur", "deblur_radius"),
    "sharpen": ("sharp_amount", "sharp_edges", "sharp_falloff"),
    "vignette": ("vig_amount", "vig_radius", "vig_soft"),
}
GEOMETRY_KEYS = ("straighten", "vertical", "horizontal", "flip", "crop", "aspect")

# Proporzioni di Ritaglia: (nome, lato corto : lato lungo) — None = libera / originale
ASPECTS: list[tuple[str, str, float | None]] = [
    ("original", "Originale", None), ("free", "Forma libera", None), ("square", "Quadrato", 1.0),
    ("16:9", "16:9", 9 / 16), ("4:5", "4:5", 4 / 5), ("5:7", "5:7", 5 / 7), ("4:3", "4:3", 3 / 4),
    ("3:5", "3:5", 3 / 5), ("3:2", "3:2", 2 / 3), ("custom", "Personalizzato", None),
]


# ----------------------------------------------------------------------------- modello
def get(e: dict, key: str) -> float:
    return float(e.get(key, DEFAULTS.get(key, 0.0)))


def clean(e: dict) -> dict:
    """Toglie i valori uguali ai predefiniti: una modifica vuota è {}."""
    out = {}
    for k, v in e.items():
        if k in DEFAULTS:
            if abs(float(v) - DEFAULTS[k]) > 1e-6:
                out[k] = round(float(v), 5)
        elif k == "off":
            if v:
                out[k] = sorted(set(v))
        elif k == "bw_on":
            if v:
                out[k] = True
        elif k == "flip":
            if v:
                out[k] = True
        elif k == "crop":
            if v and not _full_crop(v):
                out[k] = [round(float(x), 6) for x in v]
        elif k == "aspect":
            if v and v != "free":
                out[k] = v
        elif k == "aspect_custom":
            if v:
                out[k] = [int(v[0]), int(v[1])]
        elif k == "aspect_portrait":
            if v is not None:
                out[k] = bool(v)
        elif k == "redeye":
            if v:
                out[k] = [[round(float(a), 5) for a in p] for p in v]
    if "aspect" not in out:
        out.pop("aspect_custom", None)
        out.pop("aspect_portrait", None)
    if "bw_on" not in out:
        for k in SECTIONS["bw"]:
            out.pop(k, None)
    return out


def _full_crop(c) -> bool:
    return abs(c[0]) < 1e-4 and abs(c[1]) < 1e-4 and abs(c[2] - 1) < 1e-4 and abs(c[3] - 1) < 1e-4


def is_empty(e: dict | None) -> bool:
    return not e or not clean(e)


def section_modified(e: dict, sec: str) -> bool:
    if sec == "bw":
        return bool(e.get("bw_on"))
    if sec == "redeye":
        return bool(e.get("redeye"))
    return any(abs(get(e, k) - DEFAULTS[k]) > 1e-6 for k in SECTIONS[sec])


def section_on(e: dict, sec: str) -> bool:
    return section_modified(e, sec) and sec not in e.get("off", [])


def has_geometry(e: dict | None) -> bool:
    e = e or {}
    return bool(e.get("flip") or e.get("crop") or abs(get(e, "straighten")) > 1e-6
                or abs(get(e, "vertical")) > 1e-6 or abs(get(e, "horizontal")) > 1e-6)


def has_tone(e: dict | None) -> bool:
    e = e or {}
    return any(section_on(e, s) for s in SECTIONS)


def aspect_ratio(e: dict, w: int, h: int) -> float | None:
    """Rapporto larghezza/altezza imposto da Proporzioni (None = libero)."""
    key = e.get("aspect", "free")
    if key == "original":
        return w / h if h else None
    if key == "custom":
        a, b = e.get("aspect_custom") or [1, 1]
        r = max(a, 1) / max(b, 1)
        return r
    for k, _name, short_long in ASPECTS:
        if k == key and short_long:
            portrait = e.get("aspect_portrait")
            if portrait is None:
                portrait = h > w
            return short_long if portrait else 1 / short_long
    return None


def fit_aspect(crop: list[float] | None, ratio: float | None, w: int, h: int) -> list[float]:
    """Il riquadro più grande con quel rapporto, centrato nel ritaglio attuale (o nella foto)."""
    x, y, cw, ch = crop or [0.0, 0.0, 1.0, 1.0]
    if not ratio:
        return [x, y, cw, ch]
    pw, ph = cw * w, ch * h
    if pw / ph > ratio:
        nw, nh = ph * ratio, ph
    else:
        nw, nh = pw, pw / ratio
    cx, cy = (x + cw / 2) * w, (y + ch / 2) * h
    return [(cx - nw / 2) / w, (cy - nh / 2) / h, nw / w, nh / h]


# ----------------------------------------------------------------------------- geometria
def _perspective_coeffs(src_quad, w: int, h: int):
    """Coefficienti per Image.transform(PERSPECTIVE): il rettangolo d'uscita w×h prende i pixel
    dal quadrilatero src_quad (alto-sx, alto-dx, basso-dx, basso-sx) della foto di partenza."""
    dst = [(0, 0), (w, 0), (w, h), (0, h)]
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src_quad):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return np.linalg.solve(np.array(a, float), np.array(b, float)).tolist()


def straighten_scale(angle_deg: float, w: int, h: int) -> float:
    """Quanto si riduce il riquadro (stesse proporzioni) per stare dentro la foto ruotata."""
    t = math.radians(abs(angle_deg))
    c, s = math.cos(t), math.sin(t)
    return min(w / (w * c + h * s), h / (w * s + h * c))


def geometry_base(img: Image.Image, e: dict) -> Image.Image:
    """Capovolgi, prospettiva e raddrizza (senza il ritaglio dell'utente). Il risultato non ha
    mai angoli vuoti: come in Foto, la foto si ingrandisce quanto basta."""
    if e.get("flip"):
        img = ImageOps.mirror(img)
    v, hz = get(e, "vertical"), get(e, "horizontal")
    if abs(v) > 1e-6 or abs(hz) > 1e-6:
        w, h = img.size
        dv, dh = abs(v) * 0.22 * w, abs(hz) * 0.22 * h
        tl, tr, br, bl = [0.0, 0.0], [w, 0.0], [w, h], [0.0, h]
        if v > 0:      # linee verticali che convergono in alto: si allarga la parte alta
            tl[0] += dv; tr[0] -= dv
        elif v < 0:
            bl[0] += dv; br[0] -= dv
        if hz > 0:
            tr[1] += dh; br[1] -= dh
        elif hz < 0:
            tl[1] += dh; bl[1] -= dh
        img = img.transform((w, h), Image.PERSPECTIVE, _perspective_coeffs([tl, tr, br, bl], w, h),
                            Image.BICUBIC)
    a = get(e, "straighten")
    if abs(a) > 1e-6:
        w, h = img.size
        k = straighten_scale(a, w, h)
        rot = img.rotate(-a, resample=Image.BICUBIC, expand=False)
        nw, nh = max(1, int(w * k)), max(1, int(h * k))
        left, top = (w - nw) // 2, (h - nh) // 2
        img = rot.crop((left, top, left + nw, top + nh))
    return img


def apply_crop(img: Image.Image, e: dict) -> Image.Image:
    c = e.get("crop")
    if not c:
        return img
    w, h = img.size
    x0, y0 = round(c[0] * w), round(c[1] * h)
    x1, y1 = round((c[0] + c[2]) * w), round((c[1] + c[3]) * h)
    x0, y0 = max(0, min(w - 1, x0)), max(0, min(h - 1, y0))
    x1, y1 = max(x0 + 1, min(w, x1)), max(y0 + 1, min(h, y1))
    return img.crop((x0, y0, x1, y1))


# ----------------------------------------------------------------------------- toni e colore
def _smooth(a, b, x):
    t = np.clip((x - a) / max(b - a, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def _lum(x):
    return x[..., 0] * 0.2126 + x[..., 1] * 0.7152 + x[..., 2] * 0.0722


def _blur1(ch: np.ndarray, radius: float) -> np.ndarray:
    """Sfocatura gaussiana di un canale float. Raggi piccoli: convoluzione separabile esatta;
    raggi grandi: si riduce, si sfoca e si riporta su (molto più veloce, stesso aspetto)."""
    if radius > 4:
        k = radius / 3
        h, w = ch.shape
        small = Image.fromarray(ch).resize((max(1, round(w / k)), max(1, round(h / k))), Image.BOX)
        sm = _blur1(np.asarray(small, np.float32), 3.0)
        return np.asarray(Image.fromarray(sm).resize((w, h), Image.BILINEAR), np.float32)
    n = max(1, int(radius * 3))
    t = np.arange(-n, n + 1, dtype=np.float32)
    ker = np.exp(-(t * t) / (2 * radius * radius))
    ker /= ker.sum()
    p = np.pad(ch, n, mode="edge")
    out = np.zeros((p.shape[0], ch.shape[1]), np.float32)
    for i, kv in enumerate(ker):
        out += p[:, i:i + ch.shape[1]] * kv
    res = np.zeros_like(ch)
    for i, kv in enumerate(ker):
        res += out[i:i + ch.shape[0], :] * kv
    return res


def _blur(x: np.ndarray, radius: float) -> np.ndarray:
    """Sfocatura gaussiana di un'immagine float 0..1 (un canale o RGB)."""
    if radius <= 0.05:
        return x
    if x.ndim == 2:
        return _blur1(x, radius)
    return np.stack([_blur1(np.ascontiguousarray(x[..., i]), radius) for i in range(x.shape[2])], -1)


def _rgb_to_hsv(x):
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    mx, mn = x.max(-1), x.min(-1)
    d = mx - mn
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    dd = np.maximum(d, 1e-6)
    h = np.where(mx == r, ((g - b) / dd) % 6, np.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4)) / 6
    h = np.where(d > 1e-6, h, 0)
    return h, s, mx


def _hsv_to_rgb(h, s, v):
    h6 = (h % 1.0) * 6
    i = np.floor(h6).astype(np.int32) % 6
    f = h6 - np.floor(h6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def _curve_lut(e: dict) -> np.ndarray:
    xs = np.array([0, .25, .5, .75, 1.0])
    ys = xs + np.array([get(e, "curve_blacks"), get(e, "curve_shadows"), get(e, "curve_mid"),
                        get(e, "curve_high"), get(e, "curve_whites")]) * 0.25
    ys = np.clip(ys, 0, 1)
    t = np.linspace(0, 1, 1024)
    # Catmull-Rom tra i punti: curva morbida come in Foto
    p = np.concatenate([[2 * ys[0] - ys[1]], ys, [2 * ys[-1] - ys[-2]]])
    seg = np.minimum((t * 4).astype(int), 3)
    u = t * 4 - seg
    p0, p1, p2, p3 = p[seg], p[seg + 1], p[seg + 2], p[seg + 3]
    lut = 0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u ** 2
                 + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)
    return np.maximum.accumulate(np.clip(lut, 0, 1)).astype(np.float32)


def _light(x, e):
    m = get(e, "light")
    br = get(e, "brilliance") + m * 0.25
    expo = get(e, "exposure") + m * 0.55
    hi = get(e, "highlights") - br * 0.35 - max(m, 0) * 0.2
    sh = get(e, "shadows") + br * 0.45 + m * 0.25
    bright = get(e, "brightness") + m * 0.25
    con = get(e, "contrast") + br * 0.1
    bp = get(e, "blackpoint") + max(m, 0) * 0.05
    if abs(expo) > 1e-6:
        x = np.clip(x, 0, None) ** 2.2 * (2 ** (expo * 1.6))
        x = np.clip(x, 0, 1) ** (1 / 2.2)
    if abs(hi) > 1e-6 or abs(sh) > 1e-6:
        L = _lum(x)[..., None]
        if abs(hi) > 1e-6:
            mask = _smooth(0.45, 1.0, L)
            x = x + (hi * 0.45 * x if hi < 0 else hi * 0.35 * (1 - x)) * mask
        if abs(sh) > 1e-6:
            mask = 1 - _smooth(0.0, 0.55, L)
            x = x + (sh * 0.5 * (1 - x) if sh > 0 else sh * 0.5 * x) * mask
        x = np.clip(x, 0, 1)
    if abs(bright) > 1e-6:
        x = np.clip(x, 0, 1) ** (2 ** (-bright * 0.7))
    if abs(con) > 1e-6:
        x = np.clip(x, 0, 1)
        if con > 0:
            x = x + (x * x * (3 - 2 * x) - x) * min(con, 1) * 1.2
        else:
            x = x + (0.5 - x) * (-con) * 0.5
    if abs(bp) > 1e-6:
        k = abs(bp) * 0.15
        x = (x - k) / (1 - k) if bp > 0 else x * (1 - k) + k
    return np.clip(x, 0, 1)


def _color(x, e):
    m = get(e, "color")
    sat = get(e, "saturation") + m
    vib = get(e, "vibrance") + m * 0.4
    cast = get(e, "cast")
    if abs(sat) > 1e-6:
        L = _lum(x)[..., None]
        x = L + (x - L) * max(0.0, 1 + sat)
    if abs(vib) > 1e-6:
        L = _lum(x)[..., None]
        s = (x.max(-1) - x.min(-1))[..., None]
        x = L + (x - L) * np.maximum(0, 1 + vib * 1.3 * (1 - np.clip(s, 0, 1)))
    if abs(cast) > 1e-6:
        x = x * np.array([1 + cast * 0.07, 1.0, 1 - cast * 0.07], np.float32)
    return np.clip(x, 0, 1)


def _wb(x, e):
    t, g = get(e, "wb_temp"), get(e, "wb_tint")
    return np.clip(x * np.array([1 + t * 0.18, 1 - g * 0.14, 1 - t * 0.18], np.float32), 0, 1)


def _levels(x, e):
    ib, iw = get(e, "lv_black"), get(e, "lv_white")
    iw = max(iw, ib + 0.02)
    x = np.clip((x - ib) / (iw - ib), 0, 1) ** (2 ** (-get(e, "lv_gamma")))
    ob, ow = get(e, "lv_out_black"), get(e, "lv_out_white")
    return ob + x * (ow - ob)


def _selective(x, e):
    h, s, v = _rgb_to_hsv(x)
    for i, name in enumerate(SEL_HUES):
        dh, ds, dl = (get(e, f"sel_{name}_{p}") for p in ("h", "s", "l"))
        if abs(dh) < 1e-6 and abs(ds) < 1e-6 and abs(dl) < 1e-6:
            continue
        d = np.abs(((h - i / 6) + 0.5) % 1.0 - 0.5)
        w = np.clip(1 - d * 6, 0, 1) * np.clip(s * 3, 0, 1)
        h = h + w * dh / 12
        s = np.clip(s * (1 + w * ds), 0, 1)
        v = np.clip(v * (1 + w * dl * 0.5), 0, 1)
    return _hsv_to_rgb(h, s, v)


def _bw(x, e, scale: float):
    m = get(e, "bw")   # come il filtro colorato davanti all'obiettivo: + rosso, − blu
    wts = np.array([0.30 + 0.25 * max(m, 0), 0.59 - 0.1 * abs(m), 0.11 + 0.25 * max(-m, 0)], np.float32)
    g = (x * (wts / wts.sum())).sum(-1)
    inten = get(e, "bw_intensity")
    if abs(inten) > 1e-6:
        g = np.clip(g + (g * g * (3 - 2 * g) - g) * inten * 1.2, 0, 1)
    neu = get(e, "bw_neutrals")
    if abs(neu) > 1e-6:
        g = np.clip(g, 0, 1) ** (2 ** (-neu * 0.6))
    out = np.repeat(g[..., None], 3, -1)
    tone = get(e, "bw_tone")
    if abs(tone) > 1e-6:   # + seppia, − freddo
        tint = np.array([1.0, 0.85, 0.62] if tone > 0 else [0.75, 0.88, 1.0], np.float32)
        out = out * (1 + (tint - 1) * abs(tone))
    grain = get(e, "bw_grain")
    if grain > 1e-6:
        rng = np.random.default_rng(7)
        noise = rng.standard_normal(g.shape).astype(np.float32)
        out = out + noise[..., None] * grain * 0.08
    return np.clip(out, 0, 1)


def _redeye(x, e):
    pts = e.get("redeye") or []
    if not pts:
        return x
    hgt, wid = x.shape[:2]
    yy, xx = np.mgrid[0:hgt, 0:wid].astype(np.float32)
    for p in pts:
        cx, cy = p[0] * wid, p[1] * hgt
        r = (p[2] if len(p) > 2 else get(e, "redeye_size")) * max(wid, hgt)
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(r, 1)
        mask = np.clip(1.3 - d, 0, 1)
        rch, gch, bch = x[..., 0], x[..., 1], x[..., 2]
        red = np.clip((rch - np.maximum(gch, bch)) * 3, 0, 1) * mask
        x[..., 0] = rch * (1 - red) + ((gch + bch) / 2) * red
    return x


def deblur_sigma(radius: float) -> float:
    """Raggio di Sfocatura (0..1) → sfocatura in pixel di una foto da 2000 px."""
    return 0.6 + 3.4 * radius


def _deblur(x: np.ndarray, amount: float, sigma: float, iters: int = 12) -> np.ndarray:
    """Richardson-Lucy con una sfocatura gaussiana (come restoration.richardson_lucy di
    scikit-image), sulla sola luminanza: ridà i contorni senza aloni colorati. Il rapporto
    è limitato a ogni passo, così il rumore e gli aloni non esplodono."""
    if amount <= 1e-6 or sigma < 0.3:
        return x
    L = np.clip(_lum(x), 1e-3, 1)
    est = L.copy()
    for _ in range(iters):
        conv = np.maximum(_blur(est, sigma), 1e-3)
        est = est * _blur(np.clip(L / conv, 0.5, 2.0), sigma)
    detail = np.clip(est - L, -0.25, 0.25) * amount
    return np.clip(x + detail[..., None], 0, 1)


def render_tone(img: Image.Image, e: dict) -> Image.Image:
    """Tutte le regolazioni di Regola, nell'ordine di Foto."""
    if not has_tone(e):
        return img
    on = lambda s: section_on(e, s)   # noqa: E731
    x = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    x = x.copy()
    scale = max(img.size) / 2000.0   # raggi in proporzione: anteprima e export si somigliano
    if on("redeye"):
        x = _redeye(x, e)
    if on("wb"):
        x = _wb(x, e)
    if on("levels"):
        x = _levels(x, e)
    if on("light"):
        x = _light(x, e)
    if on("curves"):
        lut = _curve_lut(e)
        x = lut[np.clip((x * 1023).astype(np.int32), 0, 1023)]
    if on("color"):
        x = _color(x, e)
    if on("selective"):
        x = _selective(x, e)
    if on("bw"):
        x = _bw(x, e, scale)
    if on("definition"):
        d = get(e, "definition")
        L = _lum(x)
        bl = _blur(L, 20 * scale + 1)
        x = np.clip(x + (L - bl)[..., None] * d * 1.2, 0, 1)
    if on("noise"):
        n = get(e, "noise")
        x = x + (_blur(x, (0.8 + 1.6 * n) * scale + 0.3) - x) * min(1.0, n * 1.1)
    if on("deblur"):
        x = _deblur(x, get(e, "deblur"), deblur_sigma(get(e, "deblur_radius")) * scale)
    if on("sharpen"):
        a = get(e, "sharp_amount")
        radius = (0.6 + 2.0 * get(e, "sharp_falloff")) * max(scale, 0.25)
        L = _lum(x)
        detail = L - _blur(L, radius)
        thr = (1 - get(e, "sharp_edges")) * 0.03
        detail = np.where(np.abs(detail) > thr, detail, detail * 0.2)
        x = np.clip(x + detail[..., None] * a * 2.0, 0, 1)
    if on("vignette"):
        v, r, s = get(e, "vig_amount"), get(e, "vig_radius"), get(e, "vig_soft")
        hgt, wid = x.shape[:2]
        yy, xx = np.ogrid[0:hgt, 0:wid]
        d = np.sqrt(((xx - wid / 2) / (wid / 2)) ** 2 + ((yy - hgt / 2) / (hgt / 2)) ** 2) / math.sqrt(2)
        r_in = 0.15 + 0.6 * r - s * 0.25
        mask = _smooth(r_in, r_in + 0.15 + s * 0.6, d)[..., None].astype(np.float32)
        x = x * (1 - v * mask * 0.85) if v > 0 else x + (1 - x) * (-v) * mask * 0.85
    return Image.fromarray(np.clip(x * 255 + 0.5, 0, 255).astype(np.uint8))


def render(img: Image.Image, e: dict | None, crop: bool = True) -> Image.Image:
    """Foto finita: geometria, ritaglio (se crop) e regolazioni."""
    e = e or {}
    if is_empty(e):
        return img
    img = img.convert("RGB")
    img = geometry_base(img, e)
    if crop:
        img = apply_crop(img, e)
    return render_tone(img, e)


# ----------------------------------------------------------------------------- automatico
# Solo numpy (gira uguale su macOS e Windows). Idee prese da strumenti open source:
# bilanciamento del bianco "Shades of Gray" + "Gray Edge" (Finlayson 2004, van de Weijer 2007),
# livelli con 0,2% di pixel tagliati (come le miniature di RawTherapee), esposizione sulla
# media logaritmica della luminanza (chiave 0,18, Reinhard), raddrizza e prospettiva dalle
# linee dritte trovate con la trasformata di Hough (come ShiftN / darktable "rotate and perspective").
def _small(img: Image.Image, side: int = 320) -> np.ndarray:
    k = side / max(img.size)
    im = img.convert("RGB")
    if k < 1:
        im = im.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.BILINEAR)
    return np.asarray(im, np.float32) / 255


def _lin(x):
    return np.clip(x, 0, 1) ** 2.2


def auto_light(img: Image.Image) -> dict:
    """Luce automatica: punto di nero, luci e ombre secondo i pixel che si perdono, poi
    l'esposizione cercata (sulla foto già corretta) finché la media logaritmica è a 0,18."""
    x = _small(img, 260)
    L = _lum(x)
    lo = float(np.percentile(L, 0.2))
    out: dict[str, float] = {}
    if lo > 0.05 and float(np.median(L)) > 0.3:   # neri slavati (nebbia); non se è solo scura
        out["blackpoint"] = float(np.clip((lo - 0.03) * 0.7 / 0.15, 0, 0.45))
    hi_frac = float((L > 0.94).mean())
    if hi_frac > 0.01:   # cielo / luci bruciate: si recuperano
        out["highlights"] = float(-np.clip(0.15 + hi_frac * 4, 0, 0.7))
    dark_frac = float((L < 0.12).mean())
    if dark_frac > 0.08:
        out["shadows"] = float(np.clip((dark_frac - 0.04) * 1.6, 0, 0.6))
    sd = float(L.std())
    if sd < 0.18:   # foto piatta
        out["contrast"] = float(np.clip((0.2 - sd) * 2.5, 0, 0.35))

    def key(e: float) -> float:
        y = _light(x.copy(), {**out, "exposure": e})
        return float(np.exp(np.log(_lin(_lum(y)) + 1e-4).mean()))
    lo_e, hi_e = -1.0, 1.0
    if key(0.0) > 0.18:
        hi_e = 0.0
    else:
        lo_e = 0.0
    for _ in range(9):   # bisezione: la luminosità sale con l'esposizione
        mid = (lo_e + hi_e) / 2
        if key(mid) < 0.18:
            lo_e = mid
        else:
            hi_e = mid
    e = (lo_e + hi_e) / 2 * 0.9   # un filo prudente, come Foto
    # non bruciare: al massimo l'1,5% di pixel bianchi in più
    while e > 0.05 and float((_lum(_light(x.copy(), {**out, "exposure": e})) > 0.985).mean()) > \
            float((L > 0.985).mean()) + 0.015:
        e -= 0.05
    if abs(e) > 0.03:
        out["exposure"] = float(e)
    return out


def auto_color(img: Image.Image) -> dict:
    """Vividezza secondo quanto è già satura la foto (non tocca i colori già forti)."""
    x = _small(img, 200)
    mx, mn = x.max(-1), x.min(-1)
    s = (mx - mn) / np.maximum(mx, 1e-3)
    w = np.clip(mx * 2, 0, 1)   # i pixel quasi neri non contano
    sat = float((s * w).sum() / max(w.sum(), 1e-6))
    out = {}
    v = float(np.clip((0.42 - sat) * 1.3, 0, 0.45))
    if v > 0.03:
        out["vibrance"] = v
    if sat > 0.7:   # già molto carica
        out["saturation"] = float(-np.clip((sat - 0.7) * 1.5, 0, 0.25))
    return out


def _illuminant(x: np.ndarray) -> np.ndarray:
    """Colore della luce (lineare): Shades of Gray (p=6) e Gray Edge insieme."""
    lin = _lin(x)
    L = _lum(x)
    ok = (x.max(-1) < 0.97) & (L > 0.04)   # niente pixel bruciati o neri
    if ok.sum() < 100:
        ok = np.ones_like(L, bool)
    p = 6
    sog = np.array([np.mean(lin[..., c][ok] ** p) ** (1 / p) for c in range(3)])
    sm = _blur(lin, 1.0)
    gy, gx = np.gradient(sm, axis=(0, 1))
    mag = np.hypot(gx, gy)
    ge = np.array([np.mean(mag[..., c][ok] ** p) ** (1 / p) for c in range(3)])
    if sog.sum() < 1e-9:
        return np.full(3, 1 / 3)
    est = sog / sog.sum()
    if ge.sum() > 1e-6:   # foto tutta piatta: senza bordi vale solo Shades of Gray
        est = np.sqrt(est * ge / ge.sum())
    return est / est.sum()


def auto_wb(img: Image.Image, strength: float = 0.85) -> dict:
    """Bilanciamento del bianco: si toglie la dominante della luce (lasciandone un filo, come
    Foto, perché un tramonto resti caldo)."""
    e = _illuminant(_small(img, 320))
    g_lin = e.mean() / np.maximum(e, 1e-6)
    g = g_lin ** (1 / 2.2)   # in gamma, come i guadagni di _wb
    g = 1 + (g - 1) * strength
    q = g[0] / g[2]
    temp = (q - 1) / (0.18 * (q + 1))
    rel_g = g[1] / ((g[0] + g[2]) / 2)
    tint = (1 - rel_g) / 0.14
    out = {}
    if abs(temp) > 0.02:
        out["wb_temp"] = float(np.clip(temp, -1, 1))
    if abs(tint) > 0.02:
        out["wb_tint"] = float(np.clip(tint, -1, 1))
    return out


def auto_levels(img: Image.Image) -> dict:
    """Livelli: 0,2% di pixel tagliati in basso e in alto (come RawTherapee)."""
    L = _lum(_small(img, 260))
    lo, hi = np.percentile(L, [0.2, 99.8])
    out = {}
    if lo > 0.01:
        out["lv_black"] = float(np.clip(lo, 0, 0.3))
    if hi < 0.99:
        out["lv_white"] = float(np.clip(hi, 0.85, 1.0))
    mid = float(np.median(np.clip((L - lo) / max(hi - lo, 1e-3), 0, 1)))
    if 0.05 < mid < 0.95:   # mezzitoni verso 0,45
        g = math.log(0.45) / math.log(mid)
        gamma = -math.log2(g) * 0.6
        if abs(gamma) > 0.03:
            out["lv_gamma"] = float(np.clip(gamma, -0.6, 0.6))
    return out


def auto_sharpen(img: Image.Image) -> dict:
    """Nitidezza: di più se la foto è morbida (poca energia nei dettagli fini)."""
    L = _lum(_small(img, 900))
    detail = float(np.abs(L - _blur(L, 1.2)).mean())
    return {"sharp_amount": float(np.clip(0.55 - detail * 25, 0.15, 0.5))}


def auto_noise(img: Image.Image) -> dict:
    """Riduzione disturbo: stima del rumore nelle zone piatte (mediana dei dettagli)."""
    L = _lum(_small(img, 900))
    sigma = float(np.median(np.abs(L - _blur(L, 1.0)))) * 1.4826
    return {"noise": float(np.clip((sigma - 0.004) * 30, 0, 0.6))}


def auto_definition(img: Image.Image) -> dict:
    L = _lum(_small(img, 400))
    local = float(np.abs(L - _blur(L, 12)).mean())
    return {"definition": float(np.clip(0.45 - local * 4, 0.1, 0.4))}


# --- linee dritte (Hough), per Raddrizza e Prospettiva automatici
def find_lines(img: Image.Image, side: int = 640, families: tuple[str, ...] = ("h", "v"),
               span: float = 20.0) -> list[tuple[str, float, float, float, int, int]]:
    """Linee lunghe e dritte quasi orizzontali (h) o verticali (v).

    Ritorna (famiglia, inclinazione in gradi, rho, voti, larghezza, altezza): l'inclinazione è
    l'angolo della linea rispetto all'orizzontale (h) o alla verticale (v), positiva in senso orario."""
    g = img.convert("L")
    k = side / max(g.size)
    if k < 1:
        g = g.resize((max(1, round(g.width * k)), max(1, round(g.height * k))), Image.BILINEAR)
    a = _blur(np.asarray(g, np.float32) / 255, 1.2)
    hgt, wid = a.shape
    gy, gx = np.gradient(a)
    mag = np.hypot(gx, gy)
    thr = max(float(np.percentile(mag, 93)), 0.02)
    # solo i massimi lungo il gradiente (bordi sottili, come Canny)
    ang = np.arctan2(gy, gx)
    dx = np.rint(np.cos(ang)).astype(int)
    dy = np.rint(np.sin(ang)).astype(int)
    yy, xx = np.mgrid[0:hgt, 0:wid]
    n1 = mag[np.clip(yy + dy, 0, hgt - 1), np.clip(xx + dx, 0, wid - 1)]
    n2 = mag[np.clip(yy - dy, 0, hgt - 1), np.clip(xx - dx, 0, wid - 1)]
    edge = (mag > thr) & (mag >= n1) & (mag >= n2)
    edge[:3, :] = edge[-3:, :] = edge[:, :3] = edge[:, -3:] = False
    ys, xs = np.nonzero(edge)
    if len(xs) < 30:
        return []
    if len(xs) > 40000:
        sel = np.random.default_rng(0).choice(len(xs), 40000, replace=False)
        ys, xs = ys[sel], xs[sel]
    gang = np.degrees(ang[ys, xs])   # direzione del gradiente = normale alla linea
    out = []
    step = 0.1
    tilts = np.arange(-span, span + step / 2, step)
    diag = int(math.hypot(wid, hgt)) + 2
    min_votes = max(25, int(0.12 * min(wid, hgt)))
    for fam in families:
        # normale della linea: h → circa 90°, v → circa 0°
        base = 90.0 if fam == "h" else 0.0
        normals = base + tilts
        # ogni punto vota solo le inclinazioni vicine alla sua (±2°): veloce e senza falsi
        dev = ((gang - base + 90) % 180) - 90
        keep = np.abs(dev) <= span + 2
        px, py, pd = xs[keep], ys[keep], dev[keep]
        if len(px) < 20:
            continue
        acc = np.zeros((len(tilts), 2 * diag), np.int32)
        for off in np.arange(-2.0, 2.0 + step / 2, step):
            ti = np.rint((pd + off + span) / step).astype(int)
            ok = (ti >= 0) & (ti < len(tilts))
            th = np.radians(normals[ti[ok]])
            rho = np.rint(px[ok] * np.cos(th) + py[ok] * np.sin(th)).astype(int) + diag
            np.add.at(acc, (ti[ok], rho), 1)
        # i picchi, togliendo ogni volta i dintorni
        for _ in range(12):
            i = int(acc.argmax())
            ti, ri = divmod(i, acc.shape[1])
            votes = int(acc[ti, ri])
            if votes < min_votes:
                break
            out.append((fam, float(tilts[ti]), float(ri - diag), float(votes), wid, hgt))
            acc[max(0, ti - 30):ti + 31, max(0, ri - 8):ri + 9] = 0
    return out


def _weighted_median(vals, weights) -> float:
    o = np.argsort(vals)
    v, w = np.asarray(vals)[o], np.asarray(weights, float)[o]
    c = np.cumsum(w)
    return float(v[np.searchsorted(c, c[-1] / 2)])


def auto_straighten(img: Image.Image) -> float:
    """Gradi per Raddrizza: mediana pesata dell'inclinazione delle linee lunghe orizzontali
    (orizzonte, mensole) e verticali (pareti, pali). 0 se non c'è nulla di affidabile."""
    lines = find_lines(img, families=("h", "v"), span=15)
    if not lines:
        return 0.0
    tilt = [t for _f, t, *_r in lines]
    w = [v * (1.0 if f == "h" else 0.7) for f, _t, _r, v, *_ in lines]   # l'orizzonte conta di più
    med = _weighted_median(tilt, w)
    near = [(t, ww) for t, ww in zip(tilt, w) if abs(t - med) < 1.5]
    if sum(ww for _t, ww in near) < 0.35 * sum(w):   # linee in disaccordo: meglio non toccare
        return 0.0
    ang = sum(t * ww for t, ww in near) / sum(ww for _t, ww in near)
    # segno: una linea che scende verso destra (tilt > 0) si corregge girando in senso antiorario
    return 0.0 if abs(ang) < 0.2 else round(float(-ang), 1)


def _persp_matrix(e: dict, w: int, h: int) -> np.ndarray:
    """Matrice 3×3 di geometry_base per la prospettiva: punto d'uscita → punto della foto."""
    v, hz = get(e, "vertical"), get(e, "horizontal")
    dv, dh = abs(v) * 0.22 * w, abs(hz) * 0.22 * h
    tl, tr, br, bl = [0.0, 0.0], [w, 0.0], [w, h], [0.0, h]
    if v > 0:
        tl[0] += dv; tr[0] -= dv
    elif v < 0:
        bl[0] += dv; br[0] -= dv
    if hz > 0:
        tr[1] += dh; br[1] -= dh
    elif hz < 0:
        tl[1] += dh; bl[1] -= dh
    c = _perspective_coeffs([tl, tr, br, bl], w, h)
    return np.array([[c[0], c[1], c[2]], [c[3], c[4], c[5]], [c[6], c[7], 1.0]])


def auto_perspective(img: Image.Image) -> dict:
    """Verticale (e Orizzontale) automatici: il valore che rende parallele le linee che
    convergono (palazzi visti dal basso). Solo se le linee sono abbastanza e d'accordo."""
    lines = find_lines(img, families=("v",), span=20)
    if len(lines) < 3:
        return {}
    wid, hgt = lines[0][4], lines[0][5]
    segs = []   # due punti per ogni linea (in alto e in basso)
    for _f, tilt, rho, votes, *_ in lines:
        th = math.radians(tilt)   # normale della linea
        c, s = math.cos(th), math.sin(th)
        if abs(c) < 1e-6:
            continue
        p = [((rho - y * s) / c, y) for y in (0.0, float(hgt))]
        segs.append((p, votes))
    xs_spread = [abs(p[0][0] - p[1][0]) for p, _v in segs]
    if not segs or max(xs_spread) < 1.0:
        return {}

    def cost(v: float) -> float:
        m = np.linalg.inv(_persp_matrix({"vertical": v}, wid, hgt))   # foto → uscita
        tot = 0.0
        for p, votes in segs:
            q = []
            for x, y in p:
                u = m @ np.array([x, y, 1.0])
                q.append((u[0] / u[2], u[1] / u[2]))
            ang = math.degrees(math.atan2(q[1][0] - q[0][0], q[1][1] - q[0][1]))
            tot += votes * min(ang * ang, 100.0)
        return tot

    grid = np.linspace(-1, 1, 81)
    costs = [cost(v) for v in grid]
    best = float(grid[int(np.argmin(costs))])
    if abs(best) < 0.05 or costs[int(np.argmin(costs))] > 0.6 * cost(0.0):
        return {}   # niente di convincente: si lascia com'è
    return {"vertical": round(float(np.clip(best, -0.8, 0.8)), 3)}


# ----------------------------------------------------------------------------- export
def load_full(path: Path) -> tuple[Image.Image, dict]:
    """Originale a piena risoluzione, già girato secondo l'EXIF; e cosa conservare nel file."""
    keep: dict = {}
    try:
        im = Image.open(path)
        im.load()
        exif = im.getexif()
        keep["icc_profile"] = im.info.get("icc_profile")
        im = ImageOps.exif_transpose(im)
        if exif:
            exif[0x0112] = 1   # già girata
            keep["exif"] = exif.tobytes()
        return im.convert("RGB"), keep
    except Exception:  # noqa: BLE001 - es. HEIC: lo legge Qt (macOS)
        from PySide6.QtGui import QImage, QImageReader
        r = QImageReader(str(path))
        r.setAutoTransform(True)
        q = r.read()
        if q.isNull():
            raise
        q = q.convertToFormat(QImage.Format_RGB888)
        arr = np.frombuffer(q.constBits(), np.uint8, q.sizeInBytes()).reshape(q.height(), q.bytesPerLine())
        arr = arr[:, :q.width() * 3].reshape(q.height(), q.width(), 3)
        return Image.fromarray(arr.copy()), keep


def save_edited(img: Image.Image, dst: Path, keep: dict) -> None:
    import os
    tmp = dst.with_name(dst.name + ".part")
    kw = {k: v for k, v in keep.items() if v}
    img.save(tmp, "JPEG", quality=100, subsampling=0, optimize=True, **kw)
    os.replace(tmp, dst)



def estimate_blur(img: Image.Image) -> float:
    """Quanto è sfocata la foto (sigma in pixel su 2000 px), col metodo del "risfocare"
    (Zhuo & Sim 2011): sui bordi, il rapporto tra il gradiente e quello della foto risfocata
    di σ0 dà σ = σ0 / √(R² − 1). Si prende la mediana dei bordi più netti."""
    side = 1000
    k = side / max(img.size)
    g = img.convert("L")
    if k < 1:
        g = g.resize((max(1, round(g.width * k)), max(1, round(g.height * k))), Image.BILINEAR)
    else:
        k = 1.0
    a = np.asarray(g, np.float32) / 255
    s0 = 1.0
    g1 = np.hypot(*np.gradient(a))
    g2 = np.hypot(*np.gradient(_blur(a, s0)))
    edge = g1 > max(float(np.percentile(g1, 97)), 0.03)
    if edge.sum() < 50:
        return 0.0
    r = g1[edge] / np.maximum(g2[edge], 1e-4)
    r = r[r > 1.01]
    if len(r) < 30:
        return 4.0
    sig = s0 / np.sqrt(r * r - 1)
    px = side if k < 1 else max(img.size)   # lato della foto misurata
    return float(np.median(sig)) * 2000 / px


def auto_deblur(img: Image.Image) -> dict:
    """Sfocatura automatica: niente se la foto è già nitida."""
    est = estimate_blur(img)
    sigma = math.sqrt(max(est * est - 1.8 * 1.8, 0.0))   # anche una foto nitida misura ~1,8
    if sigma < 1.2:
        return {}
    return {"deblur": float(np.clip(0.5 + sigma * 0.1, 0.5, 0.9)),
            "deblur_radius": float(np.clip((sigma - 0.6) / 3.4, 0, 1))}
