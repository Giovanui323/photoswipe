"""Pipeline delle immagini: copia per la stampa (printprep) e caricamento a piena risoluzione
(edits.load_full) con formati difficili: 16 bit, profili CMYK / grigi, DNG, PNG con orientamento,
motore Real-ESRGAN che esce enorme o si rompe, foto alte o larghe 1 px, occhi rossi e capovolgi."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import textwrap
import time
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PHOTOSWIPE_LANG", "it")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest
from PIL import Image, ImageCms

import edits as E
import printprep as P

CMYK_ICC = Path("/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc")
PY = sys.executable


@pytest.fixture
def no_engine(monkeypatch, tmp_path):
    """Nessun motore: si usa Lanczos (niente Real-ESRGAN vero nei test, è lento)."""
    monkeypatch.setenv("PHOTOSWIPE_REALESRGAN", str(tmp_path / "manca-il-motore"))


def _fake_engine(tmp_path: Path, body: str) -> Path:
    """Finto realesrgan-ncnn-vulkan: uno script Python con gli stessi argomenti."""
    f = tmp_path / "fake_engine.py"
    f.write_text(f"#!{PY}\n" + textwrap.dedent("""
        import os, sys, time
        a = sys.argv; src = a[a.index("-i") + 1]; out = a[a.index("-o") + 1]
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
    """) + textwrap.dedent(body))
    f.chmod(0o755)
    return f


def _srgb_icc() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _gray16(path: Path, w: int = 200, h: int = 150) -> Path:
    a = np.linspace(0, 65535, w * h).reshape(h, w).astype(np.uint16)
    Image.fromarray(a).save(path)
    return path


# ----------------------------------------------------------------------------- 1. motore
def test_engine_huge_output_is_opened_and_resized(monkeypatch, tmp_path):
    """Il motore esce sempre a 4×: un PNG oltre il limite "decompression bomb" di PIL non deve
    far fallire la copia, ma va aperto (file temporaneo nostro) e riportato alla misura giusta."""
    eng = _fake_engine(tmp_path, """
        w, h = Image.open(src).size
        sys.stderr.write("50.00%\\n100.00%\\n")
        Image.new("RGB", (w * 4, h * 4), (0, 0, 0)).save(out)
    """)
    monkeypatch.setenv("PHOTOSWIPE_REALESRGAN", str(eng))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 5000)   # 240×160 dal motore = oltre 2× il limite
    src = tmp_path / "a.png"
    Image.new("RGB", (60, 40), (100, 120, 140)).save(src)
    prog = []
    P.improve(src, tmp_path / "out" / "a_stampa.jpg", progress=prog.append)
    o = Image.open(tmp_path / "out" / "a_stampa.jpg")
    assert o.size == (120, 80)
    assert np.asarray(o.convert("L")).mean() < 20, "si è ripiegato su Lanczos invece di usare il motore"
    assert prog and prog[-1] == 1.0
    assert Image.MAX_IMAGE_PIXELS == 5000, "il limite di PIL va rimesso com'era"


def test_engine_error_mid_run_falls_back_and_kills(monkeypatch, tmp_path):
    """Un errore qualsiasi a metà (qui dal callback di avanzamento): si ripiega su Lanczos e il
    motore non resta acceso."""
    pidf = tmp_path / "pid"
    eng = _fake_engine(tmp_path, f"""
        open({str(pidf)!r}, "w").write(str(os.getpid()))
        sys.stderr.write("10.00%\\n"); sys.stderr.flush()
        time.sleep(60)
    """)
    monkeypatch.setenv("PHOTOSWIPE_REALESRGAN", str(eng))
    src = tmp_path / "a.png"
    Image.new("RGB", (60, 40), (100, 120, 140)).save(src)

    def boom(_f):
        raise RuntimeError("callback rotto")

    t = time.time()
    P.improve(src, tmp_path / "a_stampa.jpg", progress=boom)
    assert time.time() - t < 30
    o = Image.open(tmp_path / "a_stampa.jpg")
    assert o.size == (120, 80)
    assert abs(np.asarray(o).reshape(-1, 3).mean(0) - (100, 120, 140)).max() < 8   # Lanczos
    pid = int(pidf.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_engine_garbage_output_falls_back(monkeypatch, tmp_path):
    eng = _fake_engine(tmp_path, """
        open(out, "wb").write(b"non sono un png")
    """)
    monkeypatch.setenv("PHOTOSWIPE_REALESRGAN", str(eng))
    src = tmp_path / "a.png"
    Image.new("RGB", (60, 40), (100, 120, 140)).save(src)
    P.improve(src, tmp_path / "a_stampa.jpg")
    assert Image.open(tmp_path / "a_stampa.jpg").size == (120, 80)


# ----------------------------------------------------------------------------- 2. ICC in stampa
def test_print_copy_keeps_rgb_icc(no_engine, tmp_path):
    icc = _srgb_icc()
    src = tmp_path / "p.jpg"
    Image.new("RGB", (60, 40), (200, 30, 30)).save(src, icc_profile=icc)
    P.improve(src, tmp_path / "p_stampa.jpg")
    assert Image.open(tmp_path / "p_stampa.jpg").info.get("icc_profile") == icc


# ----------------------------------------------------------------------------- 3. 16 bit
@pytest.mark.parametrize("mode", ["I;16", "I;16B", "I"])
def test_to_rgb_16bit_modes(mode):
    a = np.linspace(0, 65535, 64 * 32).reshape(32, 64)
    if mode == "I;16":
        im = Image.fromarray(a.astype(np.uint16))
    elif mode == "I;16B":
        im = Image.fromarray(a.astype(np.uint16)).convert("I").convert("I;16B")
    else:
        im = Image.fromarray(a.astype(np.int32))
    assert im.mode == mode
    rgb, _icc = E.to_rgb(im)
    x = np.asarray(rgb)[..., 0].astype(float)
    assert rgb.mode == "RGB"
    assert abs(x.mean() - 127.5) < 3
    assert x.min() == 0 and x.max() == 255


def test_load_full_16bit_png(tmp_path):
    img, _keep = E.load_full(_gray16(tmp_path / "g16.png"))
    assert abs(np.asarray(img).mean() - 127.5) < 3


def test_print_copy_16bit_png(no_engine, tmp_path):
    P.improve(_gray16(tmp_path / "g16.png"), tmp_path / "g16_stampa.jpg")
    m = np.asarray(Image.open(tmp_path / "g16_stampa.jpg").convert("L")).mean()
    assert abs(m - 127.5) < 6, m


# ----------------------------------------------------------------------------- 4. ICC non RGB
def test_gray_profile_not_copied_into_rgb(tmp_path):
    lab = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()   # profilo non RGB
    src = tmp_path / "g.jpg"
    Image.new("L", (40, 30), 120).save(src, icc_profile=lab)
    img, keep = E.load_full(src)
    assert img.mode == "RGB" and not keep.get("icc_profile")
    E.save_edited(img, tmp_path / "out.jpg", keep)
    assert not Image.open(tmp_path / "out.jpg").info.get("icc_profile")


@pytest.mark.skipif(not CMYK_ICC.is_file(), reason="profilo CMYK di sistema (macOS)")
def test_cmyk_converted_with_profile(tmp_path):
    src = tmp_path / "c.jpg"
    Image.new("CMYK", (40, 30), (0, 200, 200, 0)).save(src, icc_profile=CMYK_ICC.read_bytes())
    img, keep = E.load_full(src)
    E.save_edited(img, tmp_path / "out.jpg", keep)
    o = Image.open(tmp_path / "out.jpg")
    icc = o.info.get("icc_profile")
    assert not icc or icc[16:20] == b"RGB "
    r, g, b = o.convert("RGB").getpixel((5, 5))
    assert r > g + 80 and r > b + 80   # resta rosso
    # e con il profilo CMYK: diverso dalla conversione ingenua di PIL (255, 55, 55)
    assert (r, g, b) != Image.new("CMYK", (1, 1), (0, 200, 200, 0)).convert("RGB").getpixel((0, 0))


def test_rgb_profile_kept(tmp_path):
    icc = _srgb_icc()
    src = tmp_path / "s.jpg"
    Image.new("RGB", (40, 30), (10, 200, 10)).save(src, icc_profile=icc)
    _img, keep = E.load_full(src)
    assert keep.get("icc_profile") == icc


# ----------------------------------------------------------------------------- 5. DNG
class _FakeRaw:
    def __init__(self, size):
        self.size = size

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def postprocess(self, **kw):
        w, h = self.size
        if kw.get("half_size"):
            w, h = w // 2, h // 2
        a = np.zeros((h, w, 3), np.uint8)
        a[...] = (90, 100, 110)
        return a

    def extract_thumb(self):
        raise RuntimeError("niente anteprima")


def _fake_rawpy(monkeypatch, size=(1200, 800), fail=False):
    m = types.ModuleType("rawpy")

    def imread(path):
        if fail:
            raise RuntimeError("rawpy rotto")
        return _FakeRaw(size)

    m.imread = imread
    m.LibRawNoThumbnailError = m.LibRawUnsupportedThumbnailError = RuntimeError
    monkeypatch.setitem(sys.modules, "rawpy", m)


def _dng(tmp_path: Path) -> Path:
    f = tmp_path / "x.dng"   # PIL lo apre come TIFF e vede solo la miniatura
    Image.new("RGB", (256, 144), (255, 0, 0)).save(f, "TIFF")
    return f


def test_load_full_dng_full_resolution(monkeypatch, tmp_path):
    _fake_rawpy(monkeypatch)
    img, _keep = E.load_full(_dng(tmp_path))
    assert img.size == (1200, 800)
    assert img.getpixel((3, 3)) == (90, 100, 110)


def test_load_full_dng_without_rawpy_falls_back(monkeypatch, tmp_path):
    _fake_rawpy(monkeypatch, fail=True)
    img, _keep = E.load_full(_dng(tmp_path))   # meglio la miniatura che niente
    assert img.mode == "RGB" and img.size == (256, 144)


def test_print_copy_dng_full_resolution(no_engine, monkeypatch, tmp_path):
    _fake_rawpy(monkeypatch, size=(4000, 3000))
    P.improve(_dng(tmp_path), tmp_path / "x_stampa.jpg")
    assert min(Image.open(tmp_path / "x_stampa.jpg").size) >= 3000


# ----------------------------------------------------------------------------- 6. orientamento
def _qt_size(path: Path):
    from PySide6.QtGui import QImageReader
    r = QImageReader(str(path))
    r.setAutoTransform(True)
    q = r.read()
    return q.width(), q.height()


@pytest.mark.parametrize("ext", [".png", ".jpg"])
def test_load_full_orientation_matches_preview(ext, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    ex = Image.Exif()
    ex[0x0112] = 6
    src = tmp_path / f"o6{ext}"
    Image.new("RGB", (60, 40), (200, 10, 10)).save(src, exif=ex.tobytes())
    img, keep = E.load_full(src)
    assert img.size == _qt_size(src)   # come l'anteprima: i ritagli finiscono al posto giusto
    E.save_edited(img, tmp_path / "out.jpg", keep)
    assert Image.open(tmp_path / "out.jpg").getexif().get(0x0112, 1) == 1


# ----------------------------------------------------------------------------- 7. occhi rossi
def _red_dot_photo(w=200, h=100, cx=50, cy=50, r=6) -> Image.Image:
    a = np.full((h, w, 3), 128, np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    a[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = (230, 20, 20)
    return Image.fromarray(a)


def _redness(img: Image.Image, x: float, y: float) -> float:
    a = np.asarray(img).astype(float)
    px = a[round(y * (img.height - 1)), round(x * (img.width - 1))]
    return px[0] - max(px[1], px[2])


def test_redeye_follows_flip_and_crop():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from editpanel import RegolaPanel, RitagliaPanel
    photo = _red_dot_photo()          # occhio a (0,25; 0,5) della foto
    geo = {"crop": [0.1, 0.0, 0.8, 1.0]}
    # clic sull'occhio, nella foto ritagliata: x = (0,25 − 0,1) / 0,8
    reg = RegolaPanel()
    reg.set_edit(dict(geo))
    reg.add_redeye((0.25 - 0.1) / 0.8, 0.5)
    e = E.clean(reg.edit)
    out = E.render(photo, e)
    assert _redness(out, (0.25 - 0.1) / 0.8, 0.5) < 30
    # Capovolgi: l'occhio va dall'altra parte, la correzione lo segue
    rit = RitagliaPanel()
    rit.set_draft(e)
    rit._flip()
    e2 = dict(e)
    e2.update(rit.draft)
    out2 = E.render(photo, e2)
    x2 = 1 - (0.25 - 0.1) / 0.8   # riquadro specchiato: (1 − 0,25 − 0,1) / 0,8
    assert _redness(out2, x2, 0.5) < 30, "l'occhio capovolto non è più corretto"
    # e se poi cambia il ritaglio, la correzione resta sull'occhio
    e3 = dict(e2, crop=[0.5, 0.0, 0.5, 1.0])
    out3 = E.render(photo, e3)
    assert _redness(out3, (0.75 - 0.5) / 0.5, 0.5) < 30


def test_old_redeye_points_unchanged():
    photo = _red_dot_photo()
    out = E.render(photo, {"redeye": [[0.25, 0.5, 0.04]]})
    assert _redness(out, 0.25, 0.5) < 30


# ----------------------------------------------------------------------------- 8. foto sottili
THIN = [(1, 1), (1, 500), (500, 1), (2, 2), (2, 300)]
AUTO = ["classic_auto_light", "classic_auto_color", "classic_auto_wb", "auto_levels", "auto_sharpen",
        "auto_noise", "auto_definition", "auto_straighten", "auto_perspective", "auto_deblur",
        "learned_auto", "estimate_blur", "auto_features"]


@pytest.mark.parametrize("size", THIN)
@pytest.mark.parametrize("fn", AUTO)
def test_auto_on_thin_images(fn, size):
    r = getattr(E, fn)(Image.new("RGB", size, (90, 100, 110)))
    if isinstance(r, dict):
        assert all(np.isfinite(v) for v in r.values())


# ----------------------------------------------------------------------------- HEIC / illeggibili
@pytest.mark.skipif(not shutil.which("sips"), reason="serve sips (macOS) per creare un HEIC")
def test_print_copy_heic_via_qt(no_engine, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    jpg = tmp_path / "h.jpg"
    Image.new("RGB", (64, 48), (200, 30, 30)).save(jpg)
    heic = tmp_path / "h.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(jpg), "--out", str(heic)], capture_output=True)
    if not heic.is_file():
        pytest.skip("sips non scrive HEIC")
    P.improve(heic, tmp_path / "h_stampa.jpg")
    assert Image.open(tmp_path / "h_stampa.jpg").size == (128, 96)


def test_print_copy_unreadable_clear_error(no_engine, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    bad = tmp_path / "rotta.heic"
    bad.write_bytes(b"\0" * 100)
    with pytest.raises(RuntimeError, match="rotta.heic"):
        P.improve(bad, tmp_path / "rotta_stampa.jpg")
    assert not (tmp_path / "rotta_stampa.jpg").exists()
