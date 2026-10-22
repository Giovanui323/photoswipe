"""Qualità nel pannello Info: nitidezza (riquadro più nitido) ed esposizione, come aiuto al Sì / No."""
import numpy as np
from PIL import Image, ImageFilter

import metadata
import quality as Q
from scanner import scan
from test_ui import qapp, win  # noqa: F401


def _detail(size=(1600, 1200), seed=0) -> Image.Image:
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 256, (size[1] // 8, size[0] // 8, 3), dtype=np.uint8)
    return Image.fromarray(small).resize(size, Image.Resampling.NEAREST)   # bordi netti dappertutto


def test_sharp_photo_is_sharp_and_blurred_one_is_not():
    img = _detail()
    assert Q.assess(img).focus == "sharp"
    assert Q.assess(img.filter(ImageFilter.GaussianBlur(8))).focus == "blurry"


def test_sharp_subject_on_blurred_background_stays_sharp():
    bg = _detail(seed=1).filter(ImageFilter.GaussianBlur(10))
    bg.paste(_detail((300, 300), seed=2), (650, 450))   # soggetto a fuoco, sfondo sfocato (bokeh)
    assert Q.assess(bg).focus == "sharp"


def test_exposure_warnings():
    white = Image.new("RGB", (800, 600), (255, 255, 255))
    white.paste(_detail((400, 300)), (0, 0))
    text, bad = Q.assess(white).summary()
    assert bad and "bruciate" in text
    text, bad = Q.assess(_detail()).summary()
    assert not bad and "esposizione buona" in text


def test_unreadable_file_gives_no_judgement(tmp_path):
    p = tmp_path / "rotta.jpg"
    p.write_bytes(b"non una foto")
    assert Q.assess_file(p) is None


def test_metadata_carries_quality_for_photos(tmp_path):
    _detail().save(tmp_path / "IMG_0001.JPG", quality=95)
    item = scan(tmp_path)[0]
    m = metadata.read(item)
    assert m.quality is not None and m.quality.focus == "sharp"
    assert "Qualità" in m.quality.info_html()


# ---------------------------------------------------------------------------- raffiche

def _burst_items(tmp_path):
    """Tre foto quasi uguali a 1 s l'una dall'altra (la seconda sfocata), poi una diversa."""
    import os
    from datetime import datetime
    base = _detail(seed=3)
    shots = [base, base.filter(ImageFilter.GaussianBlur(6)), base, _detail(seed=9)]
    for n, img in enumerate(shots):
        p = tmp_path / f"IMG_{n:04d}.JPG"
        img.save(p, quality=95)
        t = datetime(2026, 7, 1, 12, 0, n).timestamp()
        os.utime(p, (t, t))
    items = scan(tmp_path)
    q = {it.id: Q.assess_file(it.image) for it in items}
    return items, lambda it: q.get(it.id)


def test_burst_groups_near_identical_neighbours_only(tmp_path):
    import similar
    items, qof = _burst_items(tmp_path)
    assert similar.burst(items, 1, qof) == [0, 1, 2]
    assert similar.burst(items, 3, qof) == [3]
    assert similar.info_html(items, 3, qof) == ""


def test_burst_info_points_to_the_sharpest(tmp_path):
    import similar
    items, qof = _burst_items(tmp_path)
    assert "è la più nitida" in similar.info_html(items, 0, qof)
    blurred = similar.info_html(items, 1, qof)
    assert "la più nitida è la 1ª" in blurred and "questa è la 2ª" in blurred


def test_burst_breaks_on_unknown_quality_and_time_gap(tmp_path):
    import similar
    items, qof = _burst_items(tmp_path)
    assert similar.burst(items, 0, lambda it: None if it is items[1] else qof(it)) == [0]
    items[2].taken = items[1].taken + similar.GAP * 2
    assert similar.burst(items, 0, qof) == [0, 1]


def test_info_panel_shows_quality_and_points_to_the_sharpest_of_a_burst(qapp, win, tmp_path):
    from test_ui import open_folder, wait
    (tmp_path / "raffica").mkdir()
    _burst_items(tmp_path / "raffica")
    open_folder(qapp, win, tmp_path / "raffica")
    win.jump_to(1)   # la foto sfocata della raffica
    card = win.info_card_text
    assert wait(qapp, lambda: "foto simili" in card.text()), card.text()
    assert "Sfocata" in card.text() and "la più nitida è la 1ª" in card.text()


def test_16_bit_gray_scan_is_judged_like_the_8_bit_one():
    g8 = _detail().convert("L")
    g16 = Image.fromarray(np.asarray(g8, np.uint16) * 257)   # I;16, come una scansione a 16 bit
    assert g16.mode == "I;16"
    assert Q.assess(g16).summary() == Q.assess(g8).summary()   # prima: "bruciate 99%"
