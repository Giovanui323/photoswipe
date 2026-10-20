"""app.py può solo accorciarsi (vedi CLAUDE.md): il limite registrato scende insieme al file."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Ultimo numero di righe registrato. Si abbassa ogni volta che app.py si accorcia, mai si alza.
APP_PY_MAX_LINES = 4397


def _lines() -> int:
    with open(ROOT / "app.py", "rb") as f:
        return sum(1 for _ in f)


def test_app_py_does_not_grow():
    n = _lines()
    assert n <= APP_PY_MAX_LINES, (
        f"app.py ha {n} righe, il limite è {APP_PY_MAX_LINES}: il codice nuovo va in un modulo "
        f"a parte, e va portato fuori altro finché app.py non torna sotto il limite")


def test_app_py_limit_is_current():
    n = _lines()
    assert n >= APP_PY_MAX_LINES, (
        f"app.py è sceso a {n} righe: abbassa APP_PY_MAX_LINES in tests/test_app_size.py a {n}, "
        f"così le righe tolte non possono tornare")
