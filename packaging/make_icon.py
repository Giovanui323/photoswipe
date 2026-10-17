"""Crea packaging/PhotoSwipe.icns (foto + spunta verde) con Pillow e iconutil."""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

here = Path(__file__).parent
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((60, 60, S - 60, S - 60), radius=200, fill=(28, 30, 33, 255))
# foto
d.rounded_rectangle((210, 250, 760, 690), radius=40, fill=(235, 235, 235, 255))
d.rounded_rectangle((240, 280, 730, 600), radius=20, fill=(91, 141, 239, 255))
d.polygon([(240, 600), (420, 400), (560, 560), (640, 480), (730, 600)], fill=(79, 183, 168, 255))
d.ellipse((600, 320, 670, 390), fill=(240, 180, 41, 255))
# spunta
d.ellipse((560, 540, 860, 840), fill=(47, 122, 76, 255), outline=(28, 30, 33, 255), width=24)
d.line([(625, 690), (690, 755), (800, 620)], fill=(255, 255, 255, 255), width=46, joint="curve")
iconset = here / "PhotoSwipe.iconset"
iconset.mkdir(exist_ok=True)
for size in (16, 32, 128, 256, 512):
    img.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
    img.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(here / "PhotoSwipe.icns")], check=True)
img.save(here / "icon.png")
print("ok", sys.argv[0])
