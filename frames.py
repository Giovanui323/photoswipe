"""Fotogrammi dai video: analisi, scelta del fotogramma e salvataggio alla massima qualità.

Regole (verificate sui file della Pocket 4):
- si lavora per *indice* di fotogramma, mai per tempo arrotondato, per non prendere quello accanto;
- si decodifica sempre l'MP4 originale a risoluzione piena (mai l'anteprima a schermo né l'LRF);
- JPEG: ffmpeg converte in RGB (conversione colore precisa) e Pillow salva q100, 4:4:4, sRGB.
  Il JPEG fatto direttamente da ffmpeg (yuvj444p) aveva una leggera dominante di colore.
"""
from __future__ import annotations

import os
import re
import shutil
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageChops, ImageCms, ImageFilter, ImageOps, ImageStat
from i18n import tr

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # niente finestre console su Windows


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError(tr('ffmpeg non trovato'))
        return exe


def _run(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run([ffmpeg_exe(), "-hide_banner", *args], capture_output=True,
                          timeout=timeout, creationflags=_NO_WINDOW)


# Frequenze "NTSC" scritte arrotondate da ffmpeg (29.97 = 30000/1001)
_NTSC = {23.98: Fraction(24000, 1001), 29.97: Fraction(30000, 1001),
         47.95: Fraction(48000, 1001), 59.94: Fraction(60000, 1001),
         119.88: Fraction(120000, 1001), 239.76: Fraction(240000, 1001)}


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: Fraction
    duration: float
    frames: int
    transfer: str = "bt709"        # bt709 normale; arib-std-b67 = HLG; altro = profilo log
    bits: int = 8
    created_utc: datetime | None = None
    encoder: str = ""
    source: Path | None = None                     # video usato per l'anteprima, se diverso (LRF)
    original_dims: tuple[int, int] | None = None   # dimensioni dell'MP4 originale, se note

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1e6

    @property
    def is_flat_profile(self) -> bool:
        return self.transfer not in ("bt709", "unknown", "")

    def time_of(self, n: int) -> float:
        """Istante che fa scegliere a ffmpeg esattamente il fotogramma n (primo con pts >= t)."""
        return max(0.0, float((n - Fraction(1, 2)) / self.fps))

    def frame_at(self, seconds: float) -> int:
        return max(0, min(self.frames - 1, int(seconds * self.fps + Fraction(1, 2))))


def probe(path: Path) -> VideoInfo:
    err = _run(["-i", str(path)], timeout=60).stderr.decode(errors="replace")
    m = re.search(r"Stream #0:\d+[^\n]*Video: [^\n]*", err)
    if not m:
        raise RuntimeError(tr('Nessun video in {v0}', v0=path.name))
    line = m.group(0)
    w, h = map(int, re.search(r", (\d{2,5})x(\d{2,5})", line).groups())
    fps_m = re.search(r", ([\d.]+) fps", line)
    fps_f = float(fps_m.group(1)) if fps_m else 30.0
    fps = _NTSC.get(round(fps_f, 2), Fraction(fps_f).limit_denominator(1001))
    pix = re.search(r"Video: [^,]+(?:\([^)]*\))*[^,]*, (\w+)(?:\(([^)]*)\))?", line)
    pix_fmt = pix.group(1) if pix else ""
    color = (pix.group(2) or "") if pix else ""
    parts = [p.strip() for p in color.split(",")]
    transfer = parts[-1] if len(parts) >= 2 else "bt709"
    if "/" in transfer:  # forma "bt709/bt709/arib-std-b67"
        transfer = transfer.split("/")[-1]
    bits = 10 if "10" in pix_fmt else 12 if "12" in pix_fmt else 8
    rot = re.search(r"rotation of (-?[\d.]+) degrees", err)
    if rot and round(abs(float(rot.group(1)))) % 180 == 90:
        w, h = h, w
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    duration = (int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) if d else 0.0
    from scanner import mp4_duration  # più preciso del valore arrotondato di ffmpeg
    duration = mp4_duration(path) or duration
    created = None
    c = re.search(r"creation_time\s*:\s*(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", err)
    if c:
        created = datetime.strptime(c.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    enc = re.search(r"encoder\s*:\s*(.+)", err)
    return VideoInfo(w, h, fps, duration, max(1, int(duration * fps + Fraction(1, 2))),
                     transfer, bits, created, enc.group(1).strip() if enc else "")


def spotlight_dims(path: Path) -> tuple[int, int] | None:
    """Larghezza/altezza di un video ancora su iCloud, da Spotlight (macOS), senza scaricarlo."""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(["mdls", "-raw", "-name", "kMDItemPixelWidth", "-name",
                              "kMDItemPixelHeight", str(path)], capture_output=True, timeout=10)
        w, h = (int(float(v)) for v in out.stdout.decode().split("\0")[:2])
        return (w, h) if w and h else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


_SCALE_EXACT = "scale=flags=accurate_rnd+full_chroma_int+full_chroma_inp"


def frame_rgb(video: Path, info: VideoInfo, n: int) -> Image.Image:
    """Fotogramma n a risoluzione piena, RGB 8 bit."""
    res = _run(["-ss", f"{info.time_of(n):.6f}", "-i", str(video), "-map", "0:v:0",
                "-frames:v", "1", "-vf", f"{_SCALE_EXACT},format=rgb24",
                "-f", "rawvideo", "-"])
    need = info.width * info.height * 3
    if len(res.stdout) < need:
        raise RuntimeError(res.stderr.decode(errors="replace")[-400:] or tr('fotogramma non letto'))
    return Image.frombytes("RGB", (info.width, info.height), res.stdout[:need])


def frame_preview(video: Path, info: VideoInfo, n: int, max_side: int = 1600) -> Image.Image:
    """Fotogramma n esatto, ridotto per lo schermo (per la modalità 'Cambia scena')."""
    scale = max_side / max(info.width, info.height)
    w, h = (max(2, int(info.width * scale) // 2 * 2), max(2, int(info.height * scale) // 2 * 2)) \
        if scale < 1 else (info.width, info.height)
    res = _run(["-ss", f"{info.time_of(n):.6f}", "-i", str(video), "-map", "0:v:0",
                "-frames:v", "1", "-vf", f"scale={w}:{h}:flags=bicubic,format=rgb24",
                "-f", "rawvideo", "-"])
    if len(res.stdout) < w * h * 3:
        raise RuntimeError(tr('anteprima non letta'))
    return Image.frombytes("RGB", (w, h), res.stdout[:w * h * 3])


def proxy_window(video: Path, info: VideoInfo, start: int, count: int) -> list[bytes]:
    """Fotogrammi start…start+count-1 dell'anteprima (.LRF, 720p), esatti, come JPEG in memoria.

    Una sola lettura (≈0,2 s per una Live intera) e ~100 KB a fotogramma: si mostrano subito
    mentre si sceglie, poi arriva quello a risoluzione piena."""
    res = _run(["-ss", f"{info.time_of(start):.6f}", "-i", str(video), "-map", "0:v:0",
                "-frames:v", str(count), "-c:v", "mjpeg", "-q:v", "4", "-f", "image2pipe", "-"],
               timeout=60)
    # nei dati JPEG un byte 0xFF è sempre seguito da 0x00: FF D8 compare solo a inizio immagine
    parts = res.stdout.split(b"\xff\xd8")[1:]
    return [b"\xff\xd8" + p for p in parts]


def strip_thumbs(video: Path, info: VideoInfo, count: int = 16, height: int = 96) -> list[Image.Image]:
    """Miniature distribuite su tutto il video, per la striscia dei fotogrammi (come in Foto).

    Si decodificano solo i fotogrammi chiave, 4 alla volta: per le miniature non serve quello esatto."""
    from concurrent.futures import ThreadPoolExecutor
    w = max(2, int(info.width * height / info.height) // 2 * 2)

    def one(i: int) -> Image.Image | None:
        n = int((i + 0.5) * info.frames / count)
        for fast in (["-skip_frame", "nokey"], []):  # senza fotogramma chiave dopo: decodifica normale
            res = _run([*fast, "-ss", f"{info.time_of(n):.3f}", "-i", str(video),
                        "-map", "0:v:0", "-frames:v", "1", "-vf", f"scale={w}:{height},format=rgb24",
                        "-f", "rawvideo", "-"], timeout=30)
            if len(res.stdout) >= w * height * 3:
                return Image.frombytes("RGB", (w, height), res.stdout[:w * height * 3])
        return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        return [im for im in pool.map(one, range(count)) if im is not None]


def _gray_frames(video: Path, info: VideoInfo, start: int, count: int, w: int, h: int):
    res = _run(["-ss", f"{info.time_of(start):.6f}", "-i", str(video), "-map", "0:v:0",
                "-frames:v", str(count), "-vf", f"scale={w}:{h},format=gray",
                "-f", "rawvideo", "-"], timeout=300)
    size = w * h
    data = res.stdout
    return [Image.frombytes("L", (w, h), data[i * size:(i + 1) * size])
            for i in range(len(data) // size)]


def camera_frame(video: Path, info: VideoInfo, screennail: Path | None) -> int:
    """Fotogramma che la fotocamera ha scelto come 'foto' (quello dell'anteprima .SCR).

    Senza .SCR: il fotogramma centrale (le Live registrano 1,5 s prima e dopo lo scatto).
    """
    middle = info.frames // 2
    if not screennail:
        return middle
    try:
        scr = ImageOps.autocontrast(Image.open(screennail).convert("L"), cutoff=1)
    except OSError:
        return middle
    w, h = scr.size
    frames = _gray_frames(video, info, 0, info.frames, w, h)
    if not frames:
        return middle
    # L'anteprima della fotocamera può essere più luminosa/contrastata del video:
    # si confrontano immagini con il contrasto normalizzato.
    diffs = [ImageStat.Stat(ImageChops.difference(ImageOps.autocontrast(f, cutoff=1), scr)).mean[0]
             for f in frames]
    best = min(range(len(diffs)), key=diffs.__getitem__)
    typical = statistics.median(diffs)
    # Sulle Live vere il migliore è nettamente sotto la media (rapporto 0,1-0,7);
    # se non spicca, l'anteprima non è riconoscibile e si usa il fotogramma centrale.
    return best if diffs[best] < 0.8 * typical else middle


def _sharpness(img: Image.Image) -> float:
    lap = img.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
    return ImageStat.Stat(lap).var[0]


def sharpest_near(video: Path, info: VideoInfo, n: int, radius: int = 6) -> int:
    start = max(0, n - radius)
    count = min(info.frames, n + radius + 1) - start
    w = 1280 if info.width >= info.height else 720
    h = int(info.height * w / info.width) // 2 * 2
    frames = _gray_frames(video, info, start, count, w, h)
    if not frames:
        return n
    scores = [_sharpness(f) for f in frames]
    best = max(range(len(scores)), key=scores.__getitem__)
    return start + best


# ---------------------------------------------------------------------------- salvataggio

_SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@dataclass
class FrameMeta:
    taken_local: datetime            # ora dello scatto (orologio della fotocamera o corretta)
    offset: timedelta | None         # fuso orario di taken_local, se noto
    source: str                      # nome del file video
    frame: int
    model: str = "Osmo Pocket 4"


def capture_times(name_time: datetime, info: VideoInfo,
                  tz_override_hours: float | None) -> tuple[datetime, timedelta | None]:
    """Ora locale + fuso. L'orologio della fotocamera può essere rimasto sul fuso di casa:
    con tz_override_hours si usa l'ora UTC registrata nel video con il fuso del viaggio."""
    if info.created_utc is None:
        return name_time, None
    camera_offset = timedelta(minutes=round((name_time - info.created_utc.replace(tzinfo=None))
                                            .total_seconds() / 900) * 15)
    if tz_override_hours is None:
        return name_time, camera_offset
    offset = timedelta(hours=tz_override_hours)
    return (info.created_utc + offset).replace(tzinfo=None), offset


def _fmt_offset(off: timedelta) -> str:
    minutes = int(off.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _exif(meta: FrameMeta) -> bytes:
    ex = Image.Exif()
    ex[0x010F] = "DJI"
    ex[0x0110] = meta.model
    ex[0x010E] = f"{meta.source} - fotogramma {meta.frame + 1}"  # contati da 1, come a schermo
    ex[0x0131] = "PhotoSwipe"
    stamp = meta.taken_local.strftime("%Y:%m:%d %H:%M:%S")
    ex[0x0132] = stamp
    sub = ex.get_ifd(0x8769)
    sub[0x9003] = stamp  # DateTimeOriginal
    sub[0x9004] = stamp  # DateTimeDigitized
    if meta.offset is not None:
        sub[0x9011] = _fmt_offset(meta.offset)  # OffsetTimeOriginal
        sub[0x9012] = _fmt_offset(meta.offset)
    return ex.tobytes()


def save_jpeg(img: Image.Image, out: Path, meta: FrameMeta) -> None:
    tmp = out.with_name(out.name + ".part")
    img.save(tmp, "JPEG", quality=100, subsampling=0, optimize=True,
             icc_profile=_SRGB, exif=_exif(meta))
    os.replace(tmp, out)


def save_png16(video: Path, info: VideoInfo, n: int, out: Path) -> None:
    """PNG a 16 bit: conserva i 10 bit del video (utile per cieli sfumati)."""
    tmp = out.with_name(out.name + ".part.png")
    res = _run(["-y", "-ss", f"{info.time_of(n):.6f}", "-i", str(video), "-map", "0:v:0",
                "-frames:v", "1", "-update", "1", "-vf", f"{_SCALE_EXACT},format=rgb48be",
                str(tmp)])
    if res.returncode != 0 or not tmp.exists():
        raise RuntimeError(res.stderr.decode(errors="replace")[-400:])
    os.replace(tmp, out)


def set_file_time(path: Path, when: datetime) -> None:
    ts = when.timestamp()
    os.utime(path, (ts, ts))


def print_hint(width: int, height: int) -> str:
    """Formato massimo consigliato (~200 dpi sul lato corto, carta 2:3)."""
    short_in = min(width, height) / 200
    for label, inches in (("30×45", 11.8), ("20×30", 7.87), ("13×18", 5.1), ("10×15", 3.9)):
        if short_in >= inches:
            return label
    return tr('meno di 10×15')
