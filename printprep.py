"""Stampabilità di una foto: a quali formati regge, e una copia migliorata per la stampa.

Un formato regge se la foto ha abbastanza pixel per stamparlo a quei dpi: 300 = ottima resa,
200 = buona da vicino. La copia migliorata ingrandisce al massimo 2× per arrivare al formato più
grande possibile a 300 dpi. Il motore è Real-ESRGAN (il più usato e apprezzato per questo, anche
dietro Upscayl) se è installato; altrimenti un ingrandimento Lanczos con nitidezza leggera.
L'originale non si tocca mai: la copia va in una cartella a parte."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageFilter

import edits
from edits import jpeg_meta, load_full, open_unbounded
from i18n import tr

log = logging.getLogger("photoswipe")

# Formati di stampa standard (cm, lato corto × lato lungo), dal più piccolo al più grande.
PRINT_SIZES_CM = [(9, 13), (10, 15), (13, 18), (15, 20), (20, 25), (20, 30), (30, 40), (30, 45), (40, 50), (50, 70)]
MAX_UPSCALE = 2.0


def best_format(w: int, h: int, dpi: int) -> tuple[int, int] | None:
    """Il formato più grande stampabile a quei dpi (orientamento indifferente)."""
    short, long = min(w, h), max(w, h)
    fits = [(a, b) for a, b in PRINT_SIZES_CM
            if short >= a / 2.54 * dpi and long >= b / 2.54 * dpi]
    return fits[-1] if fits else None


def _fmt(f: tuple[int, int]) -> str:
    return f"{f[0]} × {f[1]} cm"


def verdict(w: int, h: int) -> tuple[str, str]:
    """Giudizio (ottima / buona / discreta / scarsa) e il formato che regge."""
    b300, b200 = best_format(w, h, 300), best_format(w, h, 200)
    if b300 and b300[0] * b300[1] >= 600:      # almeno 20 × 30 cm a 300 dpi
        return tr('ottima'), tr('{v0} a 300 dpi', v0=_fmt(b300))
    if b300:
        return tr('buona'), tr('{v0} a 300 dpi', v0=_fmt(b300))
    if b200:
        return tr('discreta'), tr('{v0} a 200 dpi', v0=_fmt(b200))
    return tr('scarsa'), tr('troppo piccola per una stampa di qualità')


def _scale(w: int, h: int) -> float:
    """Ingrandimento (1 = nessuno): il formato più grande raggiungibile a 300 dpi entro 2×.
    Se nessun formato ci arriva (foto piccola), si ingrandisce comunque al massimo: è il meglio che si può fare."""
    short, long = min(w, h), max(w, h)
    reach = [max(a / 2.54 * 300 / short, b / 2.54 * 300 / long) for a, b in PRINT_SIZES_CM]
    ok = [r for r in reach if r <= MAX_UPSCALE]
    if not ok:
        return MAX_UPSCALE
    return max(1.0, max(ok))


def _engine_dir() -> Path:
    """Cartella del motore: accanto all'app (anche dentro il pacchetto PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "engines" / ("windows" if sys.platform == "win32" else "macos")


def realesrgan_bin() -> Path | None:
    """Motore Real-ESRGAN (ncnn-vulkan, lo stesso usato da Upscayl): variabile d'ambiente,
    poi la build inclusa per questo sistema, poi il PATH."""
    if os.environ.get("PHOTOSWIPE_REALESRGAN"):
        return Path(os.environ["PHOTOSWIPE_REALESRGAN"])
    exe = "realesrgan-ncnn-vulkan.exe" if sys.platform == "win32" else "realesrgan-ncnn-vulkan"
    bundled = _engine_dir() / exe
    if bundled.is_file():
        return bundled
    found = shutil.which("realesrgan-ncnn-vulkan")
    return Path(found) if found else None


def models_dir(engine: Path) -> Path:
    """Cartella dei modelli: accanto al motore; se il motore viene dalla variabile d'ambiente o
    dal PATH e lì non ci sono, quelli inclusi nell'app."""
    here = engine.parent / "models"
    if here.is_dir():
        return here
    bundled = _engine_dir() / "models"
    return bundled if bundled.is_dir() else here


# Windows: il motore usa il runtime OpenMP di Microsoft (vcomp140.dll), che non distribuiamo
# (licenza Microsoft): se manca, si usa l'ingrandimento semplice e si suggerisce di installarlo.
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
_DLL_NOT_FOUND = 0xC0000135
missing_runtime = False
simple_upscale = False   # l'ultima copia è stata ingrandita senza Real-ESRGAN (va detto)


_PERCENT = re.compile(r"(\d+(?:\.\d+)?)%")   # il motore scrive "16.67%" su stderr, tessera per tessera

# motori accesi adesso (uno per copia in corso): kill_running() li ferma all'uscita dell'app
_RUNNING: set = set()
_KILLED: set = set()
_RUN_LOCK = threading.Lock()


def kill_running() -> None:
    """Ferma ogni motore Real-ESRGAN acceso (da chiamare quando l'app si chiude): le copie in
    corso finiscono con InterruptedError, senza ripiegare su Lanczos e senza scrivere nulla."""
    with _RUN_LOCK:
        procs = list(_RUNNING)
        _KILLED.update(id(p) for p in procs)
    for p in procs:
        try:
            p.kill()
        except Exception:  # noqa: BLE001 - già finito
            pass


def _open_big(path: Path, size: tuple[int, int]) -> Image.Image:
    """L'uscita del motore (4×: una foto da 12 MP diventa 195 MP) supera il limite "decompression
    bomb" di PIL: è un file temporaneo nostro, si apre senza limite. Se è un JPEG si decodifica
    già ridotta (draft: scala DCT 1/2, 1/4… mai sotto la misura finale), così in memoria non sta
    mai l'immagine 4× intera; poi Lanczos alla misura esatta."""
    with open_unbounded(path) as big:
        big.draft("RGB", size)   # solo JPEG; per gli altri formati non fa nulla
        big.load()
        out = big.resize(size, Image.LANCZOS) if big.size != size else big.copy()
    return out.convert("RGB")


def _enlarge(im: Image.Image, scale: float, progress=None) -> Image.Image:
    global missing_runtime, simple_upscale
    w, h = round(im.width * scale), round(im.height * scale)
    engine = realesrgan_bin()
    if engine:
        try:
            with tempfile.TemporaryDirectory() as d:
                src, out = Path(d) / "in.png", Path(d) / "out.jpg"
                im.save(src)
                # il motore lavora a 4×: poi si riporta alla misura esatta con Lanczos. Uscita JPEG
                # (qualità 100, senza sottocampionamento): si può leggere già ridotta, vedi _open_big
                cmd = [str(engine), "-i", str(src), "-o", str(out), "-n", "realesrgan-x4plus", "-s", "4",
                       "-m", str(models_dir(engine)), "-f", "jpg"]
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0   # niente console su Windows
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                        text=True, creationflags=flags)
                with _RUN_LOCK:
                    _RUNNING.add(proc)
                killer = threading.Timer(600, proc.kill)   # come il vecchio timeout: se il motore si blocca
                killer.start()
                code = None
                try:
                    for line in proc.stderr:
                        m = _PERCENT.search(line)
                        if m and progress:
                            progress(min(float(m.group(1)) / 100, 1.0))
                    code = proc.wait()
                    if progress and not code:
                        progress(1.0)   # il motore scrive l'ultima percentuale prima di finire
                finally:
                    killer.cancel()
                    if code is None:   # errore a metà: il motore non resta acceso
                        proc.kill()
                        proc.wait()
                    with _RUN_LOCK:
                        _RUNNING.discard(proc)
                        stopped = id(proc) in _KILLED
                        _KILLED.discard(id(proc))
                if stopped:
                    raise InterruptedError("print copy stopped")   # l'app si chiude
                if code:
                    raise subprocess.CalledProcessError(code, cmd)
                return _open_big(out, (w, h))
        except InterruptedError:
            raise
        except subprocess.CalledProcessError as e:
            log.warning("Real-ESRGAN non riuscito (codice %s): ingrandimento semplice", e.returncode)
            if sys.platform == "win32" and (e.returncode & 0xFFFFFFFF) == _DLL_NOT_FOUND:
                missing_runtime = True   # manca il Visual C++ Redistributable
        except Exception as e:  # noqa: BLE001 - motore non disponibile o fallito: si ripiega sul metodo classico
            log.warning("Real-ESRGAN non disponibile (%r): ingrandimento semplice", e)
    simple_upscale = True
    return im.resize((w, h), Image.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))


def copy_path(export_dir: Path, item) -> Path:
    """Dove sta la copia per la stampa: export/Stampa/<nome>_stampa.jpg. Due foto con lo stesso
    nome in cartelle diverse (due schede) non si sovrascrivono: la seconda ha un segno in più."""
    folder = Path(export_dir) / "Stampa"
    name = f"{item.main.stem}_stampa"
    folder_rel = item.id.rsplit("/", 1)[0] if "/" in item.id else ""
    if folder_rel:
        name += "_" + hashlib.sha1(folder_rel.encode("utf-8")).hexdigest()[:6]
    return folder / f"{name}.jpg"


def improve(src: Path, dst: Path, progress=None, edit: dict | None = None) -> str:
    """Scrive in dst una copia pronta per la stampa (JPEG 300 dpi) e dice cosa è cambiato.
    progress(f) riceve l'avanzamento 0..1 quando il motore lo dice (altrimenti niente).
    edit: le modifiche di Regola / Ritaglia della foto (come nell'export), applicate prima di
    ingrandire, così la copia per l'album è uguale alla foto modificata."""
    global missing_runtime, simple_upscale
    missing_runtime = simple_upscale = False   # vale per questa copia, non per quelle di prima
    # come l'export: 16 bit, CMYK, DNG a piena risoluzione, HEIC, orientamento come l'anteprima
    try:
        im, keep = load_full(src)
    except Exception as e:  # noqa: BLE001 - né PIL né Qt la leggono
        raise RuntimeError(tr('Impossibile aprire {v0}', v0=src.name)) from e
    if not edits.is_empty(edit):
        im = edits.render(im, edits.clean(edit))
    w, h = im.size
    scale = _scale(w, h)
    if scale > 1:
        im = _enlarge(im, scale, progress)   # l'originale si libera subito
    else:
        im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    meta = jpeg_meta(keep, im.size)   # EXIF (misure nuove), ICC solo RGB, XMP com'è
    exif = Image.Exif()
    if meta.get("exif"):
        exif.load(meta["exif"])
    exif[274], exif[282], exif[283], exif[296] = 1, 300.0, 300.0, 2   # orientamento, risoluzione 300 dpi
    meta["exif"] = exif.tobytes()
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=95, subsampling=0, dpi=(300, 300), **meta)
    _, text = verdict(*im.size)
    note = ""
    if missing_runtime:
        note = tr(" (ingrandimento semplice: per la qualità migliore installa il Visual C++ "
                  "Redistributable gratuito di Microsoft: {url})", url=VC_REDIST_URL)
    elif simple_upscale:
        note = tr(" (ingrandimento semplice: il motore Real-ESRGAN non è disponibile)")
    return tr('{v0} × {v1} px: {v2}', v0=im.width, v1=im.height, v2=text) + note
