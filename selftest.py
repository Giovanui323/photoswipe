"""Autodiagnosi senza finestra: `app.py --selftest <cartella> <export>` (prova la DMG)."""
from pathlib import Path

from PIL import Image
from PIL.JpegImagePlugin import get_sampling

import exporter
import frames
from i18n import tr
from scanner import scan


def selftest(root: Path, out: Path, title: str) -> int:
    """Autodiagnosi senza finestra (per provare l'app impacchettata): scan + export + controlli."""
    print(title, "| ffmpeg:", frames.ffmpeg_exe())
    items = scan(root, [out])
    print("elementi:", len(items), {k: sum(1 for i in items if i.kind == k) for k in ("photo", "pano", "live", "video")})
    ok = True
    for kind in ("photo", "live"):
        it = next((i for i in items if i.kind == kind), None)
        if not it:
            continue
        files = exporter.export_item(it, None, out, exporter.Settings())
        for f in files:
            if f.suffix.lower() == ".jpg" and kind == "live":
                im = Image.open(f)
                good = get_sampling(im) == 0 and bool(im.info.get("icc_profile"))
                ok &= good
                print(kind, f.name, im.size, "4:4:4+sRGB" if good else tr('ERRORE qualità'))
            else:
                same = f.read_bytes() == (it.image or it.video).read_bytes()
                ok &= same
                print(kind, f.name, tr('copia identica') if same else tr('ERRORE copia'))
    print("ESITO:", "OK" if ok else tr('ERRORE'))
    return 0 if ok else 1
