"""Test per i18n, datefmt, metadata.fmt_gps, exporter.fmt_when, frames._exif, quality e similar."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import datefmt  # noqa: E402
import exporter  # noqa: E402
import frames  # noqa: E402
import i18n  # noqa: E402
import metadata  # noqa: E402
import quality  # noqa: E402
import similar  # noqa: E402
import theme  # noqa: E402
from scanner import Item  # noqa: E402


def test_i18n_new_translations(monkeypatch):
    monkeypatch.setattr(i18n, "LANG", "en")
    assert i18n.current_lang() == "en"
    assert i18n.tr("Livelli") == "Levels"
    assert i18n.tr("Vignettatura") == "Vignette"
    assert i18n.tr("alle") == "at"
    assert i18n.tr("fotogramma") == "frame"
    assert i18n.tr("verticali corrette ({deg:+d}°)", deg=5) == "verticals corrected (+5°)"
    assert i18n.tr("circa {left} s rimanenti", left=12) == "about 12 s remaining"
    assert i18n.tr("stampa fino a {hint}", hint="20×30 cm") == "prints up to 20×30 cm"
    assert i18n.tr("⚠ bassa risoluzione: stampa max {hint}", hint="10×15 cm") == "⚠ low resolution: max print 10×15 cm"
    assert i18n.tr("  ·  ne mancano {n}", n=4) == "  ·  4 left"
    assert i18n.tr("  ·  tutte decise") == "  ·  all decided"
    assert (
        i18n.tr("✓ {yes} approvate    ✗ {no} scartate    ↪ {skip} saltate", yes=3, no=2, skip=1)
        == "✓ 3 approved    ✗ 2 rejected    ↪ 1 skipped"
    )
    assert i18n.tr("Sfoglia l'album delle approvate") == "Browse approved album"
    assert i18n.tr("ORIGINALE") == "ORIGINAL"
    assert i18n.tr("COPIA PER LA STAMPA") == "PRINT COPY"


def test_datefmt_english_and_italian(monkeypatch):
    d = datetime(2024, 1, 15, 9, 5, 3)  # Monday, January 15
    monkeypatch.setattr(i18n, "LANG", "it")
    assert datefmt.fmt_datetime(d) == "lun 15 gen 2024   09:05:03"
    monkeypatch.setattr(i18n, "LANG", "en")
    assert datefmt.fmt_datetime(d) == "Mon 15 Jan 2024   09:05:03"


def test_metadata_fmt_gps_west_localized(monkeypatch):
    monkeypatch.setattr(i18n, "LANG", "it")
    assert metadata.fmt_gps(40.7128, -74.0060).endswith("O")
    monkeypatch.setattr(i18n, "LANG", "en")
    assert metadata.fmt_gps(40.7128, -74.0060).endswith("W")


def test_exporter_fmt_when_localized(monkeypatch):
    iso = "2024-06-15T14:30:00"
    monkeypatch.setattr(i18n, "LANG", "it")
    assert exporter.fmt_when(iso) == "15/06/2024 alle 14:30"
    monkeypatch.setattr(i18n, "LANG", "en")
    assert exporter.fmt_when(iso) == "15/06/2024 at 14:30"


def test_frames_exif_localized(monkeypatch):
    meta = frames.FrameMeta(
        taken_local=datetime(2024, 6, 15, 12, 0, 0),
        offset=timedelta(hours=2),
        make="Apple",
        model="iPhone",
        source="IMG_0001.MOV",
        frame=4,
    )
    monkeypatch.setattr(i18n, "LANG", "it")
    assert b"IMG_0001.MOV - fotogramma 5" in frames._exif(meta)

    monkeypatch.setattr(i18n, "LANG", "en")
    assert b"IMG_0001.MOV - frame 5" in frames._exif(meta)


def test_quality_and_similar_use_theme_colors(tmp_path):
    q_good = quality.Quality(sharpness=3.5, highlights=0.0, shadows=0.0, dhash=0)
    q_bad = quality.Quality(sharpness=1.0, highlights=0.1, shadows=0.0, dhash=0)
    assert theme.C["text_ok"] in q_good.info_html()
    assert theme.C["text_warn"] in q_bad.info_html()

    t0 = datetime(2024, 6, 15, 12, 0, 0)
    it1 = Item(kind="photo", id="1.jpg", image=tmp_path / "1.jpg", taken=t0)
    it2 = Item(kind="photo", id="2.jpg", image=tmp_path / "2.jpg", taken=t0 + timedelta(seconds=2))
    qmap = {"1.jpg": q_good, "2.jpg": q_bad}
    assert theme.C["text_ok"] in similar.info_html([it1, it2], 0, lambda it: qmap[it.id])
    assert theme.C["text_warn"] in similar.info_html([it1, it2], 1, lambda it: qmap[it.id])
