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


def test_place_offline(monkeypatch):
    import places
    monkeypatch.setattr(places, "LANG", "it")
    monkeypatch.setattr(places, "_index", None)
    assert places.offline(45.9853, 9.2611).startswith("Bellagio, Lombardia · Italia")
    assert places.offline(41.9028, 12.4964).startswith("Trevi, Roma, Lazio · Italia")   # quartiere + città
    assert places.offline(43.0, 10.0).startswith("vicino a ")   # in mare: la costa più vicina
    monkeypatch.setattr(places, "_index", None)


def test_place_in_meta_and_html(tmp_path, monkeypatch):
    import places
    monkeypatch.setattr(places, "online", lambda lat, lon: "")   # i test non vanno in rete
    p = _photo(tmp_path, gps=True)
    m = metadata.read(Item("photo", p.name, image=p))
    assert m.place   # New York: la località più vicina dall'elenco incluso
    html = places.info_html(m, "#aaa", "#09f", str)
    assert "📍" in html and m.place in html and "href=" in html


def test_place_online_uses_cache(monkeypatch, tmp_path):
    import places
    monkeypatch.setattr(places, "_cache_path", lambda: tmp_path / "places.json")
    monkeypatch.setattr(places, "_cache", None)
    calls = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"address": {"village": "Bellagio", "state": "Lombardia", "country": "Italia"}}'

    monkeypatch.setattr(places.urllib.request, "urlopen", lambda req, timeout: calls.append(req) or Resp())
    assert places.online(45.9853, 9.2611) == "Bellagio, Lombardia · Italia"
    assert places.online(45.98531, 9.26112) == "Bellagio, Lombardia · Italia"   # stesso posto: dalla cache
    assert len(calls) == 1 and "PhotoSwipe" in calls[0].get_header("User-agent")


def test_place_online_switch(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    import places
    QApplication.instance() or QApplication([])
    store = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    store.setValue("places_online", "0")
    box = places.online_switch(store)
    assert not box.isChecked() and not places.ONLINE
    monkeypatch.setattr(places, "_cache", {})
    monkeypatch.setattr(places.urllib.request, "urlopen", lambda *a, **k: 1 / 0)   # spento: nessuna richiesta
    assert places.online(45.0, 9.0) == ""
    box.setChecked(True)
    assert places.ONLINE and store.value("places_online") == "1"
