"""Stampabilità di una foto: a quali formati regge, e una copia migliorata per la stampa.

Un formato regge se la foto ha abbastanza pixel per stamparlo a quei dpi: 300 = ottima resa,
200 = buona da vicino. La copia migliorata ingrandisce al massimo 2× per arrivare al formato più
grande possibile a 300 dpi. Il motore è Real-ESRGAN (il più usato e apprezzato per questo, anche
dietro Upscayl) se è installato; altrimenti un ingrandimento Lanczos con nitidezza leggera.
L'originale non si tocca mai: la copia va in una cartella a parte."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from i18n import tr

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


# Windows: il motore usa il runtime OpenMP di Microsoft (vcomp140.dll), che non distribuiamo
# (licenza Microsoft): se manca, si usa l'ingrandimento semplice e si suggerisce di installarlo.
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
_DLL_NOT_FOUND = 0xC0000135
missing_runtime = False


_PERCENT = re.compile(r"(\d+(?:\.\d+)?)%")   # il motore scrive "16.67%" su stderr, tessera per tessera


def _enlarge(im: Image.Image, scale: float, progress=None) -> Image.Image:
    global missing_runtime
    w, h = round(im.width * scale), round(im.height * scale)
    engine = realesrgan_bin()
    if engine:
        try:
            with tempfile.TemporaryDirectory() as d:
                src, out = Path(d) / "in.png", Path(d) / "out.png"
                im.save(src)
                # il motore lavora a 4× (o 2×): poi si riporta alla misura esatta con Lanczos
                cmd = [str(engine), "-i", str(src), "-o", str(out), "-n", "realesrgan-x4plus", "-s", "4",
                       "-m", str(engine.parent / "models")]
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0   # niente console su Windows
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                        text=True, creationflags=flags)
                killer = threading.Timer(600, proc.kill)   # come il vecchio timeout: se il motore si blocca
                killer.start()
                try:
                    for line in proc.stderr:
                        m = _PERCENT.search(line)
                        if m and progress:
                            progress(min(float(m.group(1)) / 100, 1.0))
                    code = proc.wait()
                finally:
                    killer.cancel()
                if code:
                    raise subprocess.CalledProcessError(code, cmd)
                with Image.open(out) as big:
                    big.load()
                    return big.resize((w, h), Image.LANCZOS)
        except subprocess.CalledProcessError as e:
            if sys.platform == "win32" and (e.returncode & 0xFFFFFFFF) == _DLL_NOT_FOUND:
                missing_runtime = True   # manca il Visual C++ Redistributable
        except (OSError, subprocess.SubprocessError):
            pass   # motore non disponibile o fallito: si ripiega sul metodo classico
    return im.resize((w, h), Image.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))


def improve(src: Path, dst: Path, progress=None) -> str:
    """Scrive in dst una copia pronta per la stampa (JPEG 300 dpi) e dice cosa è cambiato.
    progress(f) riceve l'avanzamento 0..1 quando il motore lo dice (altrimenti niente)."""
    with Image.open(src) as im:
        exif = im.getexif()
        im = ImageOps.exif_transpose(im).convert("RGB")
    w, h = im.size
    scale = _scale(w, h)
    if scale > 1:
        im = _enlarge(im, scale, progress)
    else:
        im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    exif[274], exif[282], exif[283], exif[296] = 1, 300.0, 300.0, 2   # orientamento, risoluzione 300 dpi
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=95, subsampling=0, dpi=(300, 300), exif=exif.tobytes())
    _, text = verdict(*im.size)
    note = ""
    if missing_runtime:
        note = tr(" (ingrandimento semplice: per la qualità migliore installa il Visual C++ "
                  "Redistributable gratuito di Microsoft: {url})", url=VC_REDIST_URL)
    return tr('{v0} × {v1} px: {v2}', v0=im.width, v1=im.height, v2=text) + note
