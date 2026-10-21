"""Nome del luogo dalle coordinate GPS, per il pannello Info: "📍 Bellagio, Lombardia · Italia".

Senza internet si usa l'elenco di GeoNames incluso nell'app (data/places.tsv.gz, località con più
di 1000 abitanti, CC BY 4.0). Con internet si chiede a OpenStreetMap (Nominatim), che conosce anche
frazioni e quartieri: si mandano solo le coordinate, al massimo una richiesta al secondo come chiede
il servizio, e la risposta si ricorda su disco così lo stesso posto non si chiede due volte.
Nelle impostazioni (online_switch) si può spegnere: allora non esce niente in rete."""
from __future__ import annotations

import gzip
import json
import math
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from i18n import LANG, tr

DATA = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "data" / "places.tsv.gz"
USER_AGENT = "PhotoSwipe (+https://github.com/Giovanui323/photoswipe)"
NEAR_KM = 4   # più lontano dalla località più vicina: "vicino a …"
ONLINE = True   # l'utente può spegnerlo nelle impostazioni

# paesi più comuni in italiano; gli altri restano col nome inglese di GeoNames
_PAESI = {
    "IT": "Italia", "SM": "San Marino", "VA": "Città del Vaticano", "CH": "Svizzera", "FR": "Francia",
    "DE": "Germania", "AT": "Austria", "SI": "Slovenia", "HR": "Croazia", "ES": "Spagna",
    "PT": "Portogallo", "GB": "Regno Unito", "IE": "Irlanda", "NL": "Paesi Bassi", "BE": "Belgio",
    "LU": "Lussemburgo", "DK": "Danimarca", "NO": "Norvegia", "SE": "Svezia", "FI": "Finlandia",
    "IS": "Islanda", "PL": "Polonia", "CZ": "Repubblica Ceca", "SK": "Slovacchia", "HU": "Ungheria",
    "RO": "Romania", "BG": "Bulgaria", "GR": "Grecia", "AL": "Albania", "ME": "Montenegro",
    "RS": "Serbia", "BA": "Bosnia ed Erzegovina", "MK": "Macedonia del Nord", "MT": "Malta",
    "CY": "Cipro", "TR": "Turchia", "RU": "Russia", "UA": "Ucraina", "EG": "Egitto", "MA": "Marocco",
    "TN": "Tunisia", "US": "Stati Uniti", "CA": "Canada", "MX": "Messico", "BR": "Brasile",
    "AR": "Argentina", "JP": "Giappone", "CN": "Cina", "IN": "India", "TH": "Thailandia",
    "AU": "Australia", "NZ": "Nuova Zelanda", "ZA": "Sudafrica", "AE": "Emirati Arabi Uniti",
    "MV": "Maldive", "IL": "Israele", "JO": "Giordania", "LT": "Lituania", "LV": "Lettonia",
    "EE": "Estonia", "MC": "Monaco", "AD": "Andorra", "LI": "Liechtenstein",
}


@dataclass
class _Index:
    lat: np.ndarray
    lon: np.ndarray
    names: list[str]
    regions: list[str]
    quarter: np.ndarray   # True: quartiere di una città, si aggiunge il nome della città
    region_names: dict[str, str]
    countries: dict[str, str]


_index: _Index | None = None
_index_lock = threading.Lock()


def _load() -> _Index | None:
    global _index
    with _index_lock:
        if _index is None and DATA.exists():
            lat, lon, names, regions, quarter, rnames, countries = [], [], [], [], [], {}, {}
            with gzip.open(DATA, "rt", encoding="utf-8") as f:
                for line in f:
                    p = line.rstrip("\n").split("\t")
                    if p[0] == "C":
                        countries[p[1]] = _PAESI.get(p[1], p[2]) if LANG == "it" else p[2]
                    elif p[0] == "R":
                        rnames[p[1]] = p[3] if LANG == "it" and p[3] else p[2]
                    else:
                        lat.append(float(p[0]))
                        lon.append(float(p[1]))
                        names.append(p[3] if LANG == "it" and p[3] else p[2])
                        regions.append(p[4])
                        quarter.append(p[5] == "x")
            _index = _Index(np.radians(lat), np.radians(lon), names, regions, np.array(quarter, bool),
                            rnames, countries)
        return _index


def offline(lat: float, lon: float) -> str:
    """Località più vicina dall'elenco incluso, es. "Bellagio, Lombardia · Italia"."""
    idx = _load()
    if idx is None or not idx.names:
        return ""
    la, lo = math.radians(lat), math.radians(lon)
    # distanza sulla sfera (haversine) da tutte le località: pochi millisecondi
    a = np.sin((idx.lat - la) / 2) ** 2 + math.cos(la) * np.cos(idx.lat) * np.sin((idx.lon - lo) / 2) ** 2
    i = int(np.argmin(a))
    km = 2 * 6371 * math.asin(math.sqrt(min(1.0, float(a[i]))))
    region = idx.regions[i]
    name, reg = idx.names[i], idx.region_names.get(region, "")
    if idx.quarter[i]:   # quartiere: anche la città, es. "Trevi, Roma"
        city = idx.names[int(np.argmin(np.where(idx.quarter, np.inf, a)))]
        name = f"{name}, {city}" if city != name else name
    place = name + (f", {reg}" if reg and reg != name else "")
    country = idx.countries.get(region.split(".")[0], "")
    text = place + (f" · {country}" if country else "")
    return tr('vicino a {v0}', v0=text) if km > NEAR_KM else text


# ---- online (OpenStreetMap)
_cache: dict[str, str] | None = None
_net_lock = threading.Lock()
_last_request = 0.0
_offline_until = 0.0   # dopo un errore di rete non si riprova per un minuto


def _cache_path() -> Path:
    base = (Path.home() / "Library" / "Caches" / "PhotoSwipe" if sys.platform == "darwin"
            else Path.home() / ".photoswipe")
    return base / f"places-{LANG}.json"


def _key(lat: float, lon: float) -> str:
    return f"{lat:.3f},{lon:.3f}"   # circa 100 m: le foto dello stesso posto fanno una sola richiesta


def _format(addr: dict) -> str:
    """"Trevi, Roma, Lazio · Italia": zona (se c'è), paese o città, regione e nazione."""
    name = next((addr[k] for k in ("city", "town", "village", "municipality", "county") if addr.get(k)), "")
    detail = next((addr[k] for k in ("quarter", "neighbourhood", "hamlet", "suburb")
                   if addr.get(k) and not addr[k].startswith("Municipio")), "")   # "Municipio Roma I": no
    if detail == name:
        detail = ""
    place = ", ".join(x for x in (detail, name, addr.get("state", "")) if x)
    country = addr.get("country", "")
    return place + (f" · {country}" if country and place else country)


def online(lat: float, lon: float, timeout: float = 3) -> str:
    """Nome del posto da OpenStreetMap; "" se non c'è internet o il servizio non risponde."""
    global _cache, _last_request, _offline_until
    key = _key(lat, lon)
    with _net_lock:
        if _cache is None:
            try:
                _cache = json.loads(_cache_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _cache = {}
        if key in _cache:
            return _cache[key]
        if not ONLINE or time.monotonic() < _offline_until:
            return ""
        time.sleep(max(0.0, _last_request + 1.0 - time.monotonic()))   # una richiesta al secondo
        _last_request = time.monotonic()
        q = urllib.parse.urlencode({"format": "jsonv2", "lat": f"{lat:.5f}", "lon": f"{lon:.5f}",
                                    "zoom": 16, "addressdetails": 1, "accept-language": LANG})
        req = urllib.request.Request(f"https://nominatim.openstreetmap.org/reverse?{q}",
                                     headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                text = _format(json.load(r).get("address") or {})
        except (OSError, ValueError):
            _offline_until = time.monotonic() + 60
            return ""   # niente rete: resta il nome dall'elenco incluso
        _cache[key] = text
        try:
            p = _cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return text


def online_switch(store):
    """Casella per le impostazioni: nome del luogo da OpenStreetMap sì / no, ricordata in `store`."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QCheckBox
    global ONLINE
    ONLINE = store.value("places_online", "1") != "0"
    box = QCheckBox(tr('Nome del luogo da OpenStreetMap'))
    box.setChecked(ONLINE)
    box.setFocusPolicy(Qt.NoFocus)
    box.setToolTip(tr("Con internet manda a OpenStreetMap solo le coordinate GPS della foto\n"
                      "per avere un nome più preciso (frazione, quartiere).\n"
                      "Spento: il nome viene dall'elenco incluso nell'app e nulla esce in rete."))

    def changed(on: bool):
        global ONLINE
        ONLINE = on
        store.setValue("places_online", "1" if on else "0")
    box.toggled.connect(changed)
    return box


def name(lat: float, lon: float) -> str:
    """Il nome più preciso che si riesce ad avere: OpenStreetMap se c'è rete, se no l'elenco incluso."""
    return online(lat, lon) or offline(lat, lon)


def info_html(m, color: str, link: str, esc) -> str:
    """Luogo nel pannello Info, staccato dal resto: 📍 e nome del posto (con "Mappa"), sotto in
    piccolo le coordinate, allineate al nome. Senza GPS una riga grigia lo dice (es. DJI Pocket)."""
    from theme import COLORS
    muted = COLORS["text_2"]

    def row(pin: str, body: str) -> str:   # tabella: la seconda riga resta allineata al nome
        return (f"<table cellspacing='0' cellpadding='0' style='margin-bottom:12px'>"
                f"<tr><td style='padding-right:5px'>{pin}</td><td>{body}</td></tr></table>")
    if not m.gps:
        return row(f"<span style='color:{muted}'>📍</span>",
                   f"<span style='color:{muted}'>{esc(tr('Luogo non registrato nella foto'))}</span>")
    lat, lon = m.gps
    url = (f"https://maps.apple.com/?ll={lat},{lon}&q={lat},{lon}" if sys.platform == "darwin"
           else f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=15/{lat}/{lon}")
    from metadata import fmt_gps
    coords = esc(fmt_gps(lat, lon)) + (f" · {m.altitude:.0f} m" if m.altitude else "")   # 0 m: niente
    maps = tr(" · <a style='color:{c}' href='{url}'>Mappa</a>", c=link, url=url)
    if m.place:
        body = (f"<span style='color:{color}; font-weight:600'>{esc(m.place)}</span>"
                f"<span style='font-size:12px'>{maps}</span>"
                f"<br><span style='color:{muted}; font-size:11px'>{coords}</span>")
    else:
        body = f"<span style='color:{color}'>{coords}</span><span style='font-size:12px'>{maps}</span>"
    return row("📍", body)
