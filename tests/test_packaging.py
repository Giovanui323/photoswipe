"""Controlli sul packaging macOS: venv di build, requisiti, sintassi degli script."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD_PY = ROOT / "build" / "venv" / "bin" / "python"
SHELL_SCRIPTS = [
    ROOT / "packaging" / "build_dmg.sh",
    ROOT / "packaging" / "setup_build_venv.sh",
    ROOT / "packaging" / "adhoc_sign.sh",
    ROOT / "packaging" / "macos_minos.sh",
    ROOT / "Avvia PhotoSwipe.command",
]

needs_build_venv = pytest.mark.skipif(not BUILD_PY.exists(), reason="build/venv non presente")
needs_macos = pytest.mark.skipif(sys.platform != "darwin", reason="solo macOS")


def _version_tuple(v):
    return tuple(int(x) for x in v.split("."))


def _max_minos(paths):
    """minos più alto (LC_BUILD_VERSION) fra i binari Mach-O indicati."""
    best = (0,)
    for p in paths:
        out = subprocess.run(["otool", "-l", str(p)], capture_output=True, text=True).stdout
        for m in re.findall(r"^\s*minos (\S+)", out, re.M):
            best = max(best, _version_tuple(m))
    return best


@needs_build_venv
def test_build_venv_imports_everything_the_app_bundles():
    code = (
        "import rawpy, numpy, PIL, pi_heif, imageio_ffmpeg, PySide6, PySide6.QtMultimedia;"
        "print(numpy.__file__)"
    )
    r = subprocess.run([str(BUILD_PY), "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@needs_build_venv
@needs_macos
def test_build_venv_numpy_runs_on_macos_12():
    r = subprocess.run([str(BUILD_PY), "-c", "import numpy; print(numpy.__file__)"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    numpy_dir = Path(r.stdout.strip()).parent
    libs = list(numpy_dir.rglob("*.so")) + list(numpy_dir.rglob("*.dylib"))
    assert libs, "nessun binario di numpy trovato"
    assert _max_minos(libs) <= (12, 0), "numpy richiede macOS > 12 (wheel macosx_14_0?)"


@needs_build_venv
def test_build_venv_matches_pinned_requirements():
    pinned = {
        line.strip().lower()
        for line in (ROOT / "packaging" / "requirements-build.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    r = subprocess.run([str(BUILD_PY), "-m", "pip", "list", "--format=freeze"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    installed = {l.strip().lower() for l in r.stdout.splitlines() if l.strip() and not l.startswith("pip==")}
    assert installed == pinned


def _requirement_names(path):
    names = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.append(re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower())
    return names


def test_runtime_requirements_have_no_test_tools():
    names = _requirement_names(ROOT / "requirements.txt")
    assert "pytest" not in names
    assert "pi-heif" in names and "pillow-heif" not in names  # decode-only, niente x265 (GPL)


def test_dev_requirements_include_runtime_and_pytest():
    text = (ROOT / "requirements-dev.txt").read_text()
    assert "-r requirements.txt" in text
    assert "pytest" in _requirement_names(ROOT / "requirements-dev.txt")


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_shell_script_syntax(script):
    assert script.exists()
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_launcher_installs_only_runtime_requirements():
    text = (ROOT / "Avvia PhotoSwipe.command").read_text()
    assert "-r requirements.txt" in text
    assert "install -r requirements-dev" not in text


def test_build_script_collects_native_decoders():
    text = (ROOT / "packaging" / "build_dmg.sh").read_text()
    for flag in ("--collect-all rawpy", "--collect-all pi_heif"):
        assert flag in text
    assert "codesign --force --deep" not in text


NOTICES = ROOT / "THIRD_PARTY_NOTICES.txt"
LICENSES_DIR = ROOT / "packaging" / "licenses"
_SITE_PACKAGES = sorted((ROOT / "build" / "venv" / "lib").glob("python3*/site-packages"))
SITE_PACKAGES = _SITE_PACKAGES[0] if _SITE_PACKAGES else None
needs_site_packages = pytest.mark.skipif(SITE_PACKAGES is None, reason="build/venv non presente")


def _bundled_native_libs():
    """Librerie native incluse nell'app: .dylibs di numpy/PIL/rawpy/pi_heif e le
    dylib (FFmpeg) dentro PySide6/Qt/lib."""
    libs = []
    for pkg in ("numpy", "PIL", "rawpy", "pi_heif"):
        libs += sorted((SITE_PACKAGES / pkg / ".dylibs").glob("*.dylib"))
    libs += sorted((SITE_PACKAGES / "PySide6" / "Qt" / "lib").glob("*.dylib"))
    return libs


@needs_site_packages
def test_every_bundled_dylib_is_named_in_third_party_notices():
    text = NOTICES.read_text()
    libs = _bundled_native_libs()
    assert libs, "nessuna libreria nativa trovata in build/venv"
    missing = []
    for lib in libs:
        stem = lib.name.split(".", 1)[0]          # libjpeg.62.4.0.dylib -> libjpeg
        if not re.search(rf"(?<![\w-]){re.escape(stem)}(?![\w])", text):
            missing.append(f"{lib.parent.parent.name}/{lib.name}")
    assert not missing, f"librerie senza nota in THIRD_PARTY_NOTICES.txt: {missing}"


@needs_site_packages
def test_imageio_ffmpeg_binary_is_named_in_third_party_notices():
    exes = list((SITE_PACKAGES / "imageio_ffmpeg" / "binaries").glob("ffmpeg-*"))
    assert exes
    text = NOTICES.read_text()
    for exe in exes:
        assert exe.name in text


def test_license_files_cited_in_notices_exist():
    text = NOTICES.read_text()
    cited = set(re.findall(r"licenses/([\w.+-]+\.txt)", text))
    cited |= set(re.findall(r"\b([A-Za-z][\w+-]*(?:LICENSE|COPYING|EXCEPTION)[\w.+-]*\.txt)", text))
    assert cited
    missing = sorted(name for name in cited if not (LICENSES_DIR / name).is_file())
    assert not missing, f"testi di licenza citati ma assenti in packaging/licenses: {missing}"
