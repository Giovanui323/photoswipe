"""Stampabilità: giudizio per formato, e copia migliorata per la stampa (300 dpi, originale intatto)."""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import printprep  # noqa: E402


def test_verdict_levels():
    assert printprep.verdict(6000, 4000)[0] == "ottima"       # 30 × 45 a 300 dpi
    assert printprep.verdict(2000, 3000)[0] == "buona"        # 15 × 20 a 300 dpi
    assert printprep.verdict(1500, 1000)[0] == "discreta"     # solo 200 dpi
    assert printprep.verdict(800, 600)[0] == "scarsa"


def test_scale_is_capped():
    # sempre tra 1× e il limite: il formato più grande raggiungibile senza ingrandire più di 2×
    for w, h in ((6000, 4000), (800, 600)):
        assert 1 < printprep._scale(w, h) <= printprep.MAX_UPSCALE
    assert printprep._scale(12000, 9000) == 1.0              # già 50 × 70 a 300 dpi: nessun ingrandimento


def test_improve_writes_copy_and_keeps_original(tmp_path):
    src = tmp_path / "foto.jpg"
    Image.new("RGB", (800, 600), "teal").save(src, "JPEG")
    before = src.read_bytes()
    dst = tmp_path / "Stampa" / "foto_stampa.jpg"
    desc = printprep.improve(src, dst)
    assert dst.exists() and src.read_bytes() == before        # l'originale non si tocca
    with Image.open(dst) as out:
        assert out.info.get("dpi", (0, 0))[0] == 300
        assert out.width >= 800 and out.height >= 600          # mai più piccola
    assert "px" in desc


def test_windows_without_vc_runtime_falls_back_and_explains(tmp_path, monkeypatch):
    """Su Windows senza il Visual C++ Redistributable il motore non parte: si usa Lanczos e lo si dice."""
    import subprocess
    import sys
    from PIL import Image
    import printprep
    src = tmp_path / "a.jpg"
    Image.new("RGB", (800, 600), (120, 90, 60)).save(src)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(printprep, "realesrgan_bin", lambda: tmp_path / "realesrgan-ncnn-vulkan.exe")

    class Missing:   # il motore esce subito con 0xC0000135: DLL non trovata
        stderr = iter([])

        def wait(self):
            return -1073741515

        def kill(self):
            pass
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Missing())
    monkeypatch.setattr(printprep, "missing_runtime", False)
    text = printprep.improve(src, tmp_path / "out.jpg")
    assert (tmp_path / "out.jpg").exists()
    assert "Visual C++" in text and printprep.missing_runtime


def test_missing_engine_falls_back_and_says_so(tmp_path, monkeypatch):
    """Motore assente o bloccato (es. Gatekeeper su macOS): la copia si fa lo stesso, e lo si dice."""
    from PIL import Image
    import printprep
    src = tmp_path / "a.jpg"
    Image.new("RGB", (800, 600), (120, 90, 60)).save(src)
    monkeypatch.setattr(printprep, "realesrgan_bin", lambda: tmp_path / "non_c_e")
    text = printprep.improve(src, tmp_path / "out.jpg")
    assert (tmp_path / "out.jpg").exists()
    assert "Real-ESRGAN" in text and printprep.simple_upscale


def test_print_copies_of_same_name_photos_do_not_overwrite(tmp_path):
    import printprep
    from scanner import Item
    a = Item("photo", "card1/IMG_0001.JPG", image=tmp_path / "card1" / "IMG_0001.JPG")
    b = Item("photo", "card2/IMG_0001.JPG", image=tmp_path / "card2" / "IMG_0001.JPG")
    top = Item("photo", "IMG_0001.JPG", image=tmp_path / "IMG_0001.JPG")
    paths = {printprep.copy_path(tmp_path, it) for it in (a, b, top)}
    assert len(paths) == 3
    assert printprep.copy_path(tmp_path, top) == tmp_path / "Stampa" / "IMG_0001_stampa.jpg"   # come prima
