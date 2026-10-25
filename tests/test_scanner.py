"""Test per scanner, cloud, stills, frames, edits e selftest."""
from __future__ import annotations

import collections
import concurrent.futures
import errno
import io
import struct
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cloud  # noqa: E402
import edits  # noqa: E402
import exporter  # noqa: E402
import frames  # noqa: E402
import scanner  # noqa: E402
import selftest  # noqa: E402
import stills  # noqa: E402
from scanner import Item, scan  # noqa: E402


def _save_jpeg(path: Path, color=(120, 40, 200)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[306] = "2024:06:15 12:34:56"
    exif.get_ifd(0x8769)[36867] = "2024:06:15 12:34:56"
    Image.new("RGB", (16, 16), color).save(path, "JPEG", exif=exif)
    return path


def test_same_content_dataless_returns_false(tmp_path, monkeypatch):
    a = _save_jpeg(tmp_path / "card1" / "IMG_0001.JPG", (10, 20, 30))
    b = tmp_path / "card2" / "IMG_0001.JPG"
    b.parent.mkdir(parents=True, exist_ok=True)
    b.write_bytes(a.read_bytes())

    monkeypatch.setattr(cloud, "is_local", lambda p: False)
    assert scanner._same_content(a, b) is False
    items = scan(tmp_path)
    assert len(items) == 2


def test_duplicates_tracked_and_moved_to_trash(tmp_path):
    root = tmp_path / "src"
    orig = _save_jpeg(root / "DCIM" / "100" / "IMG_0001.JPG")
    dup = root / "backup" / "IMG_0001.JPG"
    dup.parent.mkdir(parents=True, exist_ok=True)
    dup.write_bytes(orig.read_bytes())

    items = scan(root)
    assert len(items) == 1
    item = items[0]
    assert dup.resolve() in item.duplicates
    assert dup.resolve() in item.companion_files()
    assert dup.resolve() in item.all_files()

    plan = exporter.plan_trash(item, root)
    srcs = {Path(pair[0]) for pair in plan}
    assert orig.resolve() in srcs
    assert dup.resolve() in srcs

    moved = exporter.move_to_trash(item, root)
    assert not orig.exists() and not dup.exists()
    assert (root / exporter.TRASH_DIR / "DCIM" / "100" / "IMG_0001.JPG").exists()
    assert (root / exporter.TRASH_DIR / "backup" / "IMG_0001.JPG").exists()
    exporter.restore_from_trash(moved)
    assert orig.exists() and dup.exists()


def test_mp4_local_created_corrupt_keys_and_find_mvhd_bounds(tmp_path):
    # keys atom con size < 8 oppure oltre la fine di keys
    keys_payload = struct.pack(">II", 0, 5000) + struct.pack(">I4s", 4, b"mdta")
    keys_atom = struct.pack(">I4s", 8 + len(keys_payload), b"keys") + keys_payload
    ilst_atom = struct.pack(">I4s", 8, b"ilst")
    hdlr_atom = struct.pack(">I4s", 12, b"hdlr") + b"\x00" * 4
    meta_body = hdlr_atom + keys_atom + ilst_atom
    meta_atom = struct.pack(">I4s", 8 + len(meta_body), b"meta") + meta_body
    moov_atom = struct.pack(">I4s", 8 + len(meta_atom), b"moov") + meta_atom
    bad_mp4 = tmp_path / "bad_keys.mp4"
    bad_mp4.write_bytes(moov_atom)
    assert scanner.mp4_local_created(bad_mp4) is None

    # keys atom con size che sfora keys[1]
    keys_payload2 = struct.pack(">II", 0, 1) + struct.pack(">I4s", 9999, b"mdta") + b"abc"
    keys_atom2 = struct.pack(">I4s", 8 + len(keys_payload2), b"keys") + keys_payload2
    meta_body2 = hdlr_atom + keys_atom2 + ilst_atom
    meta_atom2 = struct.pack(">I4s", 8 + len(meta_body2), b"meta") + meta_body2
    moov_atom2 = struct.pack(">I4s", 8 + len(meta_atom2), b"moov") + meta_atom2
    bad_mp4_2 = tmp_path / "overflow_keys.mp4"
    bad_mp4_2.write_bytes(moov_atom2)
    assert scanner.mp4_local_created(bad_mp4_2) is None

    # _find_mvhd con moov più grande di end e mvhd troncato
    trunc_mvhd = struct.pack(">I4s", 100, b"mvhd") + b"\x00\x00\x00\x00"
    oversized_moov = struct.pack(">I4s", 99999, b"moov") + trunc_mvhd
    f = io.BytesIO(oversized_moov)
    assert scanner._find_mvhd(f, 0, len(oversized_moov)) == (0.0, 0)


def test_cloud_speed_samples_bounded_and_download_abandon(tmp_path, monkeypatch):
    assert isinstance(cloud.speed_samples, collections.deque)
    assert cloud.speed_samples.maxlen == 8
    cloud.speed_samples.clear()
    for i in range(20):
        cloud.speed_samples.append(float(i + 1))
    assert len(cloud.speed_samples) == 8
    assert cloud.estimated_speed() > 0

    p = tmp_path / "video.mov"
    p.write_bytes(b"x" * 1024)
    monkeypatch.setattr(cloud, "is_local", lambda _: False)
    ev = threading.Event()
    ev.set()
    assert cloud.download(p, timeout=1, abandon=ev) is False


def test_stills_cache_retention_and_inflight_future(tmp_path, monkeypatch):
    a_path = _save_jpeg(tmp_path / "a.jpg", (255, 0, 0))
    b_path = _save_jpeg(tmp_path / "b.jpg", (0, 255, 0))
    item_a = Item(kind="photo", id="a.jpg", image=a_path)
    item_b = Item(kind="photo", id="b.jpg", image=b_path)

    calls = []
    real_decode = stills.decode

    def counting_decode(it: Item):
        calls.append(it.id)
        return real_decode(it)

    monkeypatch.setattr(stills, "decode", counting_decode)
    cache = stills.Stills()
    img_a1 = cache.take(item_a)
    assert not img_a1.isNull()
    assert "a.jpg" in cache.cache
    img_b1 = cache.take(item_b)
    assert not img_b1.isNull()
    img_a2 = cache.take(item_a)
    assert not img_a2.isNull()
    assert calls == ["a.jpg", "b.jpg"]  # a.jpg non viene ridecodificata

    # Future in corso in self.pending
    c_path = _save_jpeg(tmp_path / "c.jpg", (0, 0, 255))
    item_c = Item(kind="photo", id="c.jpg", image=c_path)
    fut: concurrent.futures.Future = concurrent.futures.Future()
    fut.set_result(real_decode(item_c))
    cache.pending[item_c.id] = fut
    calls.clear()
    img_c = cache.take(item_c)
    assert not img_c.isNull()
    assert calls == []
    assert item_c.id in cache.cache


def test_proxy_window_ignores_ffd8_inside_jpeg_header(tmp_path, monkeypatch):
    # Costruisce due JPEG finti in cui il primo contiene \xff\xd8 dentro l'header APP0
    jpg1 = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\xff\xd8\x00\x00\x00body1\xff\xd9"
    jpg2 = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x00\x00\x00body2\xff\xd9"
    stream = jpg1 + jpg2

    monkeypatch.setattr(
        frames,
        "_run",
        lambda args, timeout=60: subprocess.CompletedProcess(args, 0, stream, b""),
    )
    info = frames.VideoInfo(width=16, height=16, fps=frames.Fraction(10, 1), duration=1.0, frames=10)
    parts = frames.proxy_window(tmp_path / "v.mp4", info, 0, 2)
    assert parts == [jpg1, jpg2]


def test_edits_aspect_ratio_invalid_custom():
    assert edits.aspect_ratio({"aspect": "custom", "aspect_custom": [5]}, 100, 100) == 1.0
    assert edits.aspect_ratio({"aspect": "custom", "aspect_custom": "bad"}, 100, 100) == 1.0
    assert edits.aspect_ratio({"aspect": "custom", "aspect_custom": [16, 9]}, 100, 100) == 16 / 9
    assert "aspect_custom" not in edits.clean({"crop": [0, 0, 0.5, 0.5], "aspect": "custom", "aspect_custom": [5]})


def test_selftest_empty_and_raw_pair(tmp_path):
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    out_empty = tmp_path / "out_empty"
    assert selftest.selftest(empty_root, out_empty, "empty") == 1

    root = tmp_path / "src"
    jpg = _save_jpeg(root / "IMG_0001.JPG")
    dng = root / "IMG_0001.DNG"
    dng.write_bytes(b"DNG-RAW-CONTENT-" * 50)
    assert jpg.read_bytes() != dng.read_bytes()
    out = tmp_path / "out"
    assert selftest.selftest(root, out, "with_raw") == 0
