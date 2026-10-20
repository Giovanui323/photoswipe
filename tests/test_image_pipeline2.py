"""Pipeline delle immagini, seconda parte: HEIC con pi-heif (EXIF, ICC, orientamento), XMP,
dimensioni EXIF dopo il ritaglio, modifiche che non cambiano nulla, panorami enormi, occhi rossi
che seguono Raddrizza / Prospettiva, copia per la stampa con le modifiche e con poca memoria,
modelli del motore e motore da fermare all'uscita."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PHOTOSWIPE_LANG", "it")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest
from PIL import Image, ImageCms

import edits as E
import printprep as P

PY = sys.executable
P3_ICC = Path("/System/Library/ColorSync/Profiles/Display P3.icc")
XMP = (b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
       b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
       b'<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"'
       b' xmp:Rating="4"><dc:subject><rdf:Bag><rdf:li>mare</rdf:li><rdf:li>estate</rdf:li></rdf:Bag>'
       b'</dc:subject></rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>')


@pytest.fixture
def no_engine(monkeypatch, tmp_path):
    monkeypatch.setenv("PHOTOSWIPE_REALESRGAN", str(tmp_path / "manca-il-motore"))


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _fake_engine(tmp_path: Path, body: str, name: str = "fake_engine.py") -> Path:
    f = tmp_path / name
    f.write_text(f"#!{PY}\n" + textwrap.dedent("""
        import os, sys, time
        a = sys.argv; src = a[a.index("-i") + 1]; out = a[a.index("-o") + 1]
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
    """) + textwrap.dedent(body))
    f.chmod(0o755)
    return f


def _exif(orient: int = 1) -> Image.Exif:
    ex = Image.Exif()
    ex[0x0112] = orient
    ex[0x010F] = "Maker"
    ex[0x0110] = "TestCam"
    sub = ex.get_ifd(0x8769)
    sub[0x9003] = "2021:05:06 07:08:09"
    sub[0xA002] = 600
    sub[0xA003] = 400
    gps = ex.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (45.0, 30.0, 0.0)
    return ex


def _check_exif(ex: Image.Exif):
    assert ex.get(0x0110) == "TestCam"
    assert ex.get_ifd(0x8769).get(0x9003) == "2021:05:06 07:08:09"
    gps = ex.get_ifd(0x8825)
    assert gps.get(1) == "N" and tuple(float(v) for v in gps.get(2)) == (45.0, 30.0, 0.0)


def _two_tone(w=60, h=40) -> Image.Image:
    a = np.zeros((h, w, 3), np.uint8)
    a[:, : w // 3] = (255, 0, 0)
    a[:, w // 3:] = (0, 0, 255)
    return Image.fromarray(a)


def _heic(tmp_path: Path, orient: int = 6) -> Path:
    if not shutil.which("sips"):
        pytest.skip("serve sips (macOS) per creare un HEIC")
    if not P3_ICC.is_file():
        pytest.skip("profilo Display P3 di sistema (macOS)")
    jpg = tmp_path / "h.jpg"
    _two_tone().save(jpg, exif=_exif(orient).tobytes(), icc_profile=P3_ICC.read_bytes())
    heic = tmp_path / "h.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(jpg), "--out", str(heic)], capture_output=True)
    if not heic.is_file():
        pytest.skip("sips non scrive HEIC")
    return heic


def _qt_read(path: Path):
    from PySide6.QtGui import QImage, QImageReader
    r = QImageReader(str(path))
    r.setAutoTransform(True)
    q = r.read().convertToFormat(QImage.Format_RGB888)
    return q


def _desc(icc: bytes) -> str:
    return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(__import__("io").BytesIO(icc))).strip()


# ----------------------------------------------------------------------------- 1. HEIC
@pytest.fixture
def pi_heif():
    return pytest.importorskip("pi_heif", reason="pi-heif non installato")


def test_heic_keeps_exif_icc_and_matches_qt_orientation(qapp, pi_heif, tmp_path):
    heic = _heic(tmp_path, orient=6)
    img, keep = E.load_full(heic)
    ex = Image.Exif()
    ex.load(keep["exif"])
    _check_exif(ex)
    assert ex.get(0x0112, 1) == 1                       # già girata
    assert keep.get("icc_profile") and "P3" in _desc(keep["icc_profile"])
    q = _qt_read(heic)
    assert img.size == (q.width(), q.height())          # come l'anteprima
    for x, y in ((2, 2), (img.width - 3, img.height - 3)):
        c = q.pixelColor(x, y)
        assert abs(np.array(img.getpixel((x, y))) - (c.red(), c.green(), c.blue())).max() < 40


def test_heic_edited_export_and_print_copy_keep_exif_icc(qapp, pi_heif, no_engine, tmp_path):
    heic = _heic(tmp_path)
    img, keep = E.load_full(heic)
    E.save_edited(E.render(img, {"exposure": 0.3}), tmp_path / "out.jpg", keep)
    for f in (tmp_path / "out.jpg",):
        o = Image.open(f)
        _check_exif(o.getexif())
        assert "P3" in _desc(o.info["icc_profile"])
    P.improve(heic, tmp_path / "stampa.jpg")
    o = Image.open(tmp_path / "stampa.jpg")
    _check_exif(o.getexif())
    assert "P3" in _desc(o.info["icc_profile"])


def test_heic_without_pi_heif_falls_back_to_qt(qapp, monkeypatch, tmp_path):
    heic = _heic(tmp_path)
    real_open = Image.open

    def no_heif(fp, *a, **k):   # come senza pi-heif: PIL non riconosce il file
        if str(fp).lower().endswith(".heic"):
            raise Image.UnidentifiedImageError(str(fp))
        return real_open(fp, *a, **k)
    monkeypatch.setattr(Image, "open", no_heif)
    img, keep = E.load_full(heic)
    q = _qt_read(heic)
    assert img.mode == "RGB" and img.size == (q.width(), q.height())


# ----------------------------------------------------------------------------- 2. XMP
def test_xmp_kept_in_edited_export_and_print_copy(no_engine, tmp_path):
    src = tmp_path / "x.jpg"
    _two_tone().save(src, exif=_exif().tobytes(), xmp=XMP)
    img, keep = E.load_full(src)
    E.save_edited(E.render(img, {"exposure": 0.2}), tmp_path / "out.jpg", keep)
    assert Image.open(tmp_path / "out.jpg").info.get("xmp") == XMP
    P.improve(src, tmp_path / "stampa.jpg")
    assert Image.open(tmp_path / "stampa.jpg").info.get("xmp") == XMP


def test_huge_xmp_does_not_break_export(tmp_path):
    img = _two_tone()
    E.save_edited(img, tmp_path / "out.jpg", {"xmp": b"x" * 70000})   # oltre un segmento JPEG
    assert Image.open(tmp_path / "out.jpg").size == img.size


def test_huge_makernote_dropped_not_whole_exif(tmp_path):
    ex = _exif()
    ex.get_ifd(0x8769)[0x927C] = b"m" * 70000
    E.save_edited(_two_tone(), tmp_path / "out.jpg", {"exif": ex.tobytes()})
    _check_exif(Image.open(tmp_path / "out.jpg").getexif())


# ----------------------------------------------------------------------------- 3. misure EXIF
def test_exif_pixel_dimensions_follow_crop(no_engine, tmp_path):
    src = tmp_path / "c.jpg"
    _two_tone(600, 400).save(src, exif=_exif().tobytes())
    img, keep = E.load_full(src)
    out = E.render(img, {"crop": [0.0, 0.0, 0.5, 0.5]})
    E.save_edited(out, tmp_path / "out.jpg", keep)
    sub = Image.open(tmp_path / "out.jpg").getexif().get_ifd(0x8769)
    assert (sub.get(0xA002), sub.get(0xA003)) == out.size == (300, 200)
    assert sub.get(0x9003) == "2021:05:06 07:08:09"
    P.improve(src, tmp_path / "stampa.jpg")
    o = Image.open(tmp_path / "stampa.jpg")
    sub = o.getexif().get_ifd(0x8769)
    assert (sub.get(0xA002), sub.get(0xA003)) == o.size


# ----------------------------------------------------------------------------- 4. modifiche nulle
@pytest.mark.parametrize("e", [
    {"aspect": "original"}, {"aspect": "square"}, {"aspect": "custom", "aspect_custom": [3, 2]},
    {"exposure": 0.0, "lv_white": 1.0, "redeye_size": 0.04}, {"crop": [0, 0, 1, 1]},
    {"redeye_size": 0.07}, {"exposure": 0.4, "off": ["light"]}, {"enhanced": True},
    {"off": ["color"]}, {"bw": 0.3},   # bw senza "bw_on": spento
])
def test_noop_edits_are_empty(e):
    assert E.is_empty(e), e


@pytest.mark.parametrize("e", [
    {"exposure": 0.2}, {"flip": True}, {"crop": [0, 0, 0.5, 1]}, {"straighten": 2.0},
    {"bw_on": True}, {"redeye": [[0.5, 0.5, 0.04]]}, {"aspect": "square", "crop": [0.1, 0, 0.8, 1]},
])
def test_real_edits_not_empty(e):
    assert not E.is_empty(e), e


def test_clean_drops_aspect_without_crop():
    assert E.clean({"aspect": "original"}) == {}
    assert E.clean({"aspect": "square", "crop": [0.1, 0, 0.8, 1]})["aspect"] == "square"


def test_noop_edit_exported_as_identical_copy(tmp_path):
    import exporter
    from scanner import Item
    src = tmp_path / "src" / "a.jpg"
    src.parent.mkdir()
    _two_tone().save(src, exif=_exif().tobytes(), quality=80)
    item = Item(kind="photo", id="a.jpg", image=src)
    out = exporter.export_item(item, None, tmp_path / "exp", exporter.Settings(), edit={"aspect": "original"})
    assert len(out) == 1 and out[0].read_bytes() == src.read_bytes()


# ----------------------------------------------------------------------------- 5. panorami enormi
def test_load_full_huge_panorama_keeps_exif(monkeypatch, tmp_path):
    src = tmp_path / "pano.jpg"
    _two_tone(120, 40).save(src, exif=_exif().tobytes())
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)   # 4800 px > 2× il limite: "bomb"
    with pytest.raises(Image.DecompressionBombError):
        Image.open(src)
    img, keep = E.load_full(src)
    assert img.size == (120, 40)
    ex = Image.Exif()
    ex.load(keep["exif"])
    _check_exif(ex)
    assert Image.MAX_IMAGE_PIXELS == 1000, "il limite va rimesso com'era"


def test_open_unbounded_restores_limit_under_threads(monkeypatch, tmp_path):
    src = tmp_path / "pano.png"
    Image.new("RGB", (120, 40)).save(src)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    errs = []

    def work():
        try:
            for _ in range(20):
                with E.open_unbounded(src) as im:
                    im.load()
        except Exception as ex:  # noqa: BLE001
            errs.append(ex)
    ts = [threading.Thread(target=work) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs and Image.MAX_IMAGE_PIXELS == 1000


# ----------------------------------------------------------------------------- 6. occhi rossi
def _dot(w, h, cx, cy, r=5) -> Image.Image:
    a = np.full((h, w, 3), 128, np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    a[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = (230, 20, 20)
    return Image.fromarray(a)


def _red_centroid(img: Image.Image) -> tuple[float, float]:
    a = np.asarray(img).astype(float)
    m = (a[..., 0] - np.maximum(a[..., 1], a[..., 2])) > 80
    ys, xs = np.nonzero(m)
    return xs.mean(), ys.mean()


GEOS = [
    ({}, {"straighten": 12.0}),
    ({"straighten": -8.0}, {"straighten": 5.0}),
    ({}, {"vertical": 0.6}),
    ({"vertical": -0.4}, {"horizontal": 0.5, "straighten": 7.0}),
    ({"flip": True, "straighten": 3.0}, {"vertical": 0.3, "crop": [0.1, 0.05, 0.8, 0.9]}),
    ({"crop": [0.2, 0.1, 0.7, 0.8], "horizontal": -0.3}, {"flip": True, "straighten": -10.0}),
]


@pytest.mark.parametrize("before,after", GEOS)
def test_redeye_point_follows_straighten_and_perspective(before, after):
    """Il punto segnato con una geometria resta sullo stesso occhio se poi cambiano raddrizza
    e prospettiva: errore di pochi pixel su una foto da 400 px."""
    photo = _dot(400, 300, 150, 120)
    shown = E.apply_crop(E.geometry_base(photo, before), before)
    cx, cy = _red_centroid(shown)
    p = [cx / shown.width, cy / shown.height, 0.03] + E.redeye_frame(before)
    now = E.apply_crop(E.geometry_base(photo, after), after)
    ex, ey = _red_centroid(now)
    aspect = photo.width / photo.height
    px, py = E.redeye_point(p, after, aspect)
    assert abs(px * now.width - ex) < 3 and abs(py * now.height - ey) < 3, (px * now.width, ex, py * now.height, ey)


def test_redeye_render_corrects_after_straighten():
    photo = _dot(400, 300, 150, 120, r=6)
    e = {"redeye": [[150 / 400, 120 / 300, 0.03] + E.redeye_frame({})]}
    e2 = dict(e, straighten=15.0, vertical=0.4)
    out = E.render(photo, e2)
    a = np.asarray(out).astype(float)
    assert ((a[..., 0] - np.maximum(a[..., 1], a[..., 2])) > 80).sum() == 0, "l'occhio è rimasto rosso"


# ----------------------------------------------------------------------------- 7. stampa con le modifiche
def test_print_copy_applies_edit(no_engine, tmp_path):
    src = tmp_path / "e.jpg"
    _two_tone(600, 400).save(src)
    P.improve(src, tmp_path / "plain.jpg")
    P.improve(src, tmp_path / "edit.jpg", edit={"crop": [0.0, 0.0, 0.5, 1.0], "bw_on": True})
    a, b = Image.open(tmp_path / "plain.jpg"), Image.open(tmp_path / "edit.jpg")
    assert abs(b.width / b.height - 0.75) < 0.01 and abs(a.width / a.height - 1.5) < 0.01
    px = np.asarray(b.convert("RGB")).astype(int)
    assert np.abs(px[..., 0] - px[..., 2]).max() < 12          # in bianco e nero
    P.improve(src, tmp_path / "noop.jpg", edit={"aspect": "original"})
    assert Image.open(tmp_path / "noop.jpg").size == a.size


# ----------------------------------------------------------------------------- 8. memoria in stampa
def test_engine_asked_for_jpeg_and_decoded_reduced(monkeypatch, tmp_path):
    argf = tmp_path / "argv"
    eng = _fake_engine(tmp_path, f"""
        open({str(argf)!r}, "w").write(" ".join(a))
        w, h = Image.open(src).size
        fmt = a[a.index("-f") + 1] if "-f" in a else "png"
        Image.new("RGB", (w * 4, h * 4), (10, 20, 30)).save(out, "JPEG" if fmt == "jpg" else "PNG", quality=100)
    """)
    monkeypatch.setenv("PHOTOSWIPE_REALESRGAN", str(eng))
    loaded = []
    from PIL import JpegImagePlugin
    real_load = JpegImagePlugin.JpegImageFile.load

    def spy(self):
        loaded.append(self.size)
        return real_load(self)
    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "load", spy)
    src = tmp_path / "a.png"
    Image.new("RGB", (300, 200), (10, 20, 30)).save(src)
    P.improve(src, tmp_path / "a_stampa.jpg")
    args = argf.read_text().split()
    assert args[args.index("-f") + 1] == "jpg" and args[args.index("-o") + 1].endswith(".jpg")
    o = Image.open(tmp_path / "a_stampa.jpg")
    assert o.size == (600, 400)
    assert abs(np.asarray(o).reshape(-1, 3).mean(0) - (10, 20, 30)).max() < 4
    big = [s for s in loaded if s[0] > 300]
    assert big and max(w * h for w, h in big) <= 1200 * 800 / 4, loaded   # mai l'uscita 4× intera


# ----------------------------------------------------------------------------- 9. modelli, runtime, stop
def test_models_found_in_bundled_folder(monkeypatch, tmp_path):
    seen = tmp_path / "models_arg"
    eng = _fake_engine(tmp_path, f"""
        open({str(seen)!r}, "w").write(a[a.index("-m") + 1])
        w, h = Image.open(src).size
        Image.new("RGB", (w * 4, h * 4)).save(out)
    """)
    monkeypatch.setenv("PHOTOSWIPE_REALESRGAN", str(eng))   # accanto al motore niente "models"
    bundled = tmp_path / "bundled"
    (bundled / "models").mkdir(parents=True)
    monkeypatch.setattr(P, "_engine_dir", lambda: bundled)
    src = tmp_path / "a.png"
    Image.new("RGB", (60, 40)).save(src)
    P.improve(src, tmp_path / "out.jpg")
    assert Path(seen.read_text()) == bundled / "models"


def test_missing_runtime_reset_each_call(no_engine, monkeypatch, tmp_path):
    src = tmp_path / "a.jpg"
    Image.new("RGB", (80, 60)).save(src)
    monkeypatch.setattr(P, "missing_runtime", True)   # dal giro prima
    text = P.improve(src, tmp_path / "out.jpg")
    assert not P.missing_runtime and "Visual C++" not in text


def test_kill_running_stops_engine(monkeypatch, tmp_path):
    pidf = tmp_path / "pid"
    eng = _fake_engine(tmp_path, f"""
        open({str(pidf)!r}, "w").write(str(os.getpid()))
        time.sleep(60)
    """)
    monkeypatch.setenv("PHOTOSWIPE_REALESRGAN", str(eng))
    src = tmp_path / "a.png"
    Image.new("RGB", (60, 40)).save(src)
    res = {}

    def run():
        try:
            res["ok"] = P.improve(src, tmp_path / "out.jpg")
        except BaseException as ex:  # noqa: BLE001
            res["err"] = ex
    t = threading.Thread(target=run)
    t.start()
    for _ in range(200):
        if pidf.exists() and pidf.read_text():
            break
        time.sleep(0.05)
    t0 = time.time()
    P.kill_running()
    t.join(20)
    assert not t.is_alive() and time.time() - t0 < 15
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidf.read_text()), 0)
    assert "err" in res and not (tmp_path / "out.jpg").exists()   # interrotta: niente copia a metà
    assert not P._RUNNING
