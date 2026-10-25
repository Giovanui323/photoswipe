"""Scansione cartelle e raggruppamento in elementi da valutare: foto, panorami, live, video."""
from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cloud
from i18n import tr

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
RAW_EXT = {".dng"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
# MISC = file di sistema DJI; PANORAMA = singoli scatti già uniti dalla fotocamera
SKIP_DIRS = {"MISC", "PANORAMA"}
_MISC_SUBDIRS = {"THM", "GIS", "IDX", "LOG", "CACHE"}   # cosa c'è nella MISC di una scheda DJI
TRASH_DIR = "cancellare"   # originali messi da parte da PhotoSwipe: mai da riproporre

RAW_PREVIEW_MIN_PX = 1000  # anteprima DNG incorporata più piccola: si sviluppa il RAW
LIVE_MAX_SECONDS = 3.5  # le Live della Pocket 4 durano 3,04 s
LIVE_GUESS_MAX_BYTES = 26_000_000  # una Live 4K pesa al massimo ~23 MB

_DJI_TS = re.compile(r"(20\d{12})")
_DJI_INDEX = re.compile(r"_(\d{4})_[A-Z]$")
_PANO_DIR = re.compile(r"^\d{3}_(\d{4})$")


@dataclass
class Item:
    kind: str                      # "photo" | "pano" | "live" | "video"
    id: str                        # percorso relativo del file principale
    image: Path | None = None      # JPG/PNG/HEIC
    raw: Path | None = None        # DNG
    video: Path | None = None      # MP4/MOV
    taken: datetime = field(default_factory=datetime.now)
    duration: float = 0.0          # 0 = non ancora nota (file su iCloud)
    size: int = 0
    duplicates: list[Path] = field(default_factory=list)

    @property
    def main(self) -> Path:
        return self.image or self.video or self.raw  # type: ignore[return-value]

    @property
    def is_clip(self) -> bool:
        return self.kind in ("live", "video")

    def files(self) -> list[Path]:
        return [p for p in (self.image, self.raw, self.video) if p]

    @property
    def proxy(self) -> Path | None:
        """Anteprima DJI .LRF (720p) dello stesso video: fluida da riprodurre."""
        if not self.video:
            return None
        for ext in (".LRF", ".lrf"):
            p = self.video.with_suffix(ext)
            if p.exists() or cloud.stub_for(p).exists():
                return p
        return None

    @property
    def screennail(self) -> Path | None:
        """Anteprima .SCR in MISC/THM: è il fotogramma che la fotocamera mostra come foto."""
        if not self.video:
            return None
        dcim_sub = self.video.parent                  # .../DCIM/DJI_001
        p = dcim_sub.parent.parent / "MISC" / "THM" / dcim_sub.name / (self.video.stem + ".SCR")
        return p if (p.exists() or cloud.stub_for(p).exists()) else None

    @property
    def preview_video(self) -> Path | None:
        """Video usato per guardare: sempre l'MP4 originale (qualità massima)."""
        return self.video

    def needed_files(self) -> list[Path]:
        """File da avere in locale per guardare l'elemento: sempre l'originale (+ anteprima .SCR)."""
        if self.video and not self.image:
            return [p for p in (self.preview_video, self.screennail) if p]
        return [p for p in (self.image or self.raw, self.screennail) if p]  # solo DNG: il DNG

    def companion_files(self) -> list[Path]:
        """File che accompagnano l'originale (spostati insieme in 'cancellare')."""
        own = (self.image, self.raw, self.video)
        return [p for p in (self.proxy, *self.duplicates) if p and p not in own]

    def all_files(self) -> list[Path]:
        """Tutti i file dell'elemento (principali, accompagnatori e doppioni)."""
        return [*self.files(), *self.companion_files()]

    def set_duration(self, seconds: float) -> None:
        self.duration = seconds
        if self.video and not self.image:
            self.kind = "live" if 0 < seconds <= LIVE_MAX_SECONDS else "video"


def mp4_duration(path: Path) -> float:
    """Legge la durata dall'atom 'mvhd' senza decodificare il video."""
    try:
        with open(path, "rb") as f:
            return _find_mvhd(f, 0, os.fstat(f.fileno()).st_size)[0]
    except (OSError, struct.error, IndexError):
        return 0.0


def mp4_created(path: Path) -> datetime | None:
    """Data di creazione scritta nel video (atom 'mvhd', UTC), convertita all'ora locale."""
    try:
        with open(path, "rb") as f:
            seconds = _find_mvhd(f, 0, os.fstat(f.fileno()).st_size)[1]
    except (OSError, struct.error, IndexError):
        return None
    if not seconds:
        return None
    try:
        utc = datetime(1904, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
        return utc.astimezone().replace(tzinfo=None)
    except (OverflowError, ValueError, OSError):
        return None


def mp4_local_created(path: Path) -> datetime | None:
    """Ora locale dello scatto scritta dall'iPhone (com.apple.quicktime.creationdate, con il fuso
    del posto): la stessa ora "da parete" delle foto, così foto e video di un viaggio restano in
    ordine anche se il Mac è in un altro fuso. None se non c'è (si usa mp4_created)."""
    try:
        with open(path, "rb") as f:
            end = os.fstat(f.fileno()).st_size
            moov = _child(f, 0, end, b"moov")
            udta = moov and _child(f, *moov, b"udta")
            meta = moov and (_child(f, *moov, b"meta")   # iPhone: moov/meta; ffmpeg: moov/udta/meta
                             or (udta and _child(f, *udta, b"meta")))
            if not meta:
                return None
            start, stop = meta
            f.seek(start + 4)
            if f.read(4) != b"hdlr":   # meta "ISO" con versione/flag davanti (non QuickTime)
                start += 4
            keys, ilst = _child(f, start, stop, b"keys"), _child(f, start, stop, b"ilst")
            if not (keys and ilst):
                return None
            f.seek(keys[0] + 4)
            count = min(struct.unpack(">I", f.read(4))[0], 1024)
            names = []
            for _ in range(count):
                size = struct.unpack(">I", f.read(4))[0]
                if size < 8 or f.tell() + size - 4 > keys[1]:
                    return None
                f.read(4)   # namespace (mdta)
                names.append(f.read(size - 8))
            if b"com.apple.quicktime.creationdate" not in names:
                return None
            index = names.index(b"com.apple.quicktime.creationdate") + 1
            item = _child(f, *ilst, struct.pack(">I", index))
            data = item and _child(f, *item, b"data")
            if not data:
                return None
            f.seek(data[0] + 8)   # tipo e lingua
            text = f.read(min(data[1] - data[0] - 8, 64)).decode("utf-8", "replace")
    except (OSError, struct.error, IndexError, ValueError):
        return None
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", text)
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S") if m else None
    except ValueError:
        return None


def _child(f, start: int, end: int, kind: bytes) -> tuple[int, int] | None:
    """(inizio del contenuto, fine) del primo atom `kind` fra start e end."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        size, k = struct.unpack(">I4s", f.read(8))
        header = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return None
        if k == kind:
            return pos + header, min(pos + size, end)
        pos += size
    return None


def _find_mvhd(f, start: int, end: int) -> tuple[float, int]:
    """(durata in secondi, data di creazione in secondi dal 1904) dall'atom 'mvhd'."""
    pos = start
    try:
        while pos + 8 <= end:
            f.seek(pos)
            buf = f.read(8)
            if len(buf) < 8:
                return 0.0, 0
            size, kind = struct.unpack(">I4s", buf)
            header = 8
            if size == 1:
                buf8 = f.read(8)
                if len(buf8) < 8:
                    return 0.0, 0
                size = struct.unpack(">Q", buf8)[0]
                header = 16
            elif size == 0:
                size = end - pos
            if size < header:
                return 0.0, 0
            if kind == b"moov":
                return _find_mvhd(f, pos + header, min(pos + size, end))
            if kind == b"mvhd":
                vbuf = f.read(1)
                if not vbuf:
                    return 0.0, 0
                version = vbuf[0]
                f.read(3)
                if version == 1:
                    created = struct.unpack(">Q", f.read(8))[0]
                    f.read(8)
                    timescale, duration = struct.unpack(">IQ", f.read(12))
                else:
                    created = struct.unpack(">I", f.read(4))[0]
                    f.read(4)
                    timescale, duration = struct.unpack(">II", f.read(8))
                return (duration / timescale if timescale else 0.0), created
            pos += size
    except (OSError, struct.error, IndexError):
        return 0.0, 0
    return 0.0, 0


def _mdls_call(attr: str, paths: list[str]) -> list[str] | None:
    """Una chiamata a mdls -raw: un valore per file, separati da NUL. None se il numero di
    valori non torna (mdls si ferma al primo file che non trova, scrivendo un errore)."""
    try:
        res = subprocess.run(["mdls", "-raw", "-name", attr, *paths], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    values = res.stdout.decode(errors="replace").split("\0")
    return values if len(values) == len(paths) else None


def _mdls(attr: str, paths: list[Path]) -> list[str | None]:
    """Valore Spotlight (testo) per ogni file, None se non c'è. Solo i file che esistono
    (uno stub iCloud ".nome.icloud" non ha i dati della foto: si salta); se il blocco non
    torna si chiede file per file, così un solo file sparito non fa perdere gli altri."""
    out: list[str | None] = [None] * len(paths)
    present = [i for i, p in enumerate(paths) if p is not None and os.path.exists(p)]
    for k in range(0, len(present), 200):
        idx = present[k:k + 200]
        values = _mdls_call(attr, [str(paths[i]) for i in idx])
        if values is None:
            values = []
            for i in idx:
                one = _mdls_call(attr, [str(paths[i])])
                values.append(one[0] if one else None)
        for i, v in zip(idx, values):
            out[i] = v
    return out


def spotlight_durations(paths: list[Path]) -> list[float]:
    if sys.platform != "darwin" or not paths:
        return [0.0] * len(paths)
    out: list[float] = []
    for text in _mdls("kMDItemDurationSeconds", paths):
        try:
            out.append(float(text.strip()) if text else 0.0)
        except ValueError:   # "(null)": non indicizzato
            out.append(0.0)
    return out


def _parse_mdls_date(text: str | None) -> datetime | None:
    text = (text or "").strip()
    try:   # "2026-07-23 21:54:08 +0200": con il fuso, convertito all'ora locale
        return datetime.strptime(text[:25], "%Y-%m-%d %H:%M:%S %z").astimezone().replace(tzinfo=None)
    except ValueError:
        try:
            return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def spotlight_dates(paths: list[Path]) -> list[datetime | None]:
    """Data di creazione dal sistema (macOS, Spotlight): serve per HEIC, PNG, DNG e video senza data."""
    if sys.platform != "darwin" or not paths:
        return [None] * len(paths)
    return [_parse_mdls_date(t) for t in _mdls("kMDItemContentCreationDate", paths)]


_HEIF = []


def _register_heif() -> None:
    """HEIC in Pillow (pi-heif) per leggerne l'EXIF; una volta sola, se c'è."""
    if not _HEIF:
        _HEIF.append(True)
        try:
            from pi_heif import register_heif_opener
            register_heif_opener()
        except Exception:  # noqa: BLE001 - pi-heif assente: resta Spotlight
            pass


def capture_time(path: Path, local: bool) -> datetime | None:
    """Data di scatto: nome file DJI -> EXIF (JPEG, PNG, HEIC, DNG, solo se già scaricato) -> data nel video.
    None se non c'è: si chiede a Spotlight, poi si usa la data del file (file_time)."""
    m = _DJI_TS.search(path.name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    if local and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".heif", ".dng"}:
        try:
            from PIL import Image
            if path.suffix.lower() in {".heic", ".heif"}:
                _register_heif()
            with Image.open(path) as im:   # il DNG è un TIFF: Pillow ne legge l'EXIF
                exif = im.getexif()
                raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if raw:
                return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
    if local and path.suffix.lower() in {".mp4", ".mov", ".m4v"}:
        created = mp4_local_created(path) or mp4_created(path)
        if created:
            return created
    return None


def _same_content(a: Path, b: Path, chunk: int = 1 << 20) -> bool:
    """Due file con stesso nome e dimensione sono lo stesso scatto? Si confrontano inizio e fine
    (i RAW non compressi hanno tutti la stessa dimensione, e i contatori ripartono su ogni scheda).
    Un file solo su iCloud non si legge (si scaricherebbe): nel dubbio si tengono entrambi."""
    if not (cloud.is_local(a) and cloud.is_local(b)):
        return False
    try:
        size = a.stat().st_size
        with open(a, "rb") as fa, open(b, "rb") as fb:
            if fa.read(chunk) != fb.read(chunk):
                return False
            if size > chunk:
                fa.seek(-chunk, os.SEEK_END)
                fb.seek(-chunk, os.SEEK_END)
                return fa.read(chunk) == fb.read(chunk)
            return True
    except OSError:
        return False


def file_time(path: Path, local: bool) -> datetime:
    """Ultima risorsa: la data di modifica del file (dopo una copia è il giorno della copia)."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        pass
    try:
        return datetime.fromtimestamp(cloud.stub_for(path).stat().st_mtime)
    except OSError:  # link rotto, o file sparito durante la scansione (iCloud che sincronizza)
        return datetime.now()


def refresh_capture_time(item: Item) -> bool:
    """Dopo il download da iCloud: rilegge la data di scatto vera (nome DJI, EXIF, data nel video,
    poi Spotlight) e aggiorna item.taken. Alla scansione, per un file non ancora scaricato, c'era
    solo la data del file. True se è cambiata; False se il file non è ancora in locale o se non
    si trova niente di meglio (taken resta com'è)."""
    main = item.main
    if main is None or not cloud.is_local(main):
        return False
    when = capture_time(main, True)
    if when is None:
        when = spotlight_dates([main])[0]
    if when is None or when == item.taken:
        return False
    item.taken = when
    return True


def raw_preview(path: Path):
    """Anteprima di un DNG (Qt non legge i RAW): prima quella incorporata, se manca si
    sviluppa a metà risoluzione. Ritorna un'immagine PIL, o None se il file non si legge."""
    try:
        import io
        import rawpy
        from PIL import Image, ImageOps
        with rawpy.imread(str(path)) as raw:
            try:
                thumb = raw.extract_thumb()
            except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                thumb = None
            img = None
            if thumb is not None and thumb.format == rawpy.ThumbFormat.JPEG:
                img = ImageOps.exif_transpose(Image.open(io.BytesIO(thumb.data)))
            elif thumb is not None and thumb.format == rawpy.ThumbFormat.BITMAP:
                img = Image.fromarray(thumb.data)
            if img is not None and max(img.size) >= RAW_PREVIEW_MIN_PX:
                return img
            return Image.fromarray(raw.postprocess(half_size=True, use_camera_wb=True))
    except Exception:
        return None


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def scan(root: Path, exclude: Path | list[Path] | None = None) -> list[Item]:
    root = root.resolve()
    if not root.is_dir():   # disco scollegato, cartella spostata: va detto, non "nessuna foto"
        raise FileNotFoundError(tr('Cartella non trovata: {v0}', v0=root))
    if exclude is None:
        exclude = []
    excluded = {p.resolve() for p in (exclude if isinstance(exclude, list) else [exclude])}
    # stesso nome base = stesso elemento (JPG+DNG, HEIC+MOV); se il tipo è già occupato
    # (IMG_0002.JPG + IMG_0002.HEIC) si apre un altro elemento invece di sovrascriverlo
    groups: dict[tuple[Path, str], list[dict[str, Path]]] = {}
    pano_indexes: set[tuple[Path, str]] = set()  # (cartella DCIM, indice)

    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        system: set[str] = set()   # MISC / PANORAMA della DJI (non le cartelle dell'utente con quel nome)
        for n in dirnames:
            if n.upper() not in SKIP_DIRS:
                continue
            try:
                subs = os.listdir(d / n)
            except OSError:   # non leggibile: si salta, senza far fallire tutta la lettura
                subs = []
            if n.upper() == "PANORAMA":
                for sub in subs:
                    m = _PANO_DIR.match(sub)
                    if m:
                        pano_indexes.add((d, m.group(1)))
                        system.add(n)
            elif {x.upper() for x in subs} & _MISC_SUBDIRS or any(x.upper() == "DCIM" for x in dirnames):
                system.add(n)
        dirnames[:] = sorted(
            n for n in dirnames
            if not n.startswith(".") and n not in system
            and n != TRASH_DIR   # anche quella di una sottocartella, aprendo la cartella madre
            and (d / n).resolve() not in excluded
            and not (d == root and n == "export")   # l'export proposto: mai riletto come sorgente
        )
        for name in sorted(filenames):
            if name.startswith("."):
                name = cloud.real_name_of_stub(name) or ""
                if not name or name.startswith("."):
                    continue  # file nascosti (anche solo su iCloud) e "._" creati da macOS
            p = d / name
            if p.is_symlink():
                if not p.exists() and not cloud.stub_for(p).exists():
                    continue  # link rotto: non c'è niente da mostrare
                if root in Path(os.path.realpath(p)).parents:
                    continue  # link a un file della stessa cartella: si vede già com'è
            ext = p.suffix.lower()
            slot = ("image" if ext in IMAGE_EXT else "raw" if ext in RAW_EXT
                    else "video" if ext in VIDEO_EXT else None)
            if slot:  # .LRF, .THM, .SCR ecc. vengono ignorati
                slots = groups.setdefault((d, p.stem.upper()), [])
                free = next((g for g in slots if slot not in g), None)
                if free is None:
                    free = {}
                    slots.append(free)
                free[slot] = p

    items: list[Item] = []
    seen: dict[tuple[str, int], tuple[Item, Path]] = {}  # doppioni: stesso nome, dimensione e contenuto
    # Prima le cartelle più profonde (DCIM originale), poi le copie fatte a mano
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[0][0].parts), str(kv[0][0])))
    unknown: list[Item] = []
    undated: list[Item] = []   # senza data nel nome né nell'EXIF: si chiede a Spotlight
    for (folder, stem), files in ((k, g) for k, slots in ordered for g in slots):
        main = files.get("image") or files.get("video") or files["raw"]
        size = _size(main)
        first = seen.get((main.name.upper(), size)) if size else None   # 0 = solo su iCloud, dimensione ignota
        kept = first[0] if first and _same_content(first[1], main) else None
        if kept is not None:
            # doppione: si tiene il primo, ma se il doppione ha un file in più (es. il DNG, o il
            # MOV di una Live) lo si aggiunge, altrimenti non si vedrebbe/esporterebbe/sposterebbe mai.
            # Il file principale è dello stesso tipo (stesso nome), quindi l'id non cambia.
            dup = Item(kind="photo", id="", image=files.get("image"),
                       raw=files.get("raw"), video=files.get("video"))
            for slot in ("raw", "video", "image"):
                if slot in files and getattr(kept, slot) is None:
                    setattr(kept, slot, files[slot])
            for p in dup.all_files():
                if p not in kept.files() and p not in kept.duplicates:
                    kept.duplicates.append(p)
            continue
        local = cloud.is_local(main)
        taken = capture_time(main, local)
        # id in Unicode NFC (solo l'id, mai il percorso vero): uguale da qualsiasi disco/sistema
        rel = unicodedata.normalize("NFC", main.relative_to(root).as_posix())
        it = Item(kind="photo", id=rel, image=files.get("image"),
                  raw=files.get("raw"), video=files.get("video"),
                  taken=taken or file_time(main, local), size=size)
        if size and first is None:
            seen[(main.name.upper(), size)] = (it, main)
        if taken is None and local:
            undated.append(it)
        if it.image:
            idx = _DJI_INDEX.search(stem)
            if idx and (folder.parent, idx.group(1)) in pano_indexes:
                it.kind = "pano"
            # immagine + video con lo stesso nome (Live Photo iPhone, HEIC+MOV): resta una foto,
            # si esporta l'immagine originale e non un fotogramma del video
        elif it.video:
            it.kind = "video"
            if local:
                it.set_duration(mp4_duration(it.video))
            else:
                unknown.append(it)
        items.append(it)

    # Senza data nel nome né nell'EXIF (HEIC, PNG, DNG, video): la data di creazione di Spotlight,
    # così l'ordine segue davvero l'ora di scatto e non il giorno della copia
    for it, when in zip(undated, spotlight_dates([it.main for it in undated])):
        if when:
            it.taken = when

    # Video su iCloud: durata da Spotlight (macOS) senza scaricarli
    for it, seconds in zip(unknown, spotlight_durations([i.video for i in unknown])):
        if seconds:
            it.set_duration(seconds)
        elif it.size and it.size < LIVE_GUESS_MAX_BYTES:
            it.kind = "live"  # stima provvisoria, corretta dopo il download

    items.sort(key=lambda i: (i.taken, i.id))
    return items
