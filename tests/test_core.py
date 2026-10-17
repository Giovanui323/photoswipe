"""Test su una struttura di cartelle che riproduce la scheda SD della Pocket 4."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image
from PIL.JpegImagePlugin import get_sampling

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cloud  # noqa: E402
import exporter  # noqa: E402
import frames  # noqa: E402
from scanner import scan  # noqa: E402

FF = frames.ffmpeg_exe()
LIVE = "DJI_20260730132204_0001_D"
LONG = "DJI_20260730132300_0004_D"


def make_clip(path: Path, seconds: float, size="640x360"):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size={size}:rate=30000/1001:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_primaries", "bt709",
                    "-color_trc", "bt709", "-colorspace", "bt709", "-movflags", "+faststart",
                    str(path)], check=True)


@pytest.fixture(scope="module")
def sd(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("sd")
    dcim = root / "DCIM" / "DJI_001"
    dcim.mkdir(parents=True)
    make_clip(dcim / f"{LIVE}.MP4", 3.036)
    shutil.copy(dcim / f"{LIVE}.MP4", dcim / f"{LIVE}.LRF")
    make_clip(dcim / f"{LONG}.MP4", 8)
    Image.new("RGB", (400, 300), "red").save(dcim / "DJI_20260730132210_0002_D.JPG", quality=90)
    Image.new("RGB", (800, 800), "blue").save(dcim / "DJI_20260730132220_0003_D.JPG", quality=90)
    pano = root / "DCIM" / "PANORAMA" / "001_0003"
    pano.mkdir(parents=True)
    Image.new("RGB", (100, 100)).save(pano / "PANO_0001.JPG")
    (dcim / f"._{LIVE}.MP4").write_bytes(b"\0" * 10)                  # AppleDouble macOS
    (dcim / ".DJI_20260730132400_0005_D.MP4.icloud").write_bytes(b"x")  # stub iCloud
    # anteprima .SCR = fotogramma 40 della Live, come fa la fotocamera
    thm = root / "MISC" / "THM" / "DJI_001"
    thm.mkdir(parents=True)
    info = frames.probe(dcim / f"{LIVE}.MP4")
    frames.frame_rgb(dcim / f"{LIVE}.MP4", info, 40).resize((320, 180)).save(
        thm / f"{LIVE}.SCR", "JPEG", quality=85)
    return root


def test_scan_kinds(sd):
    items = {i.main.name: i for i in scan(sd, sd / "export")}
    assert items[f"{LIVE}.MP4"].kind == "live"
    assert items[f"{LONG}.MP4"].kind == "video"
    assert items["DJI_20260730132210_0002_D.JPG"].kind == "photo"
    assert items["DJI_20260730132220_0003_D.JPG"].kind == "pano"
    assert "PANO_0001.JPG" not in items                    # pezzi del panorama esclusi
    assert not any(n.startswith("._") for n in items)       # file AppleDouble esclusi
    assert not any(n.endswith(".LRF") for n in items)       # anteprime escluse
    assert "DJI_20260730132400_0005_D.MP4" in items          # file solo su iCloud incluso
    assert not cloud.is_local(items["DJI_20260730132400_0005_D.MP4"].video)
    live = items[f"{LIVE}.MP4"]
    assert live.proxy and live.proxy.suffix == ".LRF"
    assert live.screennail and live.screennail.suffix == ".SCR"


def test_frame_index_is_exact(sd):
    v = sd / "DCIM" / "DJI_001" / f"{LIVE}.MP4"
    info = frames.probe(v)
    assert info.frames == 91
    for n in (0, 1, 45, 90):
        a = frames.frame_rgb(v, info, n)
        raw = subprocess.run([FF, "-v", "error", "-i", str(v), "-map", "0:v:0", "-vf",
                              f"select=eq(n\\,{n}),{frames._SCALE_EXACT},format=rgb24",
                              "-frames:v", "1", "-f", "rawvideo", "-"],
                             capture_output=True).stdout
        b = Image.frombytes("RGB", a.size, raw[:a.width * a.height * 3])
        assert a.tobytes() == b.tobytes(), f"fotogramma {n} diverso"


def test_camera_frame_from_scr(sd):
    item = next(i for i in scan(sd) if i.kind == "live")
    info = frames.probe(item.video)
    assert frames.camera_frame(item.video, info, item.screennail) == 40
    assert frames.camera_frame(item.video, info, None) == info.frames // 2


def test_export_photo_is_byte_identical(sd, tmp_path):
    item = next(i for i in scan(sd) if i.kind == "photo")
    out = exporter.export_item(item, None, tmp_path, exporter.Settings())
    assert out[0].read_bytes() == item.image.read_bytes()


def test_export_live_jpeg_quality(sd, tmp_path):
    item = next(i for i in scan(sd) if i.kind == "live")
    out = exporter.export_item(item, None, tmp_path, exporter.Settings())
    jpg = Image.open(out[0])
    assert jpg.size == (640, 360)
    assert get_sampling(jpg) == 0                      # 4:4:4, colore pieno
    assert jpg.info.get("icc_profile")
    assert jpg.getexif().get_ifd(0x8769)[0x9003] == "2026:07:30 13:22:05"  # +40 fotogrammi
    assert "fotogramma 41" in jpg.getexif()[0x010E]   # contati da 1


def test_export_png16_and_video_copy(sd, tmp_path):
    item = next(i for i in scan(sd) if i.kind == "live")
    out = exporter.export_item(item, 10, tmp_path, exporter.Settings(fmt="png16", copy_video=True))
    assert out[0].suffix == ".png"
    assert b"\x10\x02" in out[0].read_bytes()[24:26]  # IHDR: profondità 16 bit, RGB
    assert out[1].parent.name == exporter.VIDEO_SUBDIR
    assert out[1].read_bytes() == item.video.read_bytes()


def test_long_video_without_scene_copies_mp4(sd, tmp_path):
    item = next(i for i in scan(sd) if i.kind == "video" and cloud.is_local(i.video))
    out = exporter.export_item(item, None, tmp_path, exporter.Settings())
    assert out == [tmp_path / exporter.VIDEO_SUBDIR / item.video.name]


def test_unique_names(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"1")
    assert exporter.unique_path(tmp_path, "a.jpg").name == "a_2.jpg"


def test_session_roundtrip(tmp_path):
    root, export = tmp_path / "src", tmp_path / "out"
    root.mkdir()
    s = exporter.Session(root, export, total=3)
    s.set("a", "yes", [export / "a.jpg"], 40)
    s.set("b", "skip")
    assert (root / exporter.SESSION_FILE).exists()             # salvato nella cartella aperta
    s2 = exporter.Session(root, export, total=3)
    assert s2.get("a")["frame"] == 40
    assert s2.counts() == {"yes": 1, "no": 0, "skip": 1, "trash": 0}
    info = exporter.Session.peek(root)
    assert info["decided"] == 2 and info["total"] == 3 and not info["completed"]
    s2.set("c", "no")
    s2.close()
    info = exporter.Session.peek(root)
    assert info["completed"] and info["closed"] and info["export"] == str(export)
    s2.archive()
    assert exporter.Session.peek(root) is None                  # "Ricomincia": vecchio salvato .bak
    assert list(root.glob(exporter.SESSION_FILE + ".*.bak"))


def test_move_to_trash_and_restore(tmp_path):
    root = tmp_path / "src"
    d = root / "DCIM" / "DJI_001"
    d.mkdir(parents=True)
    make_clip(d / "DJI_20260730140000_0009_D.MP4", 1)
    shutil.copy(d / "DJI_20260730140000_0009_D.MP4", d / "DJI_20260730140000_0009_D.LRF")
    item = scan(root)[0]
    moved = exporter.move_to_trash(item, root)
    trash = root / exporter.TRASH_DIR / "DCIM" / "DJI_001"
    assert sorted(p.name for p in trash.iterdir()) == ["DJI_20260730140000_0009_D.LRF",
                                                       "DJI_20260730140000_0009_D.MP4"]
    assert not item.video.exists()
    assert scan(root, [root / exporter.TRASH_DIR]) == []    # la cartella "cancellare" non si rilegge
    exporter.restore_from_trash(moved)
    assert item.video.exists() and not trash.exists()          # niente cartelle vuote rimaste


def test_snapshot_from_long_video(sd, tmp_path):
    item = next(i for i in scan(sd) if i.kind == "video" and cloud.is_local(i.video))
    s = exporter.Settings(copy_video=True)
    a = exporter.export_item(item, 30, tmp_path, s, snapshot=True)
    b = exporter.export_item(item, 120, tmp_path, s, snapshot=True)
    assert [p.name for p in a + b] == [f"{item.video.stem}_f0031.jpg", f"{item.video.stem}_f0121.jpg"]
    assert not (tmp_path / exporter.VIDEO_SUBDIR).exists()   # la foto presa non copia il video
    exif = Image.open(b[0]).getexif().get_ifd(0x8769)
    assert exif[0x9003] == "2026:07:30 13:23:04"            # 120 / 29,97 fps = +4 s
