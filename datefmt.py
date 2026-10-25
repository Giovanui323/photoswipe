"""Nomi di giorni e mesi, e la data com'è scritta nell'interfaccia."""
import i18n
from i18n import tr

_GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
_GIORNI_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_GIORNI_LUNGHI = [tr('lunedì'), tr('martedì'), tr('mercoledì'), tr('giovedì'), tr('venerdì'), tr('sabato'), tr('domenica')]
_MESI_LUNGHI = [tr('gennaio'), tr('febbraio'), tr('marzo'), tr('aprile'), tr('maggio'), tr('giugno'), tr('luglio'), tr('agosto'),
                tr('settembre'), tr('ottobre'), tr('novembre'), tr('dicembre')]
_MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
_MESI_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_datetime(d) -> str:
    en = i18n.current_lang() == "en"
    giorni = _GIORNI_EN if en else _GIORNI
    mesi = _MESI_EN if en else _MESI
    return f"{giorni[d.weekday()]} {d.day} {mesi[d.month - 1]} {d.year}   {d:%H:%M:%S}"
