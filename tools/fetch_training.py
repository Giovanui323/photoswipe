"""Scarica foto di PUBBLICO DOMINIO / CC0 da Wikimedia Commons per insegnare l'AUTO.

Solo fotografie vere (con marca e modello della fotocamera nell'EXIF), solo JPEG, licenza
"Public domain" o "CC0": il modello che ne esce si può distribuire senza vincoli.
Le foto restano in build/train (fuori da git); in sources.json titolo, autore, licenza e link.

    .venv/bin/python tools/fetch_training.py --mb 150
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = "PhotoSwipe-training/1.0 (https://github.com/Giovanui323/photoswipe; auto-adjust research)"
CATEGORIES = ("Category:Featured_pictures_on_Wikimedia_Commons", "Category:Quality_images",
              "Category:Valued_images_sorted_by_promotion_date")
OK_LICENSES = {"public domain", "cc0", "cc0 1.0", "cc-zero", "pdm", "public domain mark"}


def get(url: str, params: dict | None = None) -> bytes:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:  # noqa: BLE001 - rete: si riprova con calma
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"download fallito: {url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mb", type=float, default=150)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "build" / "train"))
    a = ap.parse_args()
    out = Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    src_file = out / "sources.json"
    sources = json.loads(src_file.read_text()) if src_file.exists() else {}
    total = sum(f.stat().st_size for f in (out / "img").glob("*.jpg"))
    budget = a.mb * 1024 * 1024
    for cat in CATEGORIES:
        cont: dict = {}
        while total < budget:
            params = {"action": "query", "format": "json", "generator": "categorymembers",
                      "gcmtitle": cat, "gcmtype": "file", "gcmlimit": "50", "prop": "imageinfo",
                      "iiprop": "url|extmetadata|mime|commonmetadata", "iiurlwidth": "960",
                      "iiextmetadatafilter": "LicenseShortName|Artist|UsageTerms", **cont}
            data = json.loads(get(API, params))
            for page in (data.get("query") or {}).get("pages", {}).values():
                info = (page.get("imageinfo") or [{}])[0]
                if info.get("mime") != "image/jpeg" or str(page["pageid"]) in sources:
                    continue
                lic = info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
                if lic.strip().lower() not in OK_LICENSES:
                    continue
                meta = {m["name"]: m["value"] for m in info.get("commonmetadata", [])
                        if isinstance(m, dict) and "name" in m}
                if not meta.get("Make") or not meta.get("Model"):
                    continue   # niente scansioni, dipinti o grafica: solo foto da fotocamera
                thumb = info.get("thumburl")
                if not thumb:
                    continue
                try:
                    blob = get(thumb)
                except RuntimeError:
                    continue
                dst = out / "img" / f"{page['pageid']}.jpg"
                dst.write_bytes(blob)
                total += len(blob)
                sources[str(page["pageid"])] = {
                    "title": page["title"], "license": lic, "page": info.get("descriptionurl"),
                    "artist": info.get("extmetadata", {}).get("Artist", {}).get("value", ""),
                    "camera": f"{meta.get('Make')} {meta.get('Model')}"}
                print(f"{len(sources):4d}  {total / 1e6:6.1f} MB  {lic:14s} {page['title'][:60]}", flush=True)
                time.sleep(0.3)   # gentili con i server di Wikimedia
                if total >= budget:
                    break
            src_file.write_text(json.dumps(sources, ensure_ascii=False, indent=1))
            if "continue" not in data:
                break
            cont = data["continue"]
            time.sleep(0.5)
        if total >= budget:
            break
    print(f"fatto: {len(sources)} foto, {total / 1e6:.1f} MB in {out}")


if __name__ == "__main__":
    main()
