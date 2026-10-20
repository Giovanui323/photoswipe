"""Il lavoro per cui esiste l'app: scegliere le foto da tenere e farne un album.

Dalla cartella con le foto (in disordine, con doppioni, preferite e scarti) alla cartella export
con solo le tenute, in ordine di scatto, originali intatti. Più i casi che rompevano quel lavoro:
export a metà, file spariti, rinomina interrotta, cestino svuotato a mano, iCloud."""
from __future__ import annotations

import ast
import re
import hashlib
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cloud  # noqa: E402
import exporter  # noqa: E402
from scanner import Item, scan  # noqa: E402


def jpeg(path: Path, when: str | None, color=(120, 80, 40), size=(64, 48)) -> Path:
    """JPEG con la data di scatto nell'EXIF (when = "2024:06:15 12:34:56")."""
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, color)
    exif = Image.Exif()
    if when:
        exif[306] = when
        exif.get_ifd(0x8769)[36867] = when
    im.save(path, quality=90, exif=exif)
    return path


def digest(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and not p.name.startswith(".")}


def files_in(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                  if p.is_file() and not p.name.startswith("."))


@pytest.fixture
def trip(tmp_path) -> Path:
    """Una vacanza: due schede, nomi in ordine diverso dall'ora di scatto, un doppione."""
    root = tmp_path / "vacanza"
    jpeg(root / "sd1" / "IMG_0003.JPG", "2024:06:15 09:00:00", (200, 0, 0))     # mattina
    jpeg(root / "sd1" / "IMG_0001.JPG", "2024:06:15 18:30:00", (0, 200, 0))     # sera
    jpeg(root / "sd2" / "IMG_0002.JPG", "2024:06:14 12:00:00", (0, 0, 200))     # giorno prima
    jpeg(root / "sd2" / "IMG_0004.JPG", "2024:06:15 13:00:00", (90, 90, 90))    # da scartare
    jpeg(root / "sd2" / "IMG_0005.JPG", "2024:06:16 08:00:00", (10, 200, 200))  # preferita
    (root / "copia").mkdir()
    (root / "copia" / "IMG_0003.JPG").write_bytes((root / "sd1" / "IMG_0003.JPG").read_bytes())
    return root


# ------------------------------------------------------------------ il percorso completo

def test_album_from_choice_to_dated_export(trip, tmp_path):
    before = digest(trip)
    export = tmp_path / "album"
    items = scan(trip, [export])
    names = [it.main.name for it in items]
    assert names.count("IMG_0003.JPG") == 1, "il doppione identico si vede una volta sola"
    # ordine di scatto, non di nome
    assert [it.main.name for it in items] == ["IMG_0002.JPG", "IMG_0003.JPG", "IMG_0004.JPG",
                                              "IMG_0001.JPG", "IMG_0005.JPG"]

    s = exporter.Session(trip, export, ids=[it.id for it in items])
    choice = {"IMG_0002.JPG": "yes", "IMG_0003.JPG": "yes", "IMG_0004.JPG": "no",
              "IMG_0001.JPG": "yes", "IMG_0005.JPG": "yes"}
    for it in items:
        c = choice[it.main.name]
        if it.main.name == "IMG_0005.JPG":
            s.toggle_favorite(it.id)
        s.set(it.id, c)
        if c == "yes":
            token = "t-" + it.id
            s.mark_export(it.id, token)
            res = exporter.export_item(it, None, export, exporter.Settings(),
                                       favorite=it.id in s.favorites)
            assert s.record_export(it.id, token, res) == "ok"
    assert s.completed and s.counts()["yes"] == 4 and s.counts()["no"] == 1

    # solo le tenute, copie identiche, già con data e ora di scatto davanti: l'album si legge
    # in ordine di scatto; la preferita in Foto/Preferite
    assert files_in(export) == ["Foto/20240614_120000_IMG_0002.JPG", "Foto/20240615_090000_IMG_0003.JPG",
                                "Foto/20240615_183000_IMG_0001.JPG",
                                "Foto/Preferite/20240616_080000_IMG_0005.JPG"]
    for it in items:
        if choice[it.main.name] == "yes":
            copy = Path(s.get(it.id)["files"][0])
            assert copy.read_bytes() == it.main.read_bytes()

    # "metti in ordine" su un export già nel formato nuovo: niente da fare, nessun secondo prefisso
    entries = [(it.id, exporter.album_time(s.get(it.id)["files"], it.taken), s.get(it.id)["files"])
               for it in items if s.get(it.id)["choice"] == "yes"]
    errors: list[str] = []
    assert exporter.rename_by_date(entries, export, errors, set(s.favorites)) == {}
    assert not errors
    for it in items:   # il salvataggio sa dove sono le copie
        for f in s.get(it.id)["files"]:
            assert Path(f).exists()

    # ripresa: un'altra apertura ritrova tutto, niente da ricopiare
    s2 = exporter.Session(trip, export, ids=[it.id for it in items])
    assert s2.completed and s2.pending_exports({it.id for it in items}) == []
    assert digest(trip) == before, "gli originali non si toccano mai"


def test_album_time_prefers_the_copy_exif(tmp_path):
    copy = jpeg(tmp_path / "DJI_20240101000000_0001_D.JPG", "2024:06:15 10:11:12")
    fallback = datetime(2000, 1, 1)
    assert exporter.album_time([str(copy)], fallback) == datetime(2024, 6, 15, 10, 11, 12)
    no_exif = jpeg(tmp_path / "x.jpg", None)
    assert exporter.album_time([str(no_exif)], fallback) == fallback
    assert exporter.album_time([str(tmp_path / "missing.jpg")], fallback) == fallback


# ------------------------------------------------------------------ export a metà

def test_failed_export_leaves_no_orphan_copies(tmp_path):
    """JPG+DNG: se il DNG non si copia, il JPG già copiato si toglie (niente doppioni ai tentativi)."""
    src = tmp_path / "src"
    img = jpeg(src / "IMG.JPG", "2024:01:01 10:00:00")
    raw = src / "IMG.DNG"
    raw.write_bytes(b"raw")
    it = Item(kind="photo", id="IMG.JPG", image=img, raw=raw)
    raw.unlink()   # sparito durante la sessione (scheda tolta, file spostato)
    export = tmp_path / "export"
    for _ in range(2):
        t0 = time.monotonic()
        with pytest.raises(OSError):
            exporter.export_item(it, None, export, exporter.Settings())
        assert time.monotonic() - t0 < 5, "un file sparito non deve bloccare la coda per 15 minuti"
    assert files_in(export) == []


def test_download_of_vanished_file_returns_at_once(tmp_path):
    t0 = time.monotonic()
    assert cloud.download(tmp_path / "gone.jpg") is False
    assert time.monotonic() - t0 < 1


# ------------------------------------------------------------------ rinomina interrotta

def test_rename_by_date_keeps_going_and_reports_errors(tmp_path):
    export = tmp_path / "export"
    a = jpeg(export / "a.jpg", None)
    locked = export / "Video"
    b = jpeg(locked / "b.jpg", None)
    os.chmod(locked, 0o555)
    try:
        errors: list[str] = []
        moved = exporter.rename_by_date([("a", datetime(2024, 1, 1), [str(a)]),
                                         ("b", datetime(2024, 1, 2), [str(b)])], export, errors)
    finally:
        os.chmod(locked, 0o755)
    assert list(moved) == ["a"], "quelli rinominati vanno comunque registrati"
    assert Path(moved["a"][0][1]).exists() and len(errors) == 1 and "b.jpg" in errors[0]
    assert b.exists()


def test_rename_by_date_never_touches_files_outside_export(tmp_path):
    export = tmp_path / "export"
    outside = jpeg(tmp_path / "originale.jpg", None)
    assert exporter.rename_by_date([("x", datetime(2024, 1, 1), [str(outside)])], export) == {}
    assert outside.exists()


# ------------------------------------------------------------------ cestino e scansione

def test_trash_of_a_subfolder_is_not_offered_again_from_the_parent(tmp_path):
    root = tmp_path / "foto"
    keep = jpeg(root / "viaggio" / "IMG_2.JPG", "2024:01:01 10:00:00")
    gone = jpeg(root / "viaggio" / "IMG_1.JPG", "2024:01:01 09:00:00", (1, 2, 3))
    items = scan(root / "viaggio")
    trashed = next(it for it in items if it.main == gone)
    exporter.move_to_trash(trashed, root / "viaggio")
    assert [it.main for it in scan(root)] == [keep.resolve()]


def test_restore_reports_files_emptied_from_trash(tmp_path):
    root = tmp_path / "src"
    img = jpeg(root / "IMG.JPG", None)
    it = Item(kind="photo", id="IMG.JPG", image=img)
    moved = exporter.move_to_trash(it, root)
    Path(moved[0][1]).unlink()   # "cancellare" svuotata a mano
    missing: list[Path] = []
    exporter.restore_from_trash(moved, missing=missing)
    assert missing == [Path(moved[0][0])]


def test_icloud_placeholders_with_same_name_in_two_folders_are_both_shown(tmp_path):
    root = tmp_path / "icloud"
    for sub in ("A", "B"):
        (root / sub).mkdir(parents=True)
        (root / sub / ".IMG_0001.JPG.icloud").write_bytes(b"")   # solo su iCloud, dimensione ignota
    assert sorted(it.id for it in scan(root)) == ["A/IMG_0001.JPG", "B/IMG_0001.JPG"]


# ------------------------------------------------------------------ interfaccia in inglese

def test_every_ui_text_has_an_english_translation():
    from i18n import EN
    base = Path(__file__).resolve().parents[1]
    missing = []
    for f in sorted(base.glob("*.py")):
        for n in ast.walk(ast.parse(f.read_text("utf-8"))):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "tr" and n.args \
                    and isinstance(n.args[0], ast.Constant) and n.args[0].value not in EN:
                missing.append(f"{f.name}:{n.lineno} {n.args[0].value[:50]!r}")
    assert not missing, "\n".join(missing)


def test_english_translations_keep_the_placeholders():
    import string
    from i18n import EN
    fields = lambda t: {f for _, f, _, _ in string.Formatter().parse(t) if f}  # noqa: E731
    bad = [k for k, v in EN.items() if fields(k) != fields(v)]
    assert not bad, bad


# ------------------------------------------------------------------ export/Foto, Foto/Preferite, Video

def test_album_layout_sorted_by_name_is_capture_order(trip, tmp_path):
    """Approvate in disordine (ultima scattata per prima), più un video e una preferita:
    alla fine solo export/Foto, export/Foto/Preferite, export/Video, e il nome dà l'ordine di scatto."""
    from test_core import make_clip
    clip = trip / "DCIM" / "DJI_001" / "DJI_20240615150000_0007_D.MP4"
    clip.parent.mkdir(parents=True)
    make_clip(clip, 5, "320x180")
    export = tmp_path / "export"
    items = scan(trip, [export])
    by_name = {it.main.name: it for it in items}
    assert by_name[clip.name].kind == "video"
    s = exporter.Session(trip, export, ids=[it.id for it in items])
    fav = by_name["IMG_0003.JPG"]
    s.toggle_favorite(fav.id)
    order = ["IMG_0005.JPG", clip.name, "IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG"]   # non di scatto
    for name in order:
        it = by_name[name]
        s.set(it.id, "yes")
        s.mark_export(it.id, "t")
        res = exporter.export_item(it, None, export, exporter.Settings(), favorite=it.id in s.favorites)
        assert s.record_export(it.id, "t", res) == "ok"

    assert sorted(p.name for p in export.iterdir()) == ["Foto", "Video"]
    foto = export / exporter.PHOTO_SUBDIR
    assert sorted(p.name for p in foto.iterdir()) == [
        "20240614_120000_IMG_0002.JPG", "20240615_183000_IMG_0001.JPG",
        "20240616_080000_IMG_0005.JPG", "Preferite"]
    assert [p.name for p in (foto / exporter.FAV_SUBDIR).iterdir()] == ["20240615_090000_IMG_0003.JPG"]
    assert [p.name for p in (export / exporter.VIDEO_SUBDIR).iterdir()] == \
        ["20240615_150000_DJI_0007_D.MP4"]   # la data DJI del nome non si ripete

    # ordinare la cartella Foto per nome = ordinarla per ora di scatto
    by_file = sorted(p for p in foto.iterdir() if p.is_file())
    taken = [exporter.album_time([str(p)], datetime.min) for p in by_file]
    assert taken == sorted(taken) and len(set(taken)) == len(taken)
    assert [p.name.split("_", 2)[2] for p in by_file] == ["IMG_0002.JPG", "IMG_0001.JPG", "IMG_0005.JPG"]
    for p in by_file:   # copie identiche agli originali
        assert p.read_bytes() == by_name[p.name.split("_", 2)[2]].main.read_bytes()
    assert (export / exporter.VIDEO_SUBDIR / "20240615_150000_DJI_0007_D.MP4").read_bytes() == clip.read_bytes()


def test_rename_by_date_migrates_legacy_export(tmp_path):
    """Copie fatte dalle versioni di prima: sciolte in export, in export/Preferite, col numero 0001_.
    Vanno al loro posto col nome con la data; rifarlo non cambia niente; fuori da export nulla."""
    export = tmp_path / "export"
    loose = jpeg(export / "IMG_0001.JPG", None, (1, 1, 1))
    old_fav = jpeg(export / exporter.FAV_SUBDIR / "x.jpg", None, (2, 2, 2))
    video = export / exporter.VIDEO_SUBDIR / "y.mp4"
    video.parent.mkdir()
    video.write_bytes(b"video" * 100)
    numbered = jpeg(export / "0001_20240101_000000_z.jpg", None, (3, 3, 3))
    new_fav = jpeg(export / "w.jpg", None, (4, 4, 4))                 # preferita, ancora sciolta
    outside = jpeg(tmp_path / "originale.jpg", None, (5, 5, 5))
    unrelated = export / "note.txt"
    unrelated.write_text("mie note")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (loose, old_fav, video, numbered, new_fav)}
    outside_bytes = outside.read_bytes()

    entries = [("a", datetime(2024, 6, 15, 10, 0, 0), [str(loose)]),
               ("b", datetime(2024, 6, 14, 9, 0, 0), [str(old_fav)]),
               ("c", datetime(2024, 6, 15, 11, 0, 0), [str(video)]),
               ("d", datetime(2024, 1, 1, 0, 0, 0), [str(numbered)]),
               ("e", datetime(2024, 6, 16, 8, 0, 0), [str(new_fav)]),
               ("f", datetime(2024, 6, 17, 8, 0, 0), [str(outside)])]
    errors: list[str] = []
    moved = exporter.rename_by_date(entries, export, errors, {"e"})
    assert not errors
    foto, favs, vids = (exporter.photo_dir(export), exporter.photo_dir(export, True),
                        exporter.video_dir(export))
    expect = {"a": foto / "20240615_100000_IMG_0001.JPG",
              "b": favs / "20240614_090000_x.jpg",
              "c": vids / "20240615_110000_y.mp4",
              "d": foto / "20240101_000000_z.jpg",
              "e": favs / "20240616_080000_w.jpg"}
    src = {"a": loose, "b": old_fav, "c": video, "d": numbered, "e": new_fav}
    assert moved == {k: [[str(src[k]), str(v)]] for k, v in expect.items()}
    layout = ["Foto/20240101_000000_z.jpg", "Foto/20240615_100000_IMG_0001.JPG",
              "Foto/Preferite/20240614_090000_x.jpg", "Foto/Preferite/20240616_080000_w.jpg",
              "Video/20240615_110000_y.mp4", "note.txt"]
    assert files_in(export) == layout
    assert not (export / exporter.FAV_SUBDIR).exists() or not any((export / exporter.FAV_SUBDIR).iterdir())
    for k, dst in expect.items():   # spostate, non ricopiate: stesso contenuto
        assert hashlib.sha256(dst.read_bytes()).hexdigest() == before[src[k]]
    assert outside.read_bytes() == outside_bytes                       # fuori da export: intatto
    assert unrelated.read_text() == "mie note"                         # non in entries: intatto

    # seconda volta, con i percorsi nuovi: niente da fare
    again = [(i, w, [str(expect[i])] if i in expect else f) for i, w, f in entries]
    assert exporter.rename_by_date(again, export, errors, {"e"}) == {}
    assert not errors
    assert files_in(export) == layout
    assert outside.exists()


def test_refile_favorite_moves_photos_between_foto_and_preferite(tmp_path):
    root, export = tmp_path / "src", tmp_path / "export"
    jpeg(root / "IMG_0001.JPG", "2024:06:15 12:34:56")
    (root / "IMG_0001.DNG").write_bytes(b"raw-data" * 100)
    (root / "IMG_0001.MOV").write_bytes(b"mov" * 1000)                # Live di iPhone
    [item] = scan(root)
    files = [str(p) for p in exporter.export_item(item, None, export, exporter.Settings(copy_video=True))]
    P = "20240615_123456_IMG_0001"
    assert files_in(export) == [f"Foto/{P}.DNG", f"Foto/{P}.JPG", f"Video/{P}.MOV"]
    exporter.release_claims(files)
    content = digest(export)

    # ♥: foto e DNG in Foto/Preferite, il video resta in Video
    pairs = exporter.refile_favorite(files, export, True)
    assert files_in(export) == [f"Foto/Preferite/{P}.DNG", f"Foto/Preferite/{P}.JPG", f"Video/{P}.MOV"]
    assert sorted(digest(export).values()) == sorted(content.values())
    assert [Path(a).name for a, _ in pairs] == [f"{P}.JPG", f"{P}.DNG"]
    files = [dict(pairs).get(f, f) for f in files]
    assert exporter.refile_favorite(files, export, True) == []        # già al posto giusto

    # come un export fatto direttamente da preferita
    other = tmp_path / "export2"
    direct = exporter.export_item(item, None, other, exporter.Settings(copy_video=True), favorite=True)
    assert files_in(other) == files_in(export)
    exporter.release_claims(direct)

    # ♥ tolto: di nuovo in Foto
    pairs = exporter.refile_favorite(files, export, False)
    assert files_in(export) == [f"Foto/{P}.DNG", f"Foto/{P}.JPG", f"Video/{P}.MOV"]
    assert len(pairs) == 2
    files = [dict(pairs).get(f, f) for f in files]
    assert exporter.refile_favorite(files, export, False) == []

    # copia di una versione di prima in export/Preferite: con ♥ resta lì, senza ♥ va in Foto
    legacy = jpeg(export / exporter.FAV_SUBDIR / "OLD.JPG", None)
    assert exporter.refile_favorite([str(legacy)], export, True) == []
    assert legacy.exists()
    assert exporter.refile_favorite([str(legacy)], export, False) == \
        [[str(legacy), str(export / exporter.PHOTO_SUBDIR / "OLD.JPG")]]
    assert not legacy.exists() and (export / exporter.PHOTO_SUBDIR / "OLD.JPG").exists()

    # fuori da export: mai
    outside = jpeg(tmp_path / "fuori.jpg", None)
    assert exporter.refile_favorite([str(outside)], export, True) == [] and outside.exists()


def test_every_name_has_one_date_in_the_same_style(tmp_path):
    """Una sola data all'inizio, sempre nello stesso stile (20240615_123456_), qualunque cosa
    scrivesse la fotocamera nel nome: Samsung, Android, Pixel, DJI, schermate del Mac. La data è
    quella di scatto (EXIF), anche se quella nel nome originale era diversa."""
    root, export = tmp_path / "src", tmp_path / "export"
    jpeg(root / "20240615_123456_001.jpg", "2024:06:15 12:34:56")                 # Samsung
    jpeg(root / "20240615_123500_002.jpg", "2024:06:15 12:35:01", (9, 9, 9))      # EXIF != nome
    jpeg(root / "IMG_20240615_130000.jpg", "2024:06:15 13:00:00", (1, 9, 9))      # Android
    jpeg(root / "PXL_20240615_140000123.jpg", "2024:06:15 14:00:00", (9, 1, 9))   # Pixel
    jpeg(root / "Screenshot 2024-06-15 at 15.00.00.jpg", "2024:06:15 15:00:00", (9, 9, 1))
    jpeg(root / "DJI_20240615160000_0003_D.JPG", "2024:06:15 16:00:00", (5, 5, 5))
    items = scan(root)
    for it in items:
        exporter.export_item(it, None, export, exporter.Settings())
    names = files_in(export / exporter.PHOTO_SUBDIR)
    assert names == ["20240615_123456_001.jpg", "20240615_123501_002.jpg", "20240615_130000_IMG.jpg",
                     "20240615_140000_PXL.jpg", "20240615_150000_Screenshot.jpg",
                     "20240615_160000_DJI_0003_D.JPG"]
    assert all(re.fullmatch(r"\d{8}_\d{6}(_[^\d].*|_\d{3}.*)?\.\w+", n) for n in names), names
    assert len({n[:15] for n in names}) == len(names), "una data per file, mai ripetuta nel nome"

    # rifare il riordino non cambia niente; una copia numerata delle versioni di prima prende
    # lo stesso stile (niente 0001_, niente seconda data)
    entries = [(it.id, exporter.album_time([str(it.main)], it.taken),
                [str(p) for p in (export / exporter.PHOTO_SUBDIR).iterdir()
                 if exporter.dated(it.main.name, exporter.album_time([str(it.main)], it.taken)) == p.name])
               for it in items]
    exporter.release_claims([str(p) for _, _, fs in entries for p in fs])
    assert exporter.rename_by_date(entries, export) == {}
    old = export / "0001_20240615_123456_20240615_123456_001.jpg"
    old.write_bytes(b"vecchia copia")
    moved = exporter.rename_by_date([("v", datetime(2024, 6, 15, 12, 34, 56), [str(old)])], export)
    foto = export / exporter.PHOTO_SUBDIR
    assert moved == {"v": [[str(old), str(foto / "20240615_123456_001_2.jpg")]]}