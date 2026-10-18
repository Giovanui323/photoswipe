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
