"""Scansione cartelle e raggruppamento in elementi da valutare: foto, panorami, live, video."""
from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cloud

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
RAW_EXT = {".dng"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
# MISC = file di sistema DJI; PANORAMA = singoli scatti già uniti dalla fotocamera
SKIP_DIRS = {"MISC", "PANORAMA"}

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
        return [p for p in (self.proxy,) if p]

    def set_duration(self, seconds: float) -> None:
        self.duration = seconds
        if self.video and not self.image:
            self.kind = "live" if 0 < seconds <= LIVE_MAX_SECONDS else "video"


def mp4_duration(path: Path) -> float:
    """Legge la durata dall'atom 'mvhd' senza decodificare il video."""
    try:
        with open(path, "rb") as f:
            return _find_mvhd(f, 0, os.fstat(f.fileno()).st_size)
    except (OSError, struct.error, IndexError):
        return 0.0


def _find_mvhd(f, start: int, end: int) -> float:
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        size, kind = struct.unpack(">I4s", f.read(8))
        header = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return 0.0
        if kind == b"moov":
            return _find_mvhd(f, pos + header, pos + size)
        if kind == b"mvhd":
            version = f.read(1)[0]
            f.read(3)
            if version == 1:
                f.read(16)
                timescale, duration = struct.unpack(">IQ", f.read(12))
            else:
                f.read(8)
                timescale, duration = struct.unpack(">II", f.read(8))
            return duration / timescale if timescale else 0.0
        pos += size
    return 0.0


def spotlight_durations(paths: list[Path]) -> list[float]:
    if sys.platform != "darwin" or not paths:
        return [0.0] * len(paths)
    out: list[float] = []
    for i in range(0, len(paths), 200):
        chunk = paths[i:i + 200]
        try:
            res = subprocess.run(["mdls", "-raw", "-name", "kMDItemDurationSeconds", *map(str, chunk)],
                                 capture_output=True, timeout=60)
            values = res.stdout.decode(errors="replace").split("\0")
        except (OSError, subprocess.SubprocessError):
            values = []
        for j in range(len(chunk)):
            try:
                out.append(float(values[j]))
            except (IndexError, ValueError):
                out.append(0.0)
    return out


def capture_time(path: Path, local: bool) -> datetime:
    """Data di scatto: nome file DJI -> EXIF (solo se già scaricato) -> data di modifica."""
    m = _DJI_TS.search(path.name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    if local and path.suffix.lower() in {".jpg", ".jpeg"}:
        try:
            from PIL import Image
            with Image.open(path) as im:
                exif = im.getexif()
                raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if raw:
                return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return datetime.fromtimestamp(cloud.stub_for(path).stat().st_mtime)


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
    if exclude is None:
        exclude = []
    excluded = {p.resolve() for p in (exclude if isinstance(exclude, list) else [exclude])}
    # stesso nome base = stesso elemento (JPG+DNG, HEIC+MOV); se il tipo è già occupato
    # (IMG_0002.JPG + IMG_0002.HEIC) si apre un altro elemento invece di sovrascriverlo
    groups: dict[tuple[Path, str], list[dict[str, Path]]] = {}
    pano_indexes: set[tuple[Path, str]] = set()  # (cartella DCIM, indice)

    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        for n in dirnames:
            if n.upper() == "PANORAMA":
                try:
                    subs = os.listdir(d / n)
                except OSError:   # non leggibile: si salta, senza far fallire tutta la lettura
                    subs = []
                for sub in subs:
                    m = _PANO_DIR.match(sub)
                    if m:
                        pano_indexes.add((d, m.group(1)))
        dirnames[:] = sorted(
            n for n in dirnames
            if not n.startswith(".") and n.upper() not in SKIP_DIRS
            and (d / n).resolve() not in excluded
            and not (d == root and n == "export")   # l'export proposto: mai riletto come sorgente
        )
        for name in sorted(filenames):
            if name.startswith("."):
                name = cloud.real_name_of_stub(name) or ""
                if not name or name.startswith("._"):
                    continue  # file nascosti e "._" creati da macOS
            p = d / name
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
    seen: set[tuple[str, int]] = set()  # doppioni: stesso nome e stessa dimensione
    # Prima le cartelle più profonde (DCIM originale), poi le copie fatte a mano
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[0][0].parts), str(kv[0][0])))
    unknown: list[Item] = []
    for (folder, stem), files in ((k, g) for k, slots in ordered for g in slots):
        main = files.get("image") or files.get("video") or files["raw"]
        size = _size(main)
        if (main.name.upper(), size) in seen:
            continue
        seen.add((main.name.upper(), size))
        local = cloud.is_local(main)
        it = Item(kind="photo", id=main.relative_to(root).as_posix(), image=files.get("image"),
                  raw=files.get("raw"), video=files.get("video"),
                  taken=capture_time(main, local), size=size)
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

    # Video su iCloud: durata da Spotlight (macOS) senza scaricarli
    for it, seconds in zip(unknown, spotlight_durations([i.video for i in unknown])):
        if seconds:
            it.set_duration(seconds)
        elif it.size and it.size < LIVE_GUESS_MAX_BYTES:
            it.kind = "live"  # stima provvisoria, corretta dopo il download

    items.sort(key=lambda i: (i.taken, i.id))
    return items
