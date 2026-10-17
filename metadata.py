"""Metadati da mostrare nel pannello Info: data, luogo (GPS), fotocamera, scatto, file.

Si legge solo ciò che è già sul disco (niente download da iCloud) e nulla viene inviato in rete:
il luogo è dato in coordinate, con un link per aprirlo nella mappa solo se l'utente lo clicca."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from PIL import Image

import frames


@dataclass
class Meta:
    rows: list[tuple[str, str]] = field(default_factory=list)   # (etichetta, valore), in ordine
    gps: tuple[float, float] | None = None                       # latitudine, longitudine
    altitude: float | None = None


def _ratio(v) -> float | None:
    try:
        if isinstance(v, tuple) and len(v) == 2:
            return v[0] / v[1] if v[1] else None
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _dms(values, ref: str) -> float | None:
    try:
        d, m, s = (_ratio(x) for x in values)
        val = d + m / 60 + s / 3600
    except (TypeError, ValueError):
        return None
    return -val if ref in ("S", "W") else val


def fmt_gps(lat: float, lon: float) -> str:
    return (f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'},  "
            f"{abs(lon):.5f}° {'E' if lon >= 0 else 'O'}")


def _exposure(t: float) -> str:
    if t >= 1:
        return f"{t:g} s"
    return f"1/{round(1 / t)} s" if t > 0 else ""


def _size(path: Path) -> str:
    try:
        n = path.stat().st_size
    except OSError:
        return ""
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


def read_image(path: Path) -> Meta:
    meta = Meta()
    try:
        with Image.open(path) as im:
            w, h = im.size
            exif = im.getexif()
            sub = exif.get_ifd(0x8769)
            gps = exif.get_ifd(0x8825)
    except Exception:  # noqa: BLE001 - file non leggibile: niente metadati, non è un errore
        return meta
    make, model = (exif.get(271) or "").strip(), (exif.get(272) or "").strip()
    if model:
        meta.rows.append(("Fotocamera", model if make and make.lower() in model.lower()
                          else f"{make} {model}".strip()))
    lens = (sub.get(42036) or "").strip()
    if lens:
        meta.rows.append(("Obiettivo", lens))
    shot = []
    f = _ratio(sub.get(33437))
    if f:
        shot.append(f"ƒ/{f:.1f}")
    t = _ratio(sub.get(33434))
    if t:
        shot.append(_exposure(t))
    iso = sub.get(34855)
    if isinstance(iso, tuple):
        iso = iso[0] if iso else None
    if iso:
        shot.append(f"ISO {iso}")
    fl, fl35 = _ratio(sub.get(37386)), sub.get(41989)
    if fl:
        shot.append(f"{fl:.1f} mm" + (f" (eq. {fl35} mm)" if fl35 else ""))
    ev = _ratio(sub.get(37380))
    if ev:
        shot.append(f"{ev:+.1f} EV")
    if shot:
        meta.rows.append(("Scatto", "  ·  ".join(shot)))
    offset = sub.get(36881) or sub.get(36880)
    if offset:
        meta.rows.append(("Fuso orario", f"UTC{offset}"))
    if gps:
        lat = _dms(gps.get(2), gps.get(1, "N")) if gps.get(2) else None
        lon = _dms(gps.get(4), gps.get(3, "E")) if gps.get(4) else None
        if lat is not None and lon is not None and (lat, lon) != (0.0, 0.0):
            meta.gps = (lat, lon)
        alt = _ratio(gps.get(6))
        if alt is not None:
            meta.altitude = -alt if gps.get(5) == 1 else alt
    meta.rows.append(("Dimensioni", f"{w} × {h}  ({w * h / 1e6:.1f} MP)"))
    return meta


_ISO6709 = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)?/?")


def read_video(path: Path, info: frames.VideoInfo | None) -> Meta:
    meta = Meta()
    try:
        err = frames._run(["-i", str(path)], timeout=60).stderr.decode(errors="replace")
    except Exception:  # noqa: BLE001
        err = ""
    def tag(*names):
        for n in names:
            m = re.search(rf"^\s*{re.escape(n)}\s*:\s*(.+)$", err, re.M)
            if m:
                return m.group(1).strip()
        return ""
    make = tag("com.apple.quicktime.make", "make")
    model = tag("com.apple.quicktime.model", "model")
    if model or make:
        meta.rows.append(("Fotocamera", f"{make} {model}".strip()))
    loc = tag("com.apple.quicktime.location.ISO6709", "location", "location-eng")
    m = _ISO6709.match(loc) if loc else None
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if (lat, lon) != (0.0, 0.0):
            meta.gps = (lat, lon)
        if m.group(3):
            meta.altitude = float(m.group(3))
    v = re.search(r"Video: (\w+)[^\n]*", err)
    if info:
        fps = float(info.fps) if isinstance(info.fps, Fraction) else info.fps
        meta.rows.append(("Video", f"{info.width} × {info.height}  ·  {fps:.3g} fps  ·  "
                                   f"{info.bits} bit" + (f"  ·  {v.group(1).upper()}" if v else "")))
        if info.is_flat_profile:
            meta.rows.append(("Colore", "HLG" if "b67" in info.transfer else f"log ({info.transfer})"))
        if info.duration:
            s = info.duration
            meta.rows.append(("Durata", f"{int(s // 60)}:{s % 60:04.1f}"))
    br = re.search(r"bitrate: (\d+) kb/s", err)
    if br:
        meta.rows.append(("Bitrate", f"{int(br.group(1)) / 1000:.1f} Mbit/s"))
    if re.search(r"Audio: ", err):
        a = re.search(r"Audio: (\w+)[^\n]*?(\d+) Hz[^\n]*?(mono|stereo|[\d.]+ channels)?", err)
        meta.rows.append(("Audio", f"{a.group(1).upper()} · {a.group(3) or ''}".strip(" ·") if a else "sì"))
    return meta


def read(item, info: frames.VideoInfo | None = None) -> Meta:
    """Tutti i metadati utili dell'elemento (foto, panorama, DNG, Live o video)."""
    if item.is_clip:
        meta = read_video(item.video, info)
        if item.image:  # foto abbinata al video
            meta.rows.extend(r for r in read_image(item.image).rows if r[0] != "Dimensioni")
    else:
        meta = read_image(item.image or item.raw)
    files = [p for p in (item.image, item.raw, item.video) if p]
    meta.rows.append(("File", "\n".join(f"{p.name}  ·  {_size(p)}" for p in files)))
    meta.rows.append(("Cartella", str(item.main.parent)))
    return meta
