"""Test su preferite, spostamento delle copie in export e miniature della striscia."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import exporter  # noqa: E402
import frames  # noqa: E402
from test_core import make_clip  # noqa: E402


def test_favorites_are_saved_with_the_session(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    s = exporter.Session(root, tmp_path / "out")
    assert s.toggle_favorite("a.jpg") is True
    assert exporter.Session(root, tmp_path / "out").favorites == {"a.jpg"}
    assert s.toggle_favorite("a.jpg") is False
    assert exporter.Session(root, tmp_path / "out").favorites == set()


def test_relocate_exports_keeps_subfolders_and_never_overwrites(tmp_path):
    out = tmp_path / "out"
    fav = out / exporter.FAV_SUBDIR
    (out / exporter.VIDEO_SUBDIR).mkdir(parents=True)
    photo, video = out / "a.jpg", out / exporter.VIDEO_SUBDIR / "a.mp4"
    photo.write_bytes(b"foto")
    video.write_bytes(b"video")
    fav.mkdir()
    (fav / "a.jpg").write_bytes(b"un'altra preferita con lo stesso nome")
    pairs = exporter.relocate_exports([str(photo), str(video), "/altrove/x.jpg"], out, fav)
    assert [Path(b).relative_to(fav).as_posix() for _, b in pairs] == ["a_2.jpg", "Video/a.mp4"]
    assert (fav / "a.jpg").read_bytes() == b"un'altra preferita con lo stesso nome"   # intatta
    assert (fav / "a_2.jpg").read_bytes() == b"foto" and not photo.exists()


def test_session_follows_relocated_files_only_for_current_export(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    s = exporter.Session(root, tmp_path / "out")
    s.set("a.jpg", "yes", [tmp_path / "out" / "a.jpg"])
    s.mark_export("a.jpg", "t1")
    pairs = [[str(tmp_path / "out" / "a.jpg"), str(tmp_path / "out" / "Preferite" / "a.jpg")]]
    assert not s.relocated("a.jpg", "vecchio", pairs)                 # scelta cambiata: ignorato
    assert s.relocated("a.jpg", "t1", pairs)
    assert s.get("a.jpg")["files"] == [pairs[0][1]]


def test_strip_thumbs_cover_the_whole_clip(tmp_path):
    v = tmp_path / "clip.mp4"
    make_clip(v, 2)
    info = frames.probe(v)
    thumbs = frames.strip_thumbs(v, info, count=8, height=48)
    assert len(thumbs) == 8
    assert thumbs[0].size == (84, 48)              # 640×360 ridotto ad altezza 48
    assert thumbs[0].tobytes() != thumbs[-1].tobytes()
