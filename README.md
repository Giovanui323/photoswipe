<div align="center">

<img src="packaging/icon.png" alt="PhotoSwipe icon" width="128">

# PhotoSwipe

**Swipe through thousands of photos and videos and keep only the best, Tinder-style.**
A fast, offline photo culling and sorting app for macOS (Windows and Linux from source).

![Version](https://img.shields.io/badge/version-1.3.0-blue)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)
![Python](https://img.shields.io/badge/python-3-3776AB?logo=python&logoColor=white)
![Qt](https://img.shields.io/badge/UI-PySide6%20%2F%20Qt-41CD52?logo=qt&logoColor=white)
![Offline](https://img.shields.io/badge/100%25-offline-success)
![License](https://img.shields.io/badge/license-MIT-green)

</div>

---

You come back from a trip with 3,000 photos, burst shots, panoramas, Live clips and videos scattered
across SD cards, phone backups and iCloud folders. You want the 200 good ones in a single folder,
ready to print, share or upload.

**PhotoSwipe makes that a one-key-per-photo job.** Point it at a folder, then for each item press
**Y** (keep), **N** (skip it) or **S** (decide later). Kept files are **copied, never moved**, into
an `export` folder. Your originals stay exactly where they are.

## ✨ Features

- **Tinder-style culling**: Yes / No / Skip with one key, plus a full **undo** history.
- **Never destructive**: originals are copied byte-for-byte. Even "delete" only moves files to a
  `cancellare` (trash) subfolder, and **Z** brings them back.
- **Every format in one stream**: JPEG, PNG, HEIC/HEIF, **RAW DNG**, panoramas, MP4/MOV/M4V
  videos and Live clips, in all subfolders.
- **Resume any time**: progress is auto-saved after every choice. Reopen the folder later and pick
  up where you left off.
- **Built-in editor** (inspired by macOS Photos): Light, Color, Black & White, White Balance,
  Curves, Levels, Definition, Selective Color, Noise Reduction, Sharpening, Vignette, Red-Eye,
  Deblur, plus **Crop / Straighten / Perspective / Flip / Aspect ratio**, a one-click **magic wand**,
  **compare with original** and **Revert to original**. Edits are confirmed with OK / Cancel,
  are non-destructive and are exported as max-quality JPEG with EXIF kept. Video frames can be
  edited too before grabbing them as stills.
- **Self-taught AUTO**: the Light / Color / White Balance AUTO and the magic wand use a tiny model
  (`auto_model.py`, numpy only) that taught itself on ~700 **public-domain / CC0** photos from
  Wikimedia Commons: good photos are deliberately damaged and the model learns the sliders that fix
  them, so it also learns to leave good photos alone. Rebuild it with `tools/fetch_training.py`
  and `tools/train_auto.py`.
- **Grab stills from videos**: scrub frame by frame, jump to the **sharpest nearby frame**, and
  save full-resolution stills (JPEG 4:4:4 q100 or **16-bit PNG** that keeps 10-bit color).
- **Info panel**: date, GPS location (with "Open in Maps"), camera, aperture/shutter/ISO/focal
  length, resolution, video codec/fps/bitrate.
- **Favorites**: one key to also drop a photo into `export/Preferite`.
- **Smart duplicate skipping**: identical copies (same name and size) are shown only once.
- **iCloud-aware**: always works on the full-quality original and pre-downloads the next 10 items.
- **Time-zone fixer**: did your camera clock change while travelling? PhotoSwipe reads each file's
  real UTC time, or lets you force a time zone for exported dates.
- **Private by design**: no account, no cloud, no telemetry. Nothing leaves your computer.

### 📷 Camera-specific smarts

PhotoSwipe works with photos from any camera or phone. It also understands a few camera quirks.
**DJI Osmo Pocket** is fully supported:

- **Live photos** (3-second MP4s) are turned into a full-resolution still using the exact frame
  the camera chose as the cover, or any frame you pick.
- **Panoramas**: the individual source shots in `PANORAMA/` are hidden, so you only see the
  finished panorama.
- `.LRF` proxy files are used for smooth playback, and `MISC` / macOS `._` files are ignored.

## 🚀 Getting started

### Download (macOS, Apple Silicon)

1. Download the latest `PhotoSwipe-x.y.z-arm64.dmg` from
   [**Releases**](https://github.com/Giovanui323/photoswipe/releases).
2. Drag **PhotoSwipe** to *Applications*.
3. First launch: right-click → **Open** → **Open** (the app is not signed with a paid Apple
   certificate). If there's no "Open" option, go to *System Settings → Privacy & Security →
   Open Anyway*.

Requires macOS 12+ on Apple Silicon (M1 or later). Everything is bundled, ffmpeg included.

### Run from source (macOS, Windows, Linux)

```bash
git clone https://github.com/Giovanui323/photoswipe.git
cd photoswipe
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

On macOS you can also just double-click **`Avvia PhotoSwipe.command`**: it sets everything up the
first time.

### Your first session

1. Pick the **folder to review** (subfolders are included, e.g. a whole `DCIM` card).
2. Pick the **export folder**.
3. Hit **Start ▶** and start swiping.

> **Note:** the interface is currently in **Italian**. The keyboard shortcuts below work the same
> whatever the language. English localization is planned, and contributions are welcome!

## ⌨️ Keyboard shortcuts

| Key | Action |
|---|---|
| **Y** / **Enter** | **Yes**: copy to export (Live: the still only) |
| **Shift+Y** | Live only: Yes, and also copy the clip to `export/Video` |
| **N** | **No** |
| **S** | **Skip**: review skipped items at the end |
| **X** | Move the original to the `cancellare` (trash) subfolder. Undoable, never deleted |
| **Z** | **Undo** the last choice (also removes the copied files) |
| **↑** / **B** · **↓** | Previous / next item |
| **.** | Toggle favorite (`export/Preferite`) |
| **I** | Show / hide the Info panel |
| **L** | Toggle Live / still |
| **C** | Change scene (Live and video) |
| **← / →** (Shift = ×10) | Previous / next frame |
| **P** | Jump to the sharpest nearby frame |
| **R** | Back to the camera's chosen frame |
| **F** | Grab the current frame as a photo |
| **V** | Replay the video from the start, with audio |
| **Space** | Play / pause |
| **? / H** | Help |
| Scroll / double-click | Zoom / fit |

## 🗂 What happens to each file type

| Type | When you press **Yes** |
|---|---|
| Photo / panorama / RAW | Exact byte-for-byte copy (or your edited version as max-quality JPEG; the original and any DNG stay untouched) |
| Live clip | A full-resolution still is extracted from the original MP4 |
| Video | Copied to `export/Video`. Press **F** to grab as many stills as you like |

Your progress is stored in a hidden `.photoswipe-session.json` inside the reviewed folder. Starting
over renames the old session file instead of deleting it.

## 🛠 Tech stack

Python · [PySide6 (Qt 6)](https://doc.qt.io/qtforpython-6/) · [Pillow](https://python-pillow.org/) ·
[rawpy](https://github.com/letmaik/rawpy) · [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)

```bash
.venv/bin/python -m pytest -q tests   # run the test suite
packaging/build_dmg.sh                 # build the macOS .dmg
```

## 📄 License

[MIT](LICENSE). Free to use, modify and share.

## 🤝 Contributing

Issues and pull requests are welcome. Good first contributions:

- English (and other) translations of the UI
- Signed builds for Windows and Intel Macs
- Support for more camera-specific formats (GoPro, Insta360, iPhone Live Photos, more RAW formats)

If PhotoSwipe saved you an evening of sorting photos, please **⭐ star the repo**. It helps other
people find it!

---

<sub>Keywords: photo culling, photo sorter, photo organizer, photo picker, keep or delete photos,
swipe photos, Tinder for photos, select photos for printing, cull vacation photos, video frame
extractor, DJI Osmo Pocket, HEIC, DNG RAW, macOS photo app, offline, open source.</sub>
