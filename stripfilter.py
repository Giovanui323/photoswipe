"""Filtro della striscia delle miniature: quali elementi mostra (e su quali vanno le frecce ← →)."""


def keeps(want: str, decision: dict | None) -> bool:
    """True se un elemento con questa scelta (None = da decidere) passa il filtro `want`."""
    if want == "all":
        return True
    if want == "todo":
        return decision is None
    if want == "done":
        return decision is not None
    return decision is not None and decision["choice"] == want
