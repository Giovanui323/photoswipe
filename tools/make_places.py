"""Prepara data/places.tsv.gz (i luoghi per il pannello Info, senza internet) dai file di GeoNames.

Da https://download.geonames.org/export/dump/ (licenza CC BY 4.0) servono, in una cartella:
cities1000.txt (da cities1000.zip), admin1CodesASCII.txt, countryInfo.txt e IT.txt
(da alternatenames/IT.zip, per i nomi italiani dei luoghi in Italia).

    .venv/bin/python tools/make_places.py CARTELLA_GEONAMES

Righe del file: "R" codice regione, nome inglese, nome italiano · "C" paese, nome inglese ·
poi un luogo per riga: lat, lon, nome, nome italiano (vuoto se uguale), codice regione, "x" se è
un quartiere."""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "places.tsv.gz"
_SKIP = ("Comune di", "Provincia di", "Regione", "Repubblica", "Città metropolitana")


def italian_names(path: Path) -> dict[str, str]:
    """geonameid -> nome italiano: quello preferito, senza "Comune di …" e simili."""
    best: dict[str, tuple[int, str]] = {}
    for line in path.open(encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        if len(f) < 5 or f[2] != "it" or f[3].startswith(_SKIP):
            continue
        rank = 0 if f[4] == "1" else 1
        if f[1] not in best or rank < best[f[1]][0]:
            best[f[1]] = (rank, f[3])
    return {k: v for k, (_, v) in best.items()}


def main(src: Path) -> None:
    it = italian_names(src / "IT.txt")
    rows = []
    for line in (src / "countryInfo.txt").open(encoding="utf-8"):
        if not line.startswith("#"):
            f = line.split("\t")
            rows.append(f"C\t{f[0]}\t{f[4]}")
    for line in (src / "admin1CodesASCII.txt").open(encoding="utf-8"):
        code, name, _, gid = line.rstrip("\n").split("\t")
        rows.append(f"R\t{code}\t{name}\t{it.get(gid, '') if it.get(gid) != name else ''}")
    for line in (src / "cities1000.txt").open(encoding="utf-8"):
        f = line.split("\t")
        name, lat, lon, cc, adm = f[1], float(f[4]), float(f[5]), f[8], f[10]
        nit = it.get(f[0], "") if cc == "IT" else ""
        part = "x" if f[7] == "PPLX" else ""   # quartiere di una città (es. Trevi a Roma)
        rows.append(f"{lat:.4f}\t{lon:.4f}\t{name}\t{nit if nit != name else ''}\t{cc}.{adm}\t{part}")
    OUT.parent.mkdir(exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as out:
        out.write("\n".join(rows) + "\n")
    print(f"{OUT}: {len(rows)} righe, {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
