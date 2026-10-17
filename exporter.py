"""Export (sempre copia, mai sposta) e sessione salvata per riprendere e annullare."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path

import cloud
import frames
from scanner import Item

SESSION_FILE = ".photoswipe-session.json"
TRASH_DIR = "cancellare"   # dentro la cartella sorgente: originali messi da parte, non cancellati
FAV_SUBDIR = "Preferite"  # le preferite approvate vanno in export/Preferite
VIDEO_SUBDIR = "Video"   # video separati: nella cartella export restano solo le foto da stampare


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
        return "La cartella export non può essere la stessa da guardare: scegline o creane un'altra."
    if export_dir == trash or trash in export_dir.parents:
        return (f"La cartella export non può stare dentro “{TRASH_DIR}”: "
                "lì vanno solo gli originali messi da parte.")
    if export_dir in root.parents:
        return ("La cartella export non può contenere la cartella da guardare: "
                "scegline o creane un'altra.")
    return None


def unique_path(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    stem, ext, i = p.stem, p.suffix, 2
    while p.exists():
        p = folder / f"{stem}_{i}{ext}"
        i += 1
    return p


def _copy(src: Path, folder: Path) -> Path:
    cloud.download(src)
    dst = unique_path(folder, src.name)
    tmp = dst.with_name(dst.name + ".part")
    shutil.copy2(src, tmp)  # copia identica, byte per byte
    os.replace(tmp, dst)
    return dst


def export_item(item: Item, frame: int | None, export_dir: Path, s: Settings,
                snapshot: bool = False) -> list[Path]:
    """Esegue l'export di un elemento approvato. Ritorna i file creati.

    snapshot=True: "Prendi foto" da un video, salva solo quel fotogramma (nome con _fNNNN).
    """
    out: list[Path] = []
    if item.kind in ("photo", "pano"):
        for src in (item.image, item.raw):
            if src:
                out.append(_copy(src, export_dir))
        if item.video and s.copy_video:  # Live Photo iPhone (HEIC+MOV): anche il video
            out.append(_copy(item.video, export_dir / VIDEO_SUBDIR))
        return out

    video = item.video
    assert video is not None
    cloud.download(video)
    if item.kind == "live" or frame is not None:
        info = frames.probe(video)
        if frame is None:
            frame = frames.camera_frame(video, info, item.screennail)
        when, offset = frames.capture_times(item.taken, info, s.tz_override_hours)
        when += timedelta(seconds=float(frame / info.fps))  # ora esatta del fotogramma
        stem = f"{video.stem}_f{frame + 1:04d}" if snapshot else video.stem
        if s.fmt == "png16":
            dst = unique_path(export_dir, stem + ".png")
            frames.save_png16(video, info, frame, dst)
        else:
            dst = unique_path(export_dir, stem + ".jpg")
            img = frames.frame_rgb(video, info, frame)
            frames.save_jpeg(img, dst, frames.FrameMeta(when, offset, video.name, frame))
        frames.set_file_time(dst, when)
        out.append(dst)
        if s.copy_video and not snapshot:
            out.append(_copy(video, export_dir / VIDEO_SUBDIR))
    else:
        # Video approvato senza scegliere una scena: si tiene il video originale
        out.append(_copy(video, export_dir / VIDEO_SUBDIR))
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


def restore_from_trash(moved: list[list[str]]) -> list[Path]:
    """Rimette a posto i file spostati in 'cancellare'. Si può richiamare dopo un errore:
    i file già rimessi a posto vengono saltati. Se al posto originale c'è già un file con lo
    stesso nome non lo sovrascrive: usa un nome nuovo, che viene ritornato nella lista."""
    renamed: list[Path] = []
    for src, dst in reversed(moved):
        if Path(dst).exists():
            target = Path(src)
            if target.exists():
                target = unique_path(target.parent, target.name)
                renamed.append(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(dst, str(target))
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
        out.append([str(src), str(dst)])
    return out


def remove_files(files: list[str]) -> None:
    for f in files:
        try:
            Path(f).unlink()
        except FileNotFoundError:
            pass


class Session:
    """Lavoro salvato DENTRO la cartella che si sta guardando (scrittura atomica).

    Contiene le scelte, la cartella export usata, le date (inizio, ultimo salvataggio, chiusura)
    e se il lavoro è completato. Se la cartella non è scrivibile si salva nella cartella export.
    """

    def __init__(self, root: Path, export_dir: Path, total: int = 0, ids=None):
        self.root = str(root)
        self.export_dir = str(export_dir)
        # ids = elementi trovati dalla scansione: "decise" conta solo quelli, così le scelte
        # su elementi ormai spostati in "cancellare" non contano né in total né in decided
        self.ids: set[str] | None = set(ids) if ids is not None else None
        self.total = len(self.ids) if self.ids is not None else total
        self.decisions: dict[str, dict] = {}
        self.favorites: set[str] = set()
        now = _now()
        self.created, self.updated, self.closed = now, now, None
        self.path = root / SESSION_FILE
        self.corrupt_backup: Path | None = None  # salvataggio illeggibile messo da parte
        data = (self._load(self.path)
                or Session.read(export_dir / SESSION_FILE, root))  # vecchie versioni
        if data:
            self.decisions = data.get("decisions", {})
            self.favorites = set(data.get("favorites", []))
            self.created = data.get("created", now)
            self.updated = data.get("updated", now)
        if not _writable(root):
            self.path = export_dir / SESSION_FILE

    def _load(self, path: Path) -> dict | None:
        """Come read(), ma un salvataggio presente e illeggibile non viene perso: si rinomina
        in .corrupt (mai sovrascritto) e si segnala in corrupt_backup. Se non si riesce a
        rinominarlo l'errore sale, così non si salva sopra."""
        if not path.exists() and cloud.stub_for(path).exists():
            cloud.download(path, timeout=60)  # salvataggio solo su iCloud
        if not path.exists():
            if cloud.stub_for(path).exists():
                raise OSError(f"Salvataggio non scaricabile da iCloud: {path}")
            return None
        try:
            data = json.loads(path.read_text("utf-8"))
            if isinstance(data, dict) and isinstance(data.get("decisions", {}), dict):
                return data
        except (OSError, ValueError):
            pass
        bak = path.with_name(f"{SESSION_FILE}.{datetime.now():%Y%m%d-%H%M%S}.corrupt")
        os.replace(path, bak)
        self.corrupt_backup = bak
        return None

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
            return "stale"
        if isinstance(res, Exception):
            d["files"] = []
            d["export_failed"] = str(res)
            self.save()
            return "failed"
        d["files"] = [str(f) for f in res]
        d.pop("export_failed", None)
        self.save()
        return "ok"

    @staticmethod
    def read(path: Path, root: Path | None = None) -> dict | None:
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if root is not None and data.get("root") != str(root):
            return None
        return data

    @staticmethod
    def peek(root: Path) -> dict | None:
        """Riassunto del lavoro salvato in questa cartella (o None se non ce n'è)."""
        data = Session.read(root / SESSION_FILE) or Session.read(root / "export" / SESSION_FILE, root)
        if not data or not data.get("decisions"):
            return None
        c = _count(data["decisions"])
        decided = data.get("decided")  # vecchi salvataggi: si conta come prima
        if decided is None:
            decided = sum(1 for k in data["decisions"] if "#" not in k)
        return {"export": data.get("export") or str(root / "export"),
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
        if self.path.exists():
            os.replace(self.path, self.path.with_name(
                f"{SESSION_FILE}.{datetime.now():%Y%m%d-%H%M%S}.bak"))
        self.decisions = {}
        self.favorites = set()
        self.created = self.updated = _now()
        self.closed = None

    def save(self, touch: bool = True) -> None:
        if touch:
            self.updated = _now()
            self.closed = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "app": "PhotoSwipe", "root": self.root, "export": self.export_dir,
                "created": self.created, "updated": self.updated, "closed": self.closed,
                "total": self.total, "decided": self.decided, "completed": self.completed,
                "decisions": self.decisions, "favorites": sorted(self.favorites),
            }, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())  # su disco prima di sostituire il vecchio
        os.replace(tmp, self.path)


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
