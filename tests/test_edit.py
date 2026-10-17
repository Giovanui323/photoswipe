"""Regola e Ritaglia: pannelli, ritaglio con OK / Annulla, export della foto modificata."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import edits as E  # noqa: E402
import exporter  # noqa: E402
from test_ui import (PHOTO1, PHOTO2, click, exported, exports_done, go, open_folder, press,  # noqa: E402,F401
                     pump, qapp, sd, sd_template, wait, win)
from PySide6.QtCore import Qt  # noqa: E402


# ------------------------------------------------------------------ motore
def test_render_empty_edit_is_identity():
    im = Image.new("RGB", (40, 30), (10, 120, 200))
    assert E.render(im, {}) is im
    assert E.is_empty({"exposure": 0.0, "crop": [0, 0, 1, 1], "aspect": "free"})


def test_crop_and_tone_change_pixels_and_size():
    im = Image.fromarray((np.random.default_rng(1).random((300, 400, 3)) * 255).astype(np.uint8))
    out = E.render(im, {"crop": [0.25, 0.0, 0.5, 1.0], "exposure": 0.5})
    assert out.size == (200, 300)
    assert np.asarray(out, np.float32).mean() > np.asarray(im, np.float32)[:, 100:300].mean()
    bw = np.asarray(E.render(im, {"bw_on": True}), np.int16)
    assert np.abs(bw[..., 0] - bw[..., 1]).max() <= 1   # grigio


def test_every_section_renders():
    im = Image.fromarray((np.random.default_rng(2).random((120, 160, 3)) * 255).astype(np.uint8))
    e = {k: 0.3 for k in E.DEFAULTS if k not in ("lv_white", "lv_out_white", "redeye_size")}
    e.update(bw_on=True, flip=True, straighten=7, redeye=[[0.5, 0.5, 0.05]])
    out = E.render(im, e)
    assert out.mode == "RGB" and out.size[0] < 160


def test_aspect_fit():
    c = E.fit_aspect(None, 1.0, 400, 200)
    assert abs(c[2] * 400 - c[3] * 200) < 1e-6 and abs(c[3] - 1) < 1e-9


def test_session_keeps_edits(tmp_path):
    root, out = tmp_path / "src", tmp_path / "out"
    root.mkdir()
    s = exporter.Session(root, out)
    s.set_edit("a.jpg", {"exposure": 0.4, "crop": [0, 0, 1, 1]})
    assert exporter.Session(root, out).edits == {"a.jpg": {"exposure": 0.4}}
    s.set_edit("a.jpg", {})
    assert exporter.Session(root, out).edits == {}


# ------------------------------------------------------------------ interfaccia
def test_tabs_info_regola_ritaglia(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    assert win.side_seg.isVisible() and win.side_tab == "info"
    win.on_side_tab("regola")
    assert win.side_pages.currentIndex() == 1
    pump(qapp, 0.4)
    assert len(win.regola.scrubbers["light"].thumbs) == 5
    assert "/ 8 già fatte" in win.done_label.text()


def test_regola_then_yes_exports_modified(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.on_side_tab("regola")
    win.regola.bars["exposure"].changed.emit(-0.8)   # come trascinare il cursore
    win.regola.bars["exposure"].set_value(-0.8)
    win.regola._set("exposure", -0.8)
    pump(qapp, 0.3)
    # prima di OK è solo una bozza: Sì è bloccato e la sessione non cambia
    assert win.tone_draft is not None and not win.decision_bar.isEnabled()
    win.decide("yes")
    assert exported(win) == [] and win.current().id not in win.session.edits
    win.regola_ok()
    assert win.session.edits[win.current().id]["exposure"] == -0.8
    assert win.btn_discard.isEnabled() and "✓ Sì" in win.edit_badge.text()
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert exported(win) == [PHOTO1]
    src = next((sd / "DCIM").rglob(PHOTO1))
    out = win.export_dir / PHOTO1
    assert out.read_bytes() != src.read_bytes()
    a = np.asarray(Image.open(out), np.float32).mean()
    b = np.asarray(Image.open(src), np.float32).mean()
    assert a < b - 10   # più scura


def test_crop_needs_ok_and_blocks_choices(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    name = win.current().main.name
    win.on_side_tab("ritaglia")
    assert win.crop_draft is not None and win.image_view.crop_mode
    assert win.decision_bar.isEnabled()      # aperto senza cambiare nulla: niente conferma
    assert not win.confirm_row.isVisible()
    win.ritaglia._set_aspect("square")
    assert abs(win.image_view.crop[2] * 1200 - win.image_view.crop[3] * 900) < 2
    assert not win.decision_bar.isEnabled()  # ora sì: riquadro cambiato
    press(qapp, win, Qt.Key_Y)               # Sì bloccato finché non si conferma
    win.decide("yes")
    assert win.current().main.name == name and exported(win) == []
    win.crop_ok()
    assert win.crop_draft is None and win.decision_bar.isEnabled()
    assert win.side_tab == "info"
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert Image.open(win.export_dir / PHOTO1).size == (900, 900)


def test_crop_cancel_keeps_original(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO2)
    win.on_side_tab("ritaglia")
    win.ritaglia._set_aspect("16:9")
    win.crop_cancel()
    assert win.crop_draft is None and E.is_empty(win.item_edit())
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert (win.export_dir / PHOTO2).read_bytes() == next((sd / "DCIM").rglob(PHOTO2)).read_bytes()


def test_discard_edits_button(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.on_side_tab("regola")
    win.regola._set("saturation", 0.5)
    win.regola_ok()
    assert not E.is_empty(win.item_edit())
    click(qapp, win, win.btn_discard)
    assert E.is_empty(win.item_edit()) and not win.btn_discard.isEnabled()


# ------------------------------------------------------------------ automatico
def _horizon_scene(w=1200, h=800):
    from PIL import ImageDraw
    im = Image.new("RGB", (w, h), (150, 190, 230))
    d = ImageDraw.Draw(im)
    d.rectangle([0, h * 0.55, w, h], fill=(40, 90, 120))
    for x in (250, 600, 950):
        d.rectangle([x, h * 0.2, x + 14, h * 0.95], fill=(60, 50, 40))
    return im


def test_auto_straighten_undoes_tilt():
    base = _horizon_scene()
    for ang in (-6, 3):
        tilted = E.geometry_base(base, {"straighten": -ang})   # foto storta di ang gradi
        fix = E.auto_straighten(tilted)
        assert abs(fix - ang) < 0.5, (ang, fix)
        assert abs(E.auto_straighten(E.geometry_base(tilted, {"straighten": fix}))) < 0.5
    assert E.auto_straighten(base) == 0.0


def test_auto_perspective_makes_verticals_parallel():
    from PIL import ImageDraw
    w, h = 900, 1200
    im = Image.new("RGB", (w, h), (200, 200, 195))
    d = ImageDraw.Draw(im)
    for xb in (120, 320, 580, 780):   # palazzo visto dal basso: linee che convergono in alto
        d.line([(w / 2 + (xb - w / 2) * 0.7, 0), (xb, h)], fill=(30, 30, 30), width=6)
    p = E.auto_perspective(im)
    assert p.get("vertical", 0) > 0.3
    tilts = [t for _f, t, *_ in E.find_lines(E.geometry_base(im, p), families=("v",))]
    assert max(abs(t) for t in tilts) < 2.0
    assert E.auto_perspective(_horizon_scene()) == {}   # pali già paralleli: niente


def test_auto_wb_removes_cast():
    rng = np.random.default_rng(5)
    arr = np.zeros((400, 600, 3), np.float32)
    for i in range(0, 400, 50):
        for j in range(0, 600, 50):
            arr[i:i + 50, j:j + 50] = rng.uniform(0.1, 0.9, 3) if rng.random() > 0.2 \
                else rng.uniform(0.2, 0.9)
    gray = np.ptp(arr, axis=-1) < 1e-6
    warm = Image.fromarray((np.clip(arr ** 2.2 * [1.25, 1.0, 0.7], 0, 1) ** (1 / 2.2) * 255).astype(np.uint8))
    out = np.asarray(E.render(warm, E.auto_wb(warm)), np.float32)[gray].mean(0)
    before = np.asarray(warm, np.float32)[gray].mean(0)
    assert np.ptp(out) < np.ptp(before) * 0.5


def test_auto_light_brightens_dark_and_leaves_good_photo():
    base = _horizon_scene()
    dark = Image.fromarray((np.asarray(base, np.float32) * 0.4).astype(np.uint8))
    e = E.auto_light(dark)
    assert e.get("exposure", 0) > 0.3
    assert np.asarray(E.render(dark, e)).mean() > np.asarray(dark).mean() * 1.4
    assert abs(E.auto_light(base).get("exposure", 0)) < 0.2


def test_auto_buttons_in_app(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.on_side_tab("regola")
    for sec in ("light", "color", "wb", "levels", "definition", "noise", "sharpen", "deblur", "bw"):
        win.on_auto(sec)   # nessun errore, e la sezione risulta toccata se serve
    win.on_side_tab("ritaglia")          # bloccato: prima OK o Annulla
    assert win.side_tab == "regola"
    win.regola_ok()
    win.on_side_tab("ritaglia")
    win.crop_auto()
    assert win.crop_draft is not None
    win.crop_ok()
    assert win.crop_draft is None


def test_regola_cancel_restores(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.on_side_tab("regola")
    win.regola._set("contrast", 0.5)
    win.cancel_edit()
    assert win.tone_draft is None and E.is_empty(win.item_edit()) and win.decision_bar.isEnabled()
    assert E.get(win.regola.edit, "contrast") == 0


def test_auto_deblur_only_when_blurred():
    from PIL import ImageDraw, ImageFilter
    rng = np.random.default_rng(1)
    im = Image.new("RGB", (1600, 1100), (200, 200, 200))
    d = ImageDraw.Draw(im)
    for _ in range(250):
        x, y = rng.integers(0, 1600), rng.integers(0, 1100)
        d.rectangle([x, y, x + rng.integers(10, 150), y + rng.integers(10, 150)],
                    fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    assert E.auto_deblur(im) == {}
    soft = im.filter(ImageFilter.GaussianBlur(2.5))
    a = E.auto_deblur(soft)
    assert a and a["deblur"] > 0.4
    g = lambda m: float(np.hypot(*np.gradient(np.asarray(m.convert("L"), np.float32))).mean())  # noqa: E731
    assert g(E.render(soft, a)) > g(soft) * 1.1


def test_open_crop_without_changes_does_not_block(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.on_side_tab("ritaglia")
    win.on_side_tab("info")                  # si esce senza OK
    assert win.crop_draft is None and win.side_tab == "info"
    win.on_side_tab("ritaglia")
    click(qapp, win, win.btn_yes)            # Sì direttamente: chiude Ritaglia ed esporta l'originale
    exports_done(qapp, win)
    assert win.crop_draft is None and not win.image_view.crop_mode
    assert (win.export_dir / PHOTO1).read_bytes() == next((sd / "DCIM").rglob(PHOTO1)).read_bytes()
    win.on_side_tab("regola")
    win.regola._set("contrast", 0.3)
    win.regola._set("contrast", 0.0)         # tornato com'era: niente da confermare
    assert win.decision_bar.isEnabled()
