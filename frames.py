"""Fotogrammi dai video: analisi, scelta del fotogramma e salvataggio alla massima qualità.

Regole (verificate sui file della Pocket 4):
- si lavora per *indice* di fotogramma, mai per tempo arrotondato, per non prendere quello accanto;
- si decodifica sempre l'MP4 originale a risoluzione piena (mai l'anteprima a schermo né l'LRF);
- JPEG: ffmpeg converte in RGB (conversione colore precisa) e Pillow salva q100, 4:4:4, sRGB.
  Il JPEG fatto direttamente da ffmpeg (yuvj444p) aveva una leggera dominante di colore.
"""
from __future__ import annotations

import bisect
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
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


# ffmpeg in corso: all'uscita dell'app si fermano (kill_running), non restano orfani
_procs: set[subprocess.Popen] = set()
_procs_lock = threading.Lock()


def _run(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_exe(), "-hide_banner", *args]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    with _procs_lock:
        _procs.add(p)
    try:
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
            raise subprocess.TimeoutExpired(cmd, timeout, out, err) from None
        except BaseException:
            p.kill()
            p.wait()
            raise
    finally:
        with _procs_lock:
            _procs.discard(p)
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def kill_running() -> int:
    """Ferma tutti i processi ffmpeg ancora in corso (uscita dall'app). Ritorna quanti erano."""
    with _procs_lock:
        procs = list(_procs)
    for p in procs:
        try:
            p.kill()
        except OSError:
            pass
    return len(procs)


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
    created_local: datetime | None = None          # iPhone: ora dello scatto con il suo fuso
    # istanti veri dei fotogrammi (s, dall'inizio del file come li conta ffmpeg -ss): ci sono anche
    # coi video a frequenza variabile, l'audio più lungo del video o il video che parte in ritardo
    times: tuple[float, ...] | None = None

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1e6

    @property
    def is_flat_profile(self) -> bool:
        return self.transfer not in ("bt709", "unknown", "")

    def time_of(self, n: int) -> float:
        """Istante che fa scegliere a ffmpeg esattamente il fotogramma n (primo con pts >= t)."""
        if self.times and 0 < n < len(self.times):
            return (self.times[n - 1] + self.times[n]) / 2   # a metà fra il precedente e lui
        if self.times and n <= 0:
            return 0.0
        return max(0.0, float((n - Fraction(1, 2)) / self.fps))

    def seconds_of(self, n: int) -> float:
        """Quando si vede il fotogramma n (s dall'inizio)."""
        if self.times and 0 <= n < len(self.times):
            return self.times[n]
        return float(n / self.fps)

    def frame_at(self, seconds: float) -> int:
        if self.times:   # il fotogramma più vicino a quell'istante
            i = bisect.bisect_left(self.times, seconds)
            if i > 0 and (i == len(self.times) or seconds - self.times[i - 1] <= self.times[i] - seconds):
                i -= 1
            return max(0, min(self.frames - 1, i))
        return max(0, min(self.frames - 1, int(seconds * self.fps + Fraction(1, 2))))


def _video_line(err: str) -> str | None:
    """La riga del flusso video vero (non la copertina "attached pic", se ce n'è un altro)."""
    lines = re.findall(r"Stream #\d+:\d+[^\n]*Video: [^\n]*", err)
    real = [ln for ln in lines if "attached pic" not in ln]
    return (real or lines or [None])[0]


def _apple_created(err: str) -> datetime | None:
    """com.apple.quicktime.creationdate (iPhone): ora locale dello scatto con il suo fuso."""
    m = re.search(r"com\.apple\.quicktime\.creationdate\s*:\s*"
                  r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?\s*(Z|[+-]\d\d:?\d\d)", err)
    if not m:
        return None
    tz = m.group(2)
    try:
        if tz == "Z":
            off = timedelta(0)
        else:
            sign = -1 if tz[0] == "-" else 1
            digits = tz[1:].replace(":", "")
            off = sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
        return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone(off))
    except ValueError:
        return None


def probe(path: Path) -> VideoInfo:
    err = _run(["-i", str(path)], timeout=60).stderr.decode(errors="replace")
    line = _video_line(err)
    if not line:
        raise RuntimeError(tr('Nessun video in {v0}', v0=path.name))
    dims = re.search(r", (\d{2,5})x(\d{2,5})\b", line) or re.search(r"(?<![\dx])(\d{2,5})x(\d{2,5})\b", line)
    if not dims:
        raise RuntimeError(tr('Video non leggibile: {v0}', v0=path.name))
    w, h = map(int, dims.groups())
    fps_f = 0.0
    for pat in (r", ([\d.]+) fps", r", ([\d.]+) tbr"):
        fps_m = re.search(pat, line)
        try:
            fps_f = float(fps_m.group(1)) if fps_m else 0.0
        except ValueError:
            fps_f = 0.0
        if fps_f > 0:
            break
    if not 0 < fps_f < 10000:
        fps_f = 30.0
    fps = _NTSC.get(round(fps_f, 2), Fraction(fps_f).limit_denominator(1001))
    pix = re.search(r"Video: [^,]+(?:\([^)]*\))*[^,]*, (\w+)(?:\(([^)]*)\))?", line)
    pix_fmt = pix.group(1) if pix else ""
    color = (pix.group(2) or "") if pix else ""
    # "tv, bt709/bt709/arib-std-b67, progressive": si tolgono gamma (tv/pc) e ordine dei campi
    parts = [p.strip() for p in color.split(",")
             if p.strip() not in ("tv", "pc", "progressive", "top first", "bottom first",
                                  "top coded first (swapped)", "bottom coded first (swapped)")]
    transfer = parts[-1] if parts else "bt709"
    if "/" in transfer:  # forma "bt709/bt709/arib-std-b67"
        transfer = transfer.split("/")[-1]
    bits = 10 if "10" in pix_fmt else 12 if "12" in pix_fmt else 8
    rot = re.search(r"rotation of (-?[\d.]+) degrees", err)
    try:
        if rot and round(abs(float(rot.group(1)))) % 180 == 90:
            w, h = h, w
    except ValueError:
        pass
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    try:
        duration = (int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) if d else 0.0
    except ValueError:
        duration = 0.0
    from scanner import mp4_duration  # più preciso del valore arrotondato di ffmpeg
    try:
        duration = mp4_duration(path) or duration
    except Exception:  # noqa: BLE001 - resta quella di ffmpeg
        pass
    created = None
    c = re.search(r"creation_time\s*:\s*(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", err)
    if c:
        try:
            created = datetime.strptime(c.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            created = None
    local = _apple_created(err)
    if created is None and local is not None:
        created = local.astimezone(timezone.utc)
    enc = re.search(r"encoder\s*:\s*(.+)", err)
    times = frame_times(path)
    count = len(times) if times else max(1, int(duration * fps + Fraction(1, 2)))
    return VideoInfo(w, h, fps, duration, count,
                     transfer, bits, created, enc.group(1).strip() if enc else "",
                     created_local=local, times=times)


def frame_times(path: Path) -> tuple[float, ...] | None:
    """Gli istanti veri di tutti i fotogrammi, senza decodificare (solo i pacchetti: -c copy).
    Così il numero dei fotogrammi è quello vero (non la durata × fps, che conta anche l'audio
    più lungo) e i video a frequenza variabile si scorrono un fotogramma vero alla volta.
    None se non si riesce: si stima da durata e fps, come prima."""
    try:
        res = _run(["-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "framemd5", "-"], timeout=120)
    except Exception:  # noqa: BLE001
        return None
    out = res.stdout.decode(errors="replace")
    tb = re.search(r"^#tb 0: (\d+)/(\d+)", out, re.M)
    if res.returncode != 0 or not tb:
        return None
    unit = Fraction(int(tb.group(1)), int(tb.group(2)))
    pts = []
    for line in out.splitlines():
        if line and not line.startswith("#"):
            f = line.split(",")
            try:
                pts.append(int(f[2]))
            except (IndexError, ValueError):
                return None
    if not pts:
        return None
    pts.sort()
    return tuple(max(0.0, float(t * unit)) for t in pts)


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
    """Il fotogramma più nitido entro radius da n. Il numero di fotogrammi è stimato dalla durata:
    verso la fine possono essercene meno; si ritorna sempre un fotogramma che si è letto davvero."""
    n = max(0, min(n, info.frames - 1))
    w = 1280 if info.width >= info.height else 720
    h = max(2, int(info.height * w / max(1, info.width)) // 2 * 2)
    start = max(0, n - radius)
    count = min(info.frames, n + radius + 1) - start
    frames = _gray_frames(video, info, start, count, w, h) if count > 0 else []
    span = 2 * radius + 1
    back = span
    while not frames and start > 0:
        # oltre l'ultimo fotogramma vero (stima dalla durata): si torna indietro finché se ne
        # leggono, sempre al massimo span alla volta (memoria)
        start = max(0, n - back)
        frames = _gray_frames(video, info, start, span, w, h)
        back *= 2
    if not frames:
        return 0
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
    make: str = ""                   # fotocamera, se nota (prima si scriveva sempre "DJI Osmo Pocket 4")
    model: str = ""


def capture_times(name_time: datetime, info: VideoInfo,
                  tz_override_hours: float | None) -> tuple[datetime, timedelta | None]:
    """Ora locale + fuso. L'orologio della fotocamera può essere rimasto sul fuso di casa:
    con tz_override_hours si usa l'ora UTC registrata nel video con il fuso del viaggio.

    iPhone: il video dice ora e fuso dello scatto (com.apple.quicktime.creationdate) e vale
    quello, non il fuso del Mac. Senza: il fuso è quello valido in quel giorno (ora legale),
    non quello di oggi."""
    if tz_override_hours is not None and info.created_utc is not None:
        offset = timedelta(hours=tz_override_hours)
        return (info.created_utc + offset).replace(tzinfo=None), offset
    local = info.created_local
    if local is not None and local.utcoffset() is not None:
        return local.replace(tzinfo=None), local.utcoffset()
    if info.created_utc is None:
        return name_time, None
    # name_time dal video convertito all'ora del Mac (scanner.mp4_created): il fuso del Mac
    # valido in quell'istante, che con l'ora legale può essere diverso da quello di adesso
    mac = info.created_utc.astimezone()
    if abs((mac.replace(tzinfo=None) - name_time).total_seconds()) < 120:
        return name_time, mac.utcoffset()
    # orologio della fotocamera (nome del file DJI): la differenza con l'UTC registrato
    camera_offset = timedelta(minutes=round((name_time - info.created_utc.replace(tzinfo=None))
                                            .total_seconds() / 900) * 15)
    return name_time, camera_offset


def _fmt_offset(off: timedelta) -> str:
    minutes = int(off.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _exif(meta: FrameMeta) -> bytes:
    ex = Image.Exif()
    if meta.make:
        ex[0x010F] = meta.make
    if meta.model:
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
        tmp.unlink(missing_ok=True)   # interrotto (uscita) o fallito: niente file a metà
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
