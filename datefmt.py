"""Nomi di giorni e mesi, e la data com'è scritta nell'interfaccia."""
from i18n import tr

_GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
_GIORNI_LUNGHI = [tr('lunedì'), tr('martedì'), tr('mercoledì'), tr('giovedì'), tr('venerdì'), tr('sabato'), tr('domenica')]
_MESI_LUNGHI = [tr('gennaio'), tr('febbraio'), tr('marzo'), tr('aprile'), tr('maggio'), tr('giugno'), tr('luglio'), tr('agosto'),
                tr('settembre'), tr('ottobre'), tr('novembre'), tr('dicembre')]
_MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def fmt_datetime(d) -> str:
    return f"{_GIORNI[d.weekday()]} {d.day} {_MESI[d.month - 1]} {d.year}   {d:%H:%M:%S}"
