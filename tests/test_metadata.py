"""Metadati del pannello Info: EXIF delle foto (fotocamera, scatto, GPS) letti senza errori."""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import metadata  # noqa: E402
from scanner import Item  # noqa: E402


def _photo(tmp_path: Path, gps: bool) -> Path:
    p = tmp_path / "DJI_20250601120000_0001_D.JPG"
    im = Image.new("RGB", (40, 30), "blue")
    ex = im.getexif()
    ex[271], ex[272] = "DJI", "Osmo Pocket 4"
    sub = ex.get_ifd(0x8769)
    sub[33437], sub[33434], sub[34855] = 2.0, (1, 250), 100
    if gps:
        g = ex.get_ifd(0x8825)
        g[1], g[2], g[3], g[4] = "N", (40.0, 41.0, 52.0), "W", (14.0, 28.0, 48.0)
    im.save(p, exif=ex)
    return p


def test_exif_and_gps(tmp_path):
    p = _photo(tmp_path, gps=True)
    m = metadata.read(Item("photo", p.name, image=p))
    rows = dict(m.rows)
    assert rows["Fotocamera"] == "DJI Osmo Pocket 4"
    assert "ƒ/2.0" in rows["Scatto"] and "1/250 s" in rows["Scatto"] and "ISO 100" in rows["Scatto"]
    assert rows["Dimensioni"].startswith("40 × 30")
    lat, lon = m.gps
    assert abs(lat - 40.6978) < 1e-3 and abs(lon + 14.48) < 1e-3   # W = longitudine negativa
    assert "O" in metadata.fmt_gps(lat, lon)


def test_no_gps_and_unreadable(tmp_path):
    p = _photo(tmp_path, gps=False)
    assert metadata.read(Item("photo", p.name, image=p)).gps is None
    bad = tmp_path / "rotta.jpg"
    bad.write_bytes(b"non una foto")
    m = metadata.read(Item("photo", bad.name, image=bad))   # nessuna eccezione
    assert m.gps is None and dict(m.rows)["File"].startswith("rotta.jpg")


def test_printability():
    # 6000×4000 px (24 MP): 4000 px / 300 dpi = 33,9 cm di lato corto -> 30×45 cm; a 200 dpi arriva a 50×70
    assert metadata.print_size(6000, 4000) == "30 × 45 cm a 300 dpi  ·  50 × 70 cm a 200 dpi"
    # 3000×2000 px (6 MP): 300 dpi -> 15×20 cm; 200 dpi -> 20×30 cm
    assert metadata.print_size(2000, 3000) == "15 × 20 cm a 300 dpi  ·  20 × 30 cm a 200 dpi"
    # orientamento irrilevante
    assert metadata.print_size(3000, 2000) == metadata.print_size(2000, 3000)
    assert metadata.print_size(800, 600) == "troppo piccola per una stampa di qualità"
