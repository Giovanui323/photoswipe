"""Export (sempre copia, mai sposta) e sessione salvata per riprendere e annullare."""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import threading
import unicodedata
import weakref
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path

import cloud
import edits
import frames
from scanner import Item, TRASH_DIR
from i18n import tr

SESSION_FILE = ".photoswipe-session.json"
# export/Foto (preferite in export/Foto/Preferite) ed export/Video; ogni copia col nome che
# comincia con data e ora di scatto (20240615_123456_IMG_0001.JPG): in ordine per nome = in ordine di scatto
PHOTO_SUBDIR = "Foto"
FAV_SUBDIR = "Preferite"  # dentro Foto
VIDEO_SUBDIR = "Video"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mts", ".m2ts"}


def photo_dir(export_dir: Path, favorite: bool = False) -> Path:
    d = Path(export_dir) / PHOTO_SUBDIR
    return d / FAV_SUBDIR if favorite else d


def video_dir(export_dir: Path) -> Path:
    return Path(export_dir) / VIDEO_SUBDIR


# date già scritte nel nome dalla fotocamera / dal telefono, in qualsiasi stile: si tolgono, così
# ogni nome ha UNA data, sempre nello stesso stile, all'inizio. 20240615_123456 (Samsung, Android),
# 20260730132210 (DJI), 20240615_123456789 (Pixel), 2024-06-15 12.34.56 (Mac, Dropbox)
_EMBEDDED_DATE = re.compile(
    r"(?<!\d)(?:(?:19|20)\d{6}[_-]?\d{6}(?:\d{3})?"
    r"|(?:19|20)\d{2}-\d{2}-\d{2}(?:[ _T]| at | alle )\d{1,2}[.:-]\d{2}[.:-]\d{2})(?!\d)")
_OLD_NUMBER = re.compile(r"^\d{4}_(?=\d{8}_\d{6})")   # "0001_" della rinomina delle versioni di prima


def dated(name: str, when: datetime) -> str:
    """Nome nell'album: data e ora di scatto davanti (20240615_123456_), poi il nome originale
    senza le date che conteneva già. Rifarlo sullo stesso nome dà lo stesso risultato."""
    p = Path(_OLD_NUMBER.sub("", name))
    rest = _EMBEDDED_DATE.sub("_", p.stem)
    rest = re.sub(r"[_\- .]{2,}", "_", rest).strip("_- .")
    stamp = f"{when:%Y%m%d_%H%M%S}"
    return f"{stamp}_{rest}{p.suffix}" if rest else f"{stamp}{p.suffix}"


@dataclass
class Settings:
    fmt: str = "jpeg"                  # "jpeg" (q100, 4:4:4) | "png16"
    copy_video: bool = False           # Live: copia anche l'MP4 originale in export/Video
    tz_override_hours: float | None = None


def export_dir_problem(root: Path, export_dir: Path) -> str | None:
    """Perché la cartella export non va bene per questa sorgente (None = va bene).

    Export dentro la sorgente è permesso (es. <sorgente>/export: la scansione la salta),
    ma non la sorgente stessa, né dentro "cancellare", né una cartella che contiene la sorgente."""
    root, export_dir = root.resolve(), export_dir.resolve()
    trash = root / TRASH_DIR
    if export_dir == root:
        return tr("La cartella export non può essere la stessa da guardare: scegline o creane un'altra.")
    if export_dir == trash or trash in export_dir.parents:
        return (tr('La cartella export non può stare dentro “{TRASH_DIR}”: lì vanno solo gli originali messi da parte.', TRASH_DIR=TRASH_DIR))
    if export_dir in root.parents:
        return (tr("La cartella export non può contenere la cartella da guardare: scegline o creane un'altra."))
    return None


def unique_path(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    stem, ext, i = p.stem, p.suffix, 2
    while p.exists():
        p = folder / f"{stem}_{i}{ext}"
        i += 1
    return p


# ---- copie già fatte e mai registrate (app chiusa dopo la copia, esito "stale"): alla ripresa
# si riusa la copia identica col nome esatto invece di farne una seconda (IMG_2.jpg).
# Mai una copia che appartiene a un'altra scelta: né registrata in una sessione aperta, né fatta
# da questo processo e non ancora liberata (esito in arrivo, o di un altro elemento uguale).
_claims: set[str] = set()               # copie fatte/riusate da questo processo, ancora "in mano"
_claims_lock = threading.Lock()
_sessions: "weakref.WeakSet[Session]" = weakref.WeakSet()   # sessioni aperte in questo processo
_tls = threading.local()                # copie riusate dall'export in corso (da non togliere se fallisce)


def _norm_path(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _path_keys(p) -> set[str]:
    keys = {_norm_path(p)}
    try:
        keys.add(os.path.normcase(os.path.realpath(str(p))))
    except OSError:
        pass
    return keys


def _claim(paths) -> None:
    with _claims_lock:
        for p in paths:
            _claims.update(_path_keys(p))


def release_claims(paths) -> None:
    """Le copie non sono più "in mano" a un export di questo processo (esito ignorato o tolte)."""
    with _claims_lock:
        for p in paths:
            _claims.difference_update(_path_keys(p))


def _recorded_files() -> set[str]:
    """Tutte le copie registrate nelle scelte delle sessioni aperte (di qualsiasi elemento)."""
    out: set[str] = set()
    for sess in list(_sessions):
        for _ in range(5):   # le scelte cambiano nel thread dell'interfaccia: si riprova
            try:
                decisions = list(sess.decisions.values())
                break
            except RuntimeError:
                continue
        else:
            raise RuntimeError("sessione in modifica")
        for d in decisions:
            for f in d.get("files") or []:
                out |= _path_keys(f)
    return out


def _same_content(a: Path, b: Path) -> bool:
    """Stessa dimensione e stesso contenuto (SHA-256)."""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False

        def digest(p: Path) -> bytes:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                    h.update(chunk)
            return h.digest()
        return digest(a) == digest(b)
    except OSError:
        return False


def _adoptable(target: Path, content: Path) -> bool:
    """La copia col nome esatto si può riusare: file vero (non link), identica a content,
    e di nessun'altra scelta. Nel dubbio no: si fa una copia nuova come prima."""
    try:
        if target.is_symlink() or not target.is_file():
            return False
        keys = _path_keys(target)
        with _claims_lock:
            if keys & _claims:
                return False
        if keys & _recorded_files():
            return False
    except (OSError, RuntimeError):
        return False
    return _same_content(target, content)


def _adopted() -> set[Path]:
    s = getattr(_tls, "adopted", None)
    if s is None:
        s = _tls.adopted = set()
    return s


def _place(tmp: Path, folder: Path, name: str) -> Path:
    """Mette al suo posto un file appena generato (tmp, già completo): se col nome esatto c'è
    già una copia identica e senza padrone si riusa quella, altrimenti nome libero (_2...)."""
    target = folder / name
    if _adoptable(target, tmp):
        tmp.unlink()
        _adopted().add(target)
        return target
    dst = unique_path(folder, name)
    os.replace(tmp, dst)
    return dst


def _staging(folder: Path, name: str) -> Path:
    """Nome temporaneo per un file generato: finisce con .part / .part.png, quindi se l'app
    si chiude a metà lo toglie clean_partial."""
    folder.mkdir(parents=True, exist_ok=True)
    if name.lower().endswith(".png"):
        return folder / f"{name}.part.png"
    return folder / f"{name}.part"


def _copy(src: Path, folder: Path, name: str | None = None) -> Path:
    cloud.download(src)
    name = name or src.name
    target = folder / name
    if _adoptable(target, src):   # copia identica già fatta (app chiusa prima di registrarla)
        _adopted().add(target)
        return target
    dst = unique_path(folder, name)
    tmp = dst.with_name(dst.name + ".part")
    shutil.copy2(src, tmp)  # copia identica, byte per byte
    os.replace(tmp, dst)
    return dst


def clean_partial(export_dir: Path) -> int:
    """Toglie le copie a metà (*.part) lasciate da un'uscita durante un export: sono solo file
    temporanei dell'app, la copia vera si rifà alla ripresa."""
    n = 0
    if not export_dir.is_dir():
        return 0
    for pat in ("*.part", "*.part.png"):
        for f in export_dir.rglob(pat):
            try:
                if f.is_file():
                    f.unlink()
                    n += 1
            except OSError:
                pass
    return n


def _export_edited(item: Item, edit: dict, export_dir: Path, when: datetime) -> Path:
    """Foto con Regola / Ritaglia: si salva la foto modificata (JPEG qualità massima, EXIF
    conservato), a piena risoluzione. L'originale non si tocca."""
    src = item.image or item.raw
    cloud.download(src)
    # solo DNG: load_full lo sviluppa a piena risoluzione (non l'anteprima incorporata)
    img, keep = edits.load_full(src)
    ext = src.suffix if src.suffix.lower() in (".jpg", ".jpeg") else ".jpg"   # stesso nome se era JPEG
    name = dated(src.stem + ext, when)
    if (export_dir / name).exists():   # forse già fatta (app chiusa prima di registrarla): si confronta
        stage = _staging(export_dir, name)
        try:
            edits.save_edited(edits.render(img, edit), stage, keep)
            dst = _place(stage, export_dir, name)
        finally:
            stage.unlink(missing_ok=True)
    else:
        dst = unique_path(export_dir, name)
        edits.save_edited(edits.render(img, edit), dst, keep)
    st = src.stat()
    os.utime(dst, (st.st_atime, st.st_mtime))   # stessa data dell'originale
    return dst


def export_item(item: Item, frame: int | None, export_dir: Path, s: Settings,
                snapshot: bool = False, edit: dict | None = None, favorite: bool = False) -> list[Path]:
    """Esegue l'export di un elemento approvato. Ritorna i file creati.

    export_dir: la cartella export; le foto vanno in export/Foto (favorite: export/Foto/Preferite),
    i video in export/Video, tutte col nome che comincia con data e ora di scatto.
    snapshot=True: "Prendi foto" da un video, salva solo quel fotogramma (nome con _fNNNN).
    edit: modifiche di Regola / Ritaglia (foto, panorami e Live): si salva la foto modificata.
    """
    out: list[Path] = []
    _tls.adopted = set()
    try:
        _export_item(item, frame, export_dir, s, snapshot, edit, out, favorite)
        _claim(out)   # di questo export finché l'esito non è registrato (o ignorato)
        return out
    except BaseException:
        # tutto o niente: le copie appena fatte da QUESTO export si tolgono, altrimenti
        # resterebbero in export senza una scelta e ogni nuovo tentativo farebbe un doppione.
        # Quelle riusate (già lì prima) non si toccano.
        adopted = _adopted()
        for f in out:
            if f in adopted:
                continue
            try:
                f.unlink()
            except OSError:
                pass
        raise
    finally:
        _tls.adopted = None


def _export_item(item: Item, frame: int | None, export_dir: Path, s: Settings,
                 snapshot: bool, edit: dict | None, out: list[Path], favorite: bool = False) -> list[Path]:
    edit = None if edits.is_empty(edit) else edits.clean(edit)   # anche le foto prese dai video
    photos, videos = photo_dir(export_dir, favorite), video_dir(export_dir)
    if item.kind in ("photo", "pano"):
        src = item.image or item.raw
        cloud.download(src)
        when = album_time([str(src)], item.taken)   # EXIF dell'originale, o la data della scansione
        if edit:
            out.append(_export_edited(item, edit, photos, when))
            if item.image and item.raw:   # il DNG resta l'originale, identico
                out.append(_copy(item.raw, photos, dated(item.raw.name, when)))
        else:
            for f in (item.image, item.raw):
                if f:
                    out.append(_copy(f, photos, dated(f.name, when)))
        if item.video and s.copy_video:  # Live Photo iPhone (HEIC+MOV): anche il video
            out.append(_copy(item.video, videos, dated(item.video.name, when)))
        return out

    video = item.video
    assert video is not None
    cloud.download(video)
    if item.kind == "live" or frame is not None:
        info = frames.probe(video)
        if frame is None:
            frame = frames.camera_frame(video, info, item.screennail)
        start, offset = frames.capture_times(item.taken, info, s.tz_override_hours)
        when = start + timedelta(seconds=float(frame / info.fps))  # ora esatta del fotogramma
        stem = f"{video.stem}_f{frame + 1:04d}" if snapshot else video.stem
        name = dated(stem + (".png" if s.fmt == "png16" else ".jpg"), when)

        def render(path: Path) -> None:
            if s.fmt == "png16" and not edit:
                frames.save_png16(video, info, frame, path)
            elif s.fmt == "png16":   # modificata: PNG senza perdita (8 bit, dopo le regolazioni)
                tmp = path.with_name(path.name + ".part.png")
                edits.render(frames.frame_rgb(video, info, frame), edit).save(tmp, "PNG")
                os.replace(tmp, path)
            else:
                img = edits.render(frames.frame_rgb(video, info, frame), edit)
                frames.save_jpeg(img, path, frames.FrameMeta(when, offset, video.name, frame))

        if (photos / name).exists():
            # forse già fatto (app chiusa prima di registrarlo), ma potrebbe essere un altro
            # fotogramma: si rigenera a parte e si riusa solo se identico byte per byte
            stage = _staging(photos, name)
            try:
                render(stage)
                dst = _place(stage, photos, name)
            finally:
                stage.unlink(missing_ok=True)
        else:
            dst = unique_path(photos, name)
            render(dst)
        frames.set_file_time(dst, when)
        out.append(dst)
        if s.copy_video and not snapshot:
            out.append(_copy(video, videos, dated(video.name, start)))
    else:
        # Video approvato senza scegliere una scena: si tiene il video originale
        start, _ = frames.capture_times(item.taken, frames.probe(video), s.tz_override_hours) \
            if s.tz_override_hours is not None else (item.taken, None)
        out.append(_copy(video, videos, dated(video.name, start)))
    return out


def move_to_trash(item: Item, root: Path) -> list[list[str]]:
    """Sposta gli originali dell'elemento in <root>/cancellare, con le stesse sottocartelle.

    Non cancella nulla. Ritorna le coppie [origine, destinazione] per poterli rimettere a posto.
    Tutto o niente: se un file non si sposta, quelli già spostati tornano al loro posto.
    """
    root = root.resolve()  # la scansione usa percorsi risolti (link simbolici, es. ~/Dropbox)
    trash = root / TRASH_DIR
    moved: list[list[str]] = []
    try:
        for src in [*item.files(), *item.companion_files()]:
            if not src.exists():
                src = cloud.stub_for(src)  # solo su iCloud: si sposta lo stub ".nome.icloud"
                if not src.exists():
                    continue
            dst = trash / src.relative_to(root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                dst = unique_path(dst.parent, dst.name)
            shutil.move(str(src), str(dst))  # stesso disco: è solo uno spostamento, istantaneo
            moved.append([str(src), str(dst)])
    except (OSError, ValueError):
        restore_from_trash(moved)
        raise
    return moved


def trash_item(session: "Session", item: Item, root: Path, base: dict | None = None) -> list[list[str]]:
    """X: sposta gli originali in "cancellare" E registra la scelta, insieme. Se il salvataggio
    non riesce (disco pieno, permessi) gli originali tornano al loro posto e la scelta in memoria
    torna quella di prima: mai file in "cancellare" senza traccia su disco. L'errore sale
    (SessionSaveError). base: la scelta da registrare (es. Annulla che la rimette), con "moved"
    aggiornato; senza base si registra una X nuova."""
    prev = session.decisions.get(item.id)
    moved = move_to_trash(item, root)   # tutto o niente
    try:
        if base is not None:
            session.decisions[item.id] = {**base, "moved": moved}
            session.save()
        else:
            session.set(item.id, "trash", moved=moved)
    except OSError as e:
        if prev is None:
            session.decisions.pop(item.id, None)
        else:
            session.decisions[item.id] = prev
        new_names: dict[Path, Path] = {}
        try:
            restore_from_trash(moved, new_names)
        except OSError as e2:
            # né salvato né rimesso a posto: la traccia resta almeno in memoria (Annulla funziona)
            session.decisions[item.id] = ({**base, "moved": moved} if base is not None else
                                          {"choice": "trash", "files": [], "frame": None,
                                           "with_video": False, "moved": moved})
            raise SessionSaveError(tr(
                '{e} — e non riesco a rimettere a posto gli originali ({e2}): sono in “{TRASH_DIR}”:\n{v0}',
                e=e, e2=e2, TRASH_DIR=TRASH_DIR, v0="\n".join(d for _, d in moved))) from e
        for attr in ("image", "raw", "video"):   # posto originale occupato: l'elemento è il file rinominato
            p = getattr(item, attr)
            if p is not None and p in new_names:
                setattr(item, attr, new_names[p])
        raise
    return moved


def restore_from_trash(moved: list[list[str]], new_names: dict[Path, Path] | None = None,
                       missing: list[Path] | None = None) -> list[Path]:
    """Rimette a posto i file spostati in 'cancellare'. Si può richiamare dopo un errore:
    i file già rimessi a posto vengono saltati. Se al posto originale c'è già un file con lo
    stesso nome non lo sovrascrive: usa un nome nuovo, che viene ritornato nella lista
    (e in new_names: posto originale → nome nuovo, per aggiornare l'elemento).
    In missing: i file che non c'erano più né in "cancellare" né al loro posto."""
    renamed: list[Path] = []
    for src, dst in reversed(moved):
        if Path(dst).exists():
            target = Path(src)
            if target.exists():
                target = unique_path(target.parent, target.name)
                renamed.append(target)
                if new_names is not None:
                    new_names[Path(src)] = target
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(dst, str(target))
        elif missing is not None and not Path(src).exists():
            missing.append(Path(src))   # tolto a mano da "cancellare": non si può rimettere
        # toglie le cartelle rimaste vuote dentro "cancellare" (mai oltre)
        d = Path(dst).parent
        while d.name and TRASH_DIR in d.parts:
            try:
                d.rmdir()
            except OSError:
                break
            if d.name == TRASH_DIR:
                break
            d = d.parent
    return renamed


def relocate_exports(files: list[str], old_root: Path, new_root: Path) -> list[list[str]]:
    """Sposta copie già esportate da old_root a new_root, con le stesse sottocartelle (es. Video).

    Solo copie in export, mai originali; non sovrascrive (nome nuovo se occupato).
    Ritorna le coppie [prima, dopo] dei file spostati."""
    out: list[list[str]] = []
    for f in files:
        src = Path(f)
        try:
            rel = src.relative_to(old_root)
        except ValueError:
            continue  # non è sotto la cartella di partenza: si lascia dov'è
        if not src.exists():
            continue
        dst = unique_path((new_root / rel).parent, src.name)
        os.replace(src, dst)
        release_claims([src])
        _claim([dst])
        out.append([str(src), str(dst)])
    return out


def refile_favorite(files: list[str], export_dir: Path, favorite: bool) -> list[list[str]]:
    """♥: le foto di un elemento passano tra export/Foto ed export/Foto/Preferite (anche quelle
    fatte dalle versioni di prima, in export o export/Preferite). I video restano in export/Video.
    Solo copie in export, mai originali; non sovrascrive. Ritorna le coppie [prima, dopo]."""
    export_dir = Path(export_dir)
    favs = (photo_dir(export_dir, True), export_dir / FAV_SUBDIR)   # nuova e vecchia posizione
    target = photo_dir(export_dir, favorite)
    out: list[list[str]] = []
    for f in files:
        src = Path(f)
        if not src.exists() or src.suffix.lower() in VIDEO_EXT:
            continue
        try:
            src.relative_to(export_dir)
        except ValueError:
            continue   # non è in export: non si tocca
        in_fav = any(src.parent == d for d in favs)
        if in_fav == favorite and src.parent == target:
            continue   # già al posto giusto
        if favorite and in_fav:
            continue   # già fra le preferite (posizione vecchia): resta lì
        dst = unique_path(target, src.name)
        os.replace(src, dst)
        release_claims([src])
        _claim([dst])
        out.append([str(src), str(dst)])
    return out


_DATE_PREFIX = re.compile(r"^\d{4}_\d{8}_\d{6}_")   # "0001_20240615_123456_": rinomina delle versioni di prima


def rename_by_date(entries: list[tuple[str, datetime, list[str]]], export_dir: Path,
                   errors: list[str] | None = None,
                   favorites: set[str] | None = None) -> dict[str, list[list[str]]]:
    """Mette in ordine le copie in export come le fa ora l'export: foto in export/Foto (preferite
    in export/Foto/Preferite), video in export/Video, nome con data e ora di scatto davanti
    (20240615_123456_nome.jpg). Serve per le copie fatte dalle versioni di prima (in export, senza
    data o con il numero 0001_ davanti). Solo copie in export, mai originali; non sovrascrive.
    entries: (id elemento, ora di scatto, copie). Ritorna, per elemento, le coppie [prima, dopo].
    Un file che non si riesce a spostare resta com'è e finisce in errors."""
    export_dir = Path(export_dir)
    favorites = favorites or set()
    out: dict[str, list[list[str]]] = {}
    for item_id, when, files in sorted(entries, key=lambda e: (e[1], e[0])):
        for f in files:
            src = Path(f)
            try:
                src.relative_to(export_dir)
            except ValueError:
                continue   # non è in export: non si tocca
            if not src.exists():
                continue
            # rifarlo non aggiunge un secondo prefisso; il vecchio numero 0001_ si toglie
            name = dated(src.name, when)   # toglie date vecchie e numero 0001_: mai due date
            if src.suffix.lower() in VIDEO_EXT:
                folder = video_dir(export_dir)
            elif src.parent == photo_dir(export_dir, True) or src.parent == export_dir / FAV_SUBDIR \
                    or item_id in favorites:
                folder = photo_dir(export_dir, True)
            else:
                folder = photo_dir(export_dir)
            if name == src.name and src.parent == folder:
                continue
            try:
                dst = unique_path(folder, name)
                os.replace(src, dst)
            except OSError as e:   # si continua: i file già spostati vanno comunque registrati
                if errors is not None:
                    errors.append(f"{src.name}: {e}")
                continue
            release_claims([src])
            out.setdefault(item_id, []).append([str(src), str(dst)])
    return out


def album_time(files: list[str], taken: datetime) -> datetime:
    """Ora di scatto per il nome nell'album: quella scritta nella copia (EXIF del JPEG, o nel nome
    per i file DJI), che per le foto prese dai video tiene conto del fuso scelto. Se non c'è,
    quella trovata alla scansione (taken)."""
    from scanner import capture_time
    for f in files:
        p = Path(f)
        if p.suffix.lower() not in (".jpg", ".jpeg", ".heic", ".heif", ".png", ".dng") \
                or not p.exists() or not cloud.is_local(p):
            continue
        try:   # prima l'EXIF: nel nome DJI c'è l'ora della camera, senza la correzione del fuso
            from PIL import Image
            edits.register_heif()   # HEIC dell'iPhone
            with Image.open(p) as im:
                exif = im.getexif()
                raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if raw:
                return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        except Exception:  # noqa: BLE001 - EXIF assente o rotto: si prova altro
            pass
        when = capture_time(p, True)
        if when:
            return when
    return taken


def file_stamp(path: Path) -> list[int]:
    """Impronta di una copia (dimensione, data di modifica): per riconoscerla prima di toglierla."""
    st = Path(path).stat()
    return [st.st_size, st.st_mtime_ns]


def remove_files(files: list[str], stamps: list[list[int]] | None = None) -> None:
    """Toglie copie fatte in export. Con stamps toglie solo i file che sono ancora QUELLE copie:
    se l'utente ne ha cancellata una a mano e un altro elemento ha riusato il nome, non si tocca."""
    known = {tuple(x) for x in stamps} if stamps else None
    release_claims(files)   # la scelta non c'è più: non sono più copie "in mano" a un export
    for f in files:
        try:
            if known is not None and tuple(file_stamp(Path(f))) not in known:
                continue
            Path(f).unlink()
        except FileNotFoundError:
            pass


# ---- compatibilità con salvataggi fatti altrove (altro livello, altro disco, altro computer)
SEARCH_UP = 4      # quante cartelle sopra si cerca un salvataggio fatto aprendo la cartella madre
SEARCH_DOWN = 3    # quanti livelli sotto (es. aperta DJI/1 ieri, oggi DJI/1/DCIM o il contrario)
_SKIP_DIRS = {TRASH_DIR, "export", PHOTO_SUBDIR, FAV_SUBDIR, VIDEO_SUBDIR}


def _key(k: str) -> str:
    """Chiave di un elemento sempre con "/" (i salvataggi fatti su Windows hanno "\\") e in
    Unicode NFC: lo stesso nome letto da un altro disco/sistema può arrivare in NFD ("è" = e + ` )."""
    return unicodedata.normalize("NFC", k.replace("\\", "/"))


def _normalize(decisions) -> dict[str, dict]:
    """Scelte lette da un salvataggio di qualsiasi versione: chiavi con "/" e tutti i campi
    che il resto dell'app si aspetta. Le voci senza una scelta valida si scartano."""
    out: dict[str, dict] = {}
    if not isinstance(decisions, dict):
        return out
    for k, d in decisions.items():
        if not isinstance(d, dict) or d.get("choice") not in ("yes", "no", "skip", "trash", "snap"):
            continue
        d = dict(d)
        d["files"] = [str(f) for f in d.get("files") or []]
        d.setdefault("frame", None)
        d.setdefault("with_video", False)
        out[_key(str(k))] = d
    return out


def _same_root(a, b) -> bool:
    """Stessa cartella, anche se il disco esterno oggi si chiama diversamente
    (/Volumes/Backup → /Volumes/Backup 1)."""
    if not a or not b:
        return False
    pa, pb = Path(a).parts, Path(b).parts
    if pa == pb:
        return True
    import re
    if len(pa) >= 3 and len(pb) >= 3 and pa[1] == "Volumes" and pb[1] == "Volumes":
        clean_a = re.sub(r" \d+$", "", pa[2])
        clean_b = re.sub(r" \d+$", "", pb[2])
        return clean_a == clean_b and pa[3:] == pb[3:]
    return False


def _nearby_saves(root: Path) -> list[tuple[Path, Path]]:
    """Salvataggi fatti aprendo una cartella sopra o sotto questa: (file, cartella aperta allora)."""
    found: list[tuple[Path, Path]] = []
    for n, parent in enumerate(root.parents):
        if n >= SEARCH_UP or parent == Path(parent.anchor) or parent.name == "Volumes":
            break
        if (parent / SESSION_FILE).is_file():
            found.append((parent / SESSION_FILE, parent))

    def walk(folder: str, depth: int) -> None:
        if depth > SEARCH_DOWN:
            return
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if not is_dir or e.name.startswith(".") or e.name in _SKIP_DIRS:
                continue
            sub = Path(e.path)
            if (sub / SESSION_FILE).is_file():
                found.append((sub / SESSION_FILE, sub))
            walk(e.path, depth + 1)
    walk(str(root), 1)
    return found


def _rebase(decisions: dict[str, dict], base: Path, root: Path) -> dict[str, dict]:
    """Chiavi relative alla cartella aperta allora (base) → relative a quella aperta ora."""
    if base == root:
        return decisions
    if base in root.parents:                    # allora la cartella madre: si tiene solo la parte qui sotto
        prefix = _key(root.relative_to(base).as_posix()) + "/"
        return {k[len(prefix):]: d for k, d in decisions.items() if k.startswith(prefix)}
    prefix = _key(base.relative_to(root).as_posix()) + "/"   # allora una sottocartella
    return {prefix + k: d for k, d in decisions.items()}


def gather_saved(root: Path, own: dict | None) -> dict | None:
    """Il salvataggio di questa cartella unito a quelli fatti aprendo una cartella sopra o sotto
    (stesso lavoro, aperto a un altro livello). I vecchi file non vengono mai modificati: si
    leggono soltanto, e da qui in poi si salva nella cartella aperta ora. A parità di elemento
    vince il salvataggio modificato più di recente. Dopo "Ricomincia da capo" non si uniscono."""
    sources = []
    if own:
        sources.append((own, root))
    if not (own and own.get("fresh")):
        for f, base in _nearby_saves(root):
            data = Session.read(f)
            if isinstance(data, dict) and data.get("decisions"):
                sources.append((data, base))
    if not sources:
        return own
    merged = dict(own or max((d for d, _ in sources), key=lambda d: d.get("updated") or ""))
    decisions: dict[str, dict] = {}
    favorites: set[str] = set()
    edit_map: dict[str, dict] = {}
    for data, base in sorted(sources, key=lambda s: s[0].get("updated") or ""):
        decisions.update(_rebase(_normalize(data.get("decisions")), base, root))
        ed = {_key(str(k)): v for k, v in (data.get("edits") or {}).items() if isinstance(v, dict)}
        edit_map.update(_rebase(ed, base, root))
        favs = {_key(str(k)): {} for k in data.get("favorites") or []}
        favorites |= set(_rebase(favs, base, root))
    merged["decisions"], merged["favorites"] = decisions, sorted(favorites)
    merged["edits"] = edit_map
    newest = max(sources, key=lambda s: s[0].get("updated") or "")[0]
    merged["updated"] = newest.get("updated")
    merged.setdefault("export", newest.get("export"))
    if len(sources) > 1 or sources[0][1] != root:
        merged.pop("decided", None)    # si ricontano sulle scelte unite
        merged["completed"] = False
    return merged


class SessionSaveError(OSError):
    """Il lavoro non si è potuto salvare da nessuna parte (né nella cartella né in export)."""


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _newest(*found: tuple[dict | None, Path]) -> dict | None:
    """Il salvataggio più recente tra quelli trovati (ultimo salvataggio, poi data del file):
    se una volta non si è potuto salvare nella cartella, quello in export è più nuovo."""
    ok = [(d, p) for d, p in found if isinstance(d, dict)]
    if not ok:
        return None
    return max(ok, key=lambda dp: (str(dp[0].get("updated") or ""), _mtime_ns(dp[1])))[0]


class Session:
    """Lavoro salvato DENTRO la cartella che si sta guardando (scrittura atomica).

    Contiene le scelte, la cartella export usata, le date (inizio, ultimo salvataggio, chiusura)
    e se il lavoro è completato. Se la cartella non è scrivibile si salva nella cartella export
    (anche se un salvataggio nella cartella non riesce: disco pieno, permessi tolti).
    """

    def __init__(self, root: Path, export_dir: Path, total: int = 0, ids=None):
        self.root = str(root)
        self.export_dir = str(export_dir)
        # ids = elementi trovati dalla scansione: "decise" conta solo quelli, così le scelte
        # su elementi ormai spostati in "cancellare" non contano né in total né in decided
        self.ids: set[str] | None = {_key(str(i)) for i in ids} if ids is not None else None
        self.total = len(self.ids) if self.ids is not None else total
        self.decisions: dict[str, dict] = {}
        self.favorites: set[str] = set()
        self.edits: dict[str, dict] = {}   # Regola / Ritaglia per elemento (anche non ancora deciso)
        now = _now()
        self.created, self.updated, self.closed = now, now, None
        self.path = root / SESSION_FILE
        self.corrupt_backup: Path | None = None  # salvataggio illeggibile messo da parte
        self.saved_elsewhere: Path | None = None  # salvato in export perché nella cartella non si poteva
        self._protected: set[str] = set()   # salvataggi illeggibili lasciati al loro posto: mai sovrascritti
        self.fresh = False   # "Ricomincia da capo": non riprendere salvataggi di altri livelli
        _sessions.add(self)
        fallback = export_dir / SESSION_FILE
        # il proprio salvataggio, e quello in export (vecchie versioni, o salvato lì perché nella
        # cartella non si poteva): vince il più recente
        own = _newest((self._load(self.path), self.path),
                      (self._load(fallback, root) if fallback != self.path else None, fallback))
        self.fresh = bool(own and own.get("fresh"))
        data = gather_saved(root, own)
        if data:
            self.decisions = _normalize(data.get("decisions", {}))
            self.favorites = {_key(str(k)) for k in data.get("favorites", [])}
            self.edits = {_key(str(k)): v for k, v in (data.get("edits") or {}).items()
                          if isinstance(v, dict) and v}
            self.created = data.get("created", now)
            self.updated = data.get("updated", now)
        if not _writable(root) or _norm_path(self.path) in self._protected:
            self.path = fallback

    def _load(self, path: Path, root: Path | None = None) -> dict | None:
        """Come read(), ma un salvataggio presente e illeggibile non viene perso: si rinomina
        in .corrupt (mai sovrascritto) e si segnala in corrupt_backup. Se non si può rinominare
        (cartella di sola lettura) resta com'è, intatto: se ne mette una copia nella cartella
        export e da qui in poi si salva lì. Con root: un salvataggio valido ma di un'altra
        cartella si ignora (e non si tocca)."""
        if not path.exists() and cloud.stub_for(path).exists():
            cloud.download(path, timeout=60)  # salvataggio solo su iCloud
        if not path.exists():
            if cloud.stub_for(path).exists():
                raise OSError(tr('Salvataggio non scaricabile da iCloud: {path}', path=path))
            return None
        try:
            data = json.loads(path.read_text("utf-8"))
            if isinstance(data, dict) and isinstance(data.get("decisions", {}), dict):
                if root is not None and not _same_root(data.get("root"), root):
                    if data.get("root") is not None:
                        self._protected.add(_norm_path(path))   # di un'altra cartella: mai sopra
                    return None
                return data
        except (OSError, ValueError):
            pass
        name = f"{SESSION_FILE}.{datetime.now():%Y%m%d-%H%M%S}.corrupt"
        try:
            bak = unique_path(path.parent, name)
            os.replace(path, bak)
            self.corrupt_backup = bak
            return None
        except OSError:
            pass
        # non si può rinominare: il file resta intatto al suo posto e non si salva mai sopra
        self._protected.add(_norm_path(path))
        self.corrupt_backup = self._backup_copy(path, name)
        return None

    def _backup_copy(self, path: Path, name: str) -> Path | None:
        """Copia di un salvataggio illeggibile nella cartella export. None se una copia identica
        c'è già (avvisato a un'apertura precedente); il file stesso se non si riesce a copiarlo."""
        folder = Path(self.export_dir)
        try:
            data = path.read_bytes()
        except OSError:
            return path
        for old in folder.glob(f"{SESSION_FILE}.*.corrupt"):
            try:
                if old.read_bytes() == data:
                    return None
            except OSError:
                continue
        try:
            bak = unique_path(folder, name)
            tmp = bak.with_name(bak.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, bak)
            return bak
        except OSError:
            return path

    def pending_exports(self, item_ids) -> list[str]:
        """Approvazioni la cui copia non è mai stata registrata (app chiusa o export fallito).

        Quelle con file registrati non si toccano MAI, anche se in export mancano dei file:
        li ha tolti o modificati l'utente, e rifarli o cancellarli farebbe danni."""
        return [k for k, d in self.decisions.items()
                if d["choice"] in ("yes", "snap") and not d.get("noexport")
                and not d["files"] and k.split("#")[0] in item_ids]

    def mark_export(self, item_id: str, token: str) -> None:
        """Lega la decisione all'export appena messo in coda."""
        d = self.decisions.get(item_id)
        if d is not None:
            d["export_id"] = token
            self.save()

    def record_export(self, item_id: str, token: str, res) -> str:
        """Registra l'esito di un export: 'ok', 'failed' o 'stale'.

        'stale' = la decisione è cambiata (annullata, rifatta, altra cartella): l'esito si ignora.
        Un export fallito NON cancella la scelta: resta un SÌ da ricopiare alla prossima apertura."""
        d = self.decisions.get(item_id)
        if d is None or d.get("export_id") != token or d["choice"] not in ("yes", "snap"):
            if isinstance(res, (list, tuple)):
                release_claims(res)   # copie senza più una scelta: alla ripresa si possono riusare
            return "stale"
        if isinstance(res, Exception):
            d["files"] = []
            d["export_failed"] = str(res)
            self.save()
            return "failed"
        d["files"] = [str(f) for f in res]
        try:
            d["stamps"] = [file_stamp(f) for f in res]
        except OSError:
            d.pop("stamps", None)
        d.pop("export_failed", None)
        self.save()
        return "ok"

    @staticmethod
    def read(path: Path, root: Path | None = None) -> dict | None:
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if root is not None and not _same_root(data.get("root"), root):
            return None
        return data

    @staticmethod
    def peek(root: Path, export: Path | None = None) -> dict | None:
        """Riassunto del lavoro salvato in questa cartella (o None se non ce n'è).

        Si guarda anche nella cartella export (quella proposta, quella scritta nel salvataggio
        e, se data, export): lì finisce il salvataggio quando nella cartella non si può scrivere."""
        mine = Session.read(root / SESSION_FILE)
        found = [(mine, root / SESSION_FILE)]
        exports = [root / "export"]
        if isinstance(mine, dict) and mine.get("export"):
            exports.append(Path(str(mine["export"])))
        if export is not None:
            exports.append(Path(export))
        for e in dict.fromkeys(exports):
            found.append((Session.read(e / SESSION_FILE, root), e / SESSION_FILE))
        own = _newest(*found)
        data = gather_saved(root, own if isinstance(own, dict) else None)
        if not data or not data.get("decisions"):
            return None
        c = _count(data["decisions"])
        decided = data.get("decided")  # vecchi salvataggi: si conta come prima
        if decided is None:
            decided = sum(1 for k in data["decisions"] if "#" not in k)
        export = data.get("export") or str(root / "export")
        return {"export": export, "export_ok": export_reachable(Path(export)),
                "created": data.get("created"), "updated": data.get("updated"),
                "closed": data.get("closed"), "total": data.get("total", 0),
                "decided": decided, "completed": bool(data.get("completed")), "counts": c}

    @property
    def decided(self) -> int:
        return sum(1 for k in self.decisions
                   if "#" not in k and (self.ids is None or k in self.ids))

    @property
    def completed(self) -> bool:
        return self.total > 0 and self.decided >= self.total

    def get(self, item_id: str) -> dict | None:
        return self.decisions.get(item_id)

    def set(self, item_id: str, choice: str, files: list[Path] | None = None,
            frame: int | None = None, with_video: bool = False,
            moved: list[list[str]] | None = None) -> None:
        self.decisions[item_id] = {"choice": choice, "files": [str(f) for f in files or []],
                                   "frame": frame, "with_video": with_video}
        if moved:
            self.decisions[item_id]["moved"] = moved
        self.save()

    def set_edit(self, item_id: str, edit: dict | None) -> None:
        edit = edits.clean(edit or {})
        if edit:
            self.edits[item_id] = edit
        else:
            self.edits.pop(item_id, None)
        self.save()

    def clear(self, item_id: str) -> None:
        self.decisions.pop(item_id, None)
        self.save()

    def toggle_favorite(self, item_id: str) -> bool:
        if item_id in self.favorites:
            self.favorites.discard(item_id)
        else:
            self.favorites.add(item_id)
        self.save()
        return item_id in self.favorites

    def relocated(self, item_id: str, token: str, pairs: list[list[str]]) -> bool:
        """Aggiorna i file registrati dopo uno spostamento (solo se la scelta è ancora quella)."""
        d = self.decisions.get(item_id)
        if d is None or d.get("export_id") != token:
            return False
        moved = {a: b for a, b in pairs}
        d["files"] = [moved.get(f, f) for f in d["files"]]
        self.save()
        return True

    def counts(self) -> dict[str, int]:
        return _count(self.decisions)

    def close(self) -> None:
        """Chiusura dell'app: segna quando il lavoro è stato interrotto o finito."""
        self.closed = _now()
        self.save(touch=False)

    def archive(self) -> None:
        """'Ricomincia da capo': il vecchio salvataggio viene rinominato, non cancellato."""
        stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        # anche il salvataggio delle vecchie versioni (in export), se è di questa cartella:
        # altrimenti alla riapertura verrebbe ricaricato e il "ricomincia" non avrebbe effetto
        root = Path(self.root)
        legacy = Path(self.export_dir) / SESSION_FILE
        for path in dict.fromkeys((self.path, root / SESSION_FILE, legacy)):
            if not path.exists() or _norm_path(path) in self._protected:
                continue
            if path == legacy and path != self.path and Session.read(path, root) is None:
                continue   # è il salvataggio di un'altra cartella: non si tocca
            try:
                os.replace(path, path.with_name(f"{SESSION_FILE}.{stamp}.bak"))
            except OSError:
                if path == self.path:
                    raise
                # cartella di sola lettura: resta, ma il nuovo salvataggio (più recente) vince
        self.decisions = {}
        self.favorites = set()
        self.edits = {}
        self.created = self.updated = _now()
        self.closed = None
        self.fresh = True
        if self.path.parent.exists() and _nearby_saves(Path(self.root)):
            self.save()   # ricorda la scelta: i salvataggi di altri livelli non si riprendono più

    def save(self, touch: bool = True) -> None:
        """Salva (scrittura atomica). Se nella cartella non si riesce (disco pieno, permessi),
        si salva nella cartella export e da lì in poi si continua lì (saved_elsewhere). Se non si
        riesce neanche lì: SessionSaveError, con un messaggio chiaro per l'utente."""
        if touch:
            self.updated = _now()
            self.closed = None
        try:
            self._write(self.path)
            return
        except OSError as e:
            first = e
        fallback = Path(self.export_dir) / SESSION_FILE
        if fallback != self.path and _norm_path(fallback) not in self._protected:
            other = Session.read(fallback)
            if not (isinstance(other, dict) and other.get("root")
                    and not _same_root(other.get("root"), self.root)):   # mai sopra quello di un'altra cartella
                try:
                    self._write(fallback)
                    self.path = self.saved_elsewhere = fallback
                    return
                except OSError as e:
                    raise SessionSaveError(tr(
                        "Non riesco a salvare il lavoro ({v0}). L'ultima scelta non è salvata.",
                        v0=f"{self.path.parent}: {first};  {fallback.parent}: {e}")) from e
        raise SessionSaveError(tr("Non riesco a salvare il lavoro ({v0}). L'ultima scelta non è salvata.",
                                  v0=f"{self.path.parent}: {first}")) from first

    def _write(self, path: Path) -> None:
        if _norm_path(path) in self._protected:
            # salvataggio illeggibile lasciato al suo posto: mai scriverci sopra
            raise PermissionError(errno.EPERM, os.strerror(errno.EPERM), str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "app": "PhotoSwipe", "root": self.root, "export": self.export_dir,
                    "created": self.created, "updated": self.updated, "closed": self.closed,
                    "total": self.total, "decided": self.decided, "completed": self.completed,
                    "decisions": self.decisions, "favorites": sorted(self.favorites),
                    **({"edits": self.edits} if self.edits else {}),
                    **({"fresh": True} if self.fresh else {}),
                }, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())  # su disco prima di sostituire il vecchio
            os.replace(tmp, path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise


def _count(decisions: dict) -> dict[str, int]:
    c = {"yes": 0, "no": 0, "skip": 0, "trash": 0}
    for d in decisions.values():
        c[d["choice"]] = c.get(d["choice"], 0) + 1
    return c


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def export_reachable(export_dir: Path) -> bool:
    """La cartella export esiste ed è scrivibile, o si può creare (senza crearla ora).
    Falso ad esempio se è su un disco esterno scollegato (/Volumes non è scrivibile)."""
    p = export_dir
    while not p.exists():
        if p.parent == p:
            return False
        p = p.parent
    return p.is_dir() and _writable(p)


def _writable(folder: Path) -> bool:
    probe = folder / ".photoswipe-write-test"
    try:
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def fmt_when(iso: str | None) -> str:
    if not iso:
        return "—"
    d = datetime.fromisoformat(iso)
    return f"{d:%d/%m/%Y} alle {d:%H:%M}"
