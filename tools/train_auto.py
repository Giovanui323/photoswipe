"""Insegna l'AUTO da solo (autoapprendimento), senza ritocchi di nessuno.

Per ogni foto buona (pubblico dominio / CC0, scaricata da tools/fetch_training.py):
  1. la si rovina apposta con i cursori dell'app (esposizione, contrasto, luci, ombre, neri,
     saturazione, temperatura, tinta) — oppure la si lascia com'è;
  2. si cerca quali cursori la riportano più vicina all'originale (discesa per coordinate);
  3. il modello impara: caratteristiche della foto rovinata → quei cursori.
Così impara anche a NON toccare le foto già buone. Il risultato è auto_model.py (pesi in numpy,
pochi KB), usato da edits.learned_auto. Gira uguale su macOS e Windows.

    .venv/bin/python tools/train_auto.py
"""
from __future__ import annotations

import base64
import io
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import edits as E  # noqa: E402

KEYS = E.LEARNED_KEYS
LIMITS = {"exposure": (-1, 1), "contrast": (-1, 1), "highlights": (-1, 1), "shadows": (-1, 1),
          "blackpoint": (-1, 1), "saturation": (-1, 1), "vibrance": (-1, 1), "wb_temp": (-1, 1),
          "wb_tint": (-1, 1)}


def sample_damage(rng) -> dict:
    """Un difetto realistico: sotto/sovraesposta, piatta, dominante, slavata… o niente."""
    if rng.random() < 0.15:
        return {}
    d = {}
    if rng.random() < 0.7:
        d["exposure"] = float(np.clip(rng.normal(0, 0.35), -0.8, 0.8))
    if rng.random() < 0.5:
        d["contrast"] = float(rng.uniform(-0.5, 0.3))
    if rng.random() < 0.3:
        d["highlights"] = float(rng.uniform(0, 0.5))
    if rng.random() < 0.3:
        d["shadows"] = float(rng.uniform(-0.5, 0))
    if rng.random() < 0.4:
        d["blackpoint"] = float(rng.uniform(-0.6, 0.2))
    if rng.random() < 0.5:
        d["saturation"] = float(rng.uniform(-0.5, 0.3))
    if rng.random() < 0.6:
        d["wb_temp"] = float(np.clip(rng.normal(0, 0.35), -0.9, 0.9))
    if rng.random() < 0.4:
        d["wb_tint"] = float(np.clip(rng.normal(0, 0.25), -0.7, 0.7))
    return d


def loss(a: np.ndarray, b: np.ndarray) -> float:
    """Differenza "a occhio": luminanza pesata il doppio, poi i due assi del colore."""
    La, Lb = E._lum(a), E._lum(b)
    ca = np.stack([a[..., 0] - a[..., 1], a[..., 2] - a[..., 1]], -1)
    cb = np.stack([b[..., 0] - b[..., 1], b[..., 2] - b[..., 1]], -1)
    return float(2 * np.abs(La - Lb).mean() + np.abs(ca - cb).mean())


def render(img: Image.Image, p: dict) -> np.ndarray:
    return np.asarray(E.render_tone(img, E.clean(p)), np.float32) / 255


def fit(damaged: Image.Image, target: np.ndarray, start: dict) -> dict:
    """I cursori che rimettono a posto la foto (discesa per coordinate, passi sempre più piccoli)."""
    p = {k: float(np.clip(start.get(k, 0.0), *LIMITS[k])) for k in KEYS}
    best = loss(render(damaged, p), target)
    zero = loss(np.asarray(damaged, np.float32) / 255, target)
    if zero <= best:
        p, best = {k: 0.0 for k in KEYS}, zero
    for step in (0.2, 0.1, 0.05, 0.02):
        improved = True
        while improved:
            improved = False
            for k in KEYS:
                for s in (step, -step):
                    q = dict(p)
                    q[k] = float(np.clip(q[k] + s, *LIMITS[k]))
                    if q[k] == p[k]:
                        continue
                    lq = loss(render(damaged, q), target)
                    if lq < best - 1e-5:
                        p, best, improved = q, lq, True
                        break
    return p


def work(args):
    path, n, seed = args
    rng = np.random.default_rng(seed)
    try:
        img = E.feature_image(Image.open(path))
    except Exception:  # noqa: BLE001
        return []
    target = np.asarray(img, np.float32) / 255
    out = []
    for _ in range(n):
        dmg = sample_damage(rng)
        damaged = E.render_tone(img, E.clean(dmg)) if dmg else img
        start = {k: -v for k, v in dmg.items()}
        p = fit(damaged, target, start)
        before = loss(np.asarray(damaged, np.float32) / 255, target)
        out.append((E.auto_features(damaged), [p[k] for k in KEYS], [dmg.get(k, 0.0) for k in KEYS],
                    before, path.name))
    return out


# ----------------------------------------------------------------------------- rete piccola
def init(sizes, rng):
    P = {}
    for i, (a, b) in enumerate(zip(sizes[:-1], sizes[1:])):
        P[f"W{i}"] = (rng.standard_normal((a, b)) * np.sqrt(1 / a)).astype(np.float32)
        P[f"b{i}"] = np.zeros(b, np.float32)
    return P


def forward(P, X):
    hs = [X]
    n = len([k for k in P if k.startswith("W")])
    h = X
    for i in range(n):
        h = h @ P[f"W{i}"] + P[f"b{i}"]
        h = np.tanh(h)
        hs.append(h)
    return hs


def train(X, Y, Xv, Yv, hidden=(64, 32), epochs=3000, lr=3e-3, wd=1e-4, seed=0):
    rng = np.random.default_rng(seed)
    P = init([X.shape[1], *hidden, Y.shape[1]], rng)
    m = {k: np.zeros_like(v) for k, v in P.items()}
    v = {k: np.zeros_like(v) for k, v in P.items()}
    best, best_P, bad = 1e9, None, 0
    n = len([k for k in P if k.startswith("W")])
    for ep in range(1, epochs + 1):
        hs = forward(P, X)
        out = hs[-1]
        g = 2 * (out - Y) / len(X) * (1 - out ** 2)
        grads = {}
        for i in reversed(range(n)):
            grads[f"W{i}"] = hs[i].T @ g + wd * P[f"W{i}"]
            grads[f"b{i}"] = g.sum(0)
            if i:
                g = (g @ P[f"W{i}"].T) * (1 - hs[i] ** 2)
        for k in P:   # Adam
            m[k] = 0.9 * m[k] + 0.1 * grads[k]
            v[k] = 0.999 * v[k] + 0.001 * grads[k] ** 2
            P[k] -= lr * (m[k] / (1 - 0.9 ** ep)) / (np.sqrt(v[k] / (1 - 0.999 ** ep)) + 1e-8)
        if ep % 25 == 0:
            vl = float(((forward(P, Xv)[-1] - Yv) ** 2).mean())
            if vl < best - 1e-6:
                best, best_P, bad = vl, {k: x.copy() for k, x in P.items()}, 0
            else:
                bad += 1
                if bad > 20:
                    break
    return best_P, best


def main():
    imgs = sorted((ROOT / "build" / "train" / "img").glob("*.jpg"))
    rng = np.random.default_rng(42)
    order = rng.permutation(len(imgs))
    nval = max(20, len(imgs) // 7)
    val = {imgs[i] for i in order[:nval]}
    jobs = [(p, 3 if p in val else 10, i) for i, p in enumerate(imgs)]
    t = time.time()
    with mp.get_context("spawn").Pool(max(1, mp.cpu_count() - 1)) as pool:
        res = pool.map(work, jobs, chunksize=4)
    print(f"{sum(len(r) for r in res)} esempi da {len(imgs)} foto in {time.time() - t:.0f} s", flush=True)
    tr = [s for r, j in zip(res, jobs) if j[0] not in val for s in r]
    va = [s for r, j in zip(res, jobs) if j[0] in val for s in r]
    X = np.array([s[0] for s in tr], np.float32)
    Y = np.array([s[1] for s in tr], np.float32)
    Xv = np.array([s[0] for s in va], np.float32)
    Yv = np.array([s[1] for s in va], np.float32)
    np.savez(ROOT / "build" / "train" / "dataset.npz", X=X, Y=Y, Xv=Xv, Yv=Yv,
             names_v=np.array([s[4] for s in va]), dmg_v=np.array([s[2] for s in va], np.float32))
    mu, sd = X.mean(0), X.std(0) + 1e-6
    # media di 5 reti piccole (più stabile di una sola), un po' prudente (×ALPHA):
    # meglio correggere un filo meno che rovinare una foto già buona
    ALPHA = 0.75
    model = {"mu": mu.astype(np.float32), "sd": sd.astype(np.float32),
             "scale": np.full(len(KEYS), ALPHA, np.float32)}
    preds = []
    for j in range(5):
        P, vl = train((X - mu) / sd, Y, (Xv - mu) / sd, Yv, hidden=(32,), epochs=6000, seed=j)
        preds.append(forward(P, (Xv - mu) / sd)[-1])
        model.update({f"m{j}_{k}": v for k, v in P.items()})
    vl = float(((np.mean(preds, 0) - Yv) ** 2).mean())
    print(f"errore di validazione (MSE cursori, media di 5): {vl:.4f}", flush=True)
    buf = io.BytesIO()
    np.savez_compressed(buf, **model)
    blob = base64.b64encode(buf.getvalue()).decode()
    lines = [blob[i:i + 100] for i in range(0, len(blob), 100)]
    (ROOT / "auto_model.py").write_text(
        '"""AUTO imparato da solo (tools/train_auto.py) su foto di pubblico dominio / CC0 di\n'
        f'Wikimedia Commons ({len(imgs)} foto, {len(X) + len(Xv)} esempi). Generato: non modificare."""\n'
        "import base64\nimport io\n\nimport numpy as np\n\nKEYS = " + repr(tuple(KEYS)) + "\n"
        "_BLOB = (\n" + "".join(f'    "{ln}"\n' for ln in lines) + ")\n\n\n"
        "def load() -> dict:\n"
        "    with np.load(io.BytesIO(base64.b64decode(_BLOB))) as z:\n"
        "        return {k: z[k] for k in z.files}\n", encoding="utf-8")
    # confronto sulle foto di validazione: nessuna correzione, AUTO classico, AUTO imparato
    import importlib
    import auto_model
    importlib.reload(auto_model)
    E._MODEL = None
    stats = {"niente": [], "classico": [], "imparato": [], "ottimo": []}
    stats_ok = {"classico": [], "imparato": []}
    for p in sorted(val)[:150]:
        img = E.feature_image(Image.open(p))
        target = np.asarray(img, np.float32) / 255
        r2 = np.random.default_rng(hash(p.name) % 2**32)
        for _ in range(3):
            dmg = sample_damage(r2)
            damaged = E.render_tone(img, E.clean(dmg)) if dmg else img
            cls = {**E.classic_auto_light(damaged), **E.classic_auto_color(damaged),
                   **E.classic_auto_wb(damaged)}
            lrn = E.learned_auto(damaged)
            best = fit(damaged, target, {k: -v for k, v in dmg.items()})
            for name, pr in (("niente", {}), ("classico", cls), ("imparato", lrn), ("ottimo", best)):
                stats[name].append(loss(render(damaged, pr), target))
            if not dmg:   # foto già buona: quanto la peggiora?
                stats_ok["classico"].append(loss(render(damaged, cls), target))
                stats_ok["imparato"].append(loss(render(damaged, lrn), target))
    report = {k: round(float(np.mean(v)) * 100, 2) for k, v in stats.items()}
    report_ok = {k: round(float(np.mean(v)) * 100, 2) if v else None for k, v in stats_ok.items()}
    print("errore medio (più basso = meglio):", report)
    print("su foto già buone (0 = non le tocca):", report_ok)
    (ROOT / "build" / "train" / "report.json").write_text(json.dumps(
        {"all": report, "good_photos": report_ok, "val_mse": vl, "photos": len(imgs)}, indent=1))


if __name__ == "__main__":
    main()
