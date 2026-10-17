"""PhotoSwipe: scegli con Sì / No / Salta le foto, i panorami e le Live da stampare."""
from __future__ import annotations

import logging
import math
import os
import subprocess
import sys
import dataclasses
import time
import uuid
import warnings
from concurrent.futures import Future, ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSettings, QSize, Qt, QTimer, QUrl,
                            Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QImage, QImageReader, QKeySequence, QPainter,
                           QLinearGradient, QPainterPath, QPalette, QPen, QPixmap, QShortcut)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                               QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QGridLayout,
                               QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QProxyStyle, QRadioButton,
                               QScrollArea, QSizePolicy, QSlider, QStackedWidget, QStyle, QStyleOption, QTextBrowser, QVBoxLayout, QWidget)

import applog
import cloud
import exporter
import frames
import metadata
from scanner import Item, mp4_duration, raw_preview, scan

# Versione: sale di 1 a ogni build, a decine: 1.1.9 -> 1.2.0 (lo fa packaging/build_dmg.sh)
APP_VERSION = "1.2.5"
APP_TITLE = f"PhotoSwipe {APP_VERSION}"

log = applog.setup(APP_TITLE)

PREFETCH = 10  # elementi successivi scaricati in anticipo da iCloud, in automatico
STRIP_FILTERS = (("Mostra: tutte", "all"), ("Mostra: da decidere", "todo"), ("Mostra: già decise", "done"),
                 ("Mostra: ✓ Sì", "yes"), ("Mostra: ✗ No", "no"), ("Mostra: ↪ saltate", "skip"),
                 ("Mostra: 🗑 “cancellare”", "trash"))
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".dng", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}
KIND_LABEL = {"photo": "FOTO", "pano": "PANORAMA", "live": "LIVE", "video": "VIDEO"}
# scelta già fatta su un elemento (tornando indietro): nome e colore dell'etichetta
CHOICE_NAME = {"yes": "✓ SÌ", "no": "✗ NO", "skip": "↪ Salta", "trash": "🗑 In “cancellare”"}
CHOICE_COLOR = {"yes": "#2ad48e", "no": "#ff4458", "skip": "#3ca4ff", "trash": "#b46cff"}  # = pulsanti
KIND_COLOR = {"photo": "#5b8def", "pano": "#a46bf0", "live": "#f0b429", "video": "#4fb7a8"}

# Stile ispirato a Foto di macOS (scuro, barre a "pillola", accento giallo) e, per la scelta,
# a Tinder: pulsanti rotondi centrati sotto la foto. Font di sistema (SF su Mac, Segoe su Windows).
STYLE = """
QMainWindow, QDialog { background: #1c1c1e; }
QWidget { color: #f2f2f7; font-size: 13px; }
QLabel, QRadioButton, QCheckBox { background: transparent; }
QToolTip { background: #2c2c2e; color: #f2f2f7; border: 1px solid #48484a; border-radius: 6px; padding: 4px 7px; font-size: 11px; }

/* pulsanti normali: pillole grigie */
QPushButton { background: #2c2c2e; border: 1px solid #545456; border-radius: 15px; padding: 6px 14px; }
QPushButton:hover { background: #3a3a3c; }
QPushButton:pressed { background: #48484a; }
QPushButton:disabled { color: #7c7c80; background: #242426; border-color: #3a3a3c; }

/* barra in alto, come la barra strumenti di Foto */
QFrame#pill { background: #2c2c2e; border: 1px solid #48484a; border-radius: 18px; }
QFrame#zoompill { background: rgba(0, 0, 0, 130); border: 1px solid rgba(255, 255, 255, 40);
                  border-radius: 14px; }
QFrame#zoompill QLabel { color: #ffffff; background: transparent; }
QFrame#pill QPushButton { background: transparent; border: none; border-radius: 14px;
                          font-size: 17px; min-width: 30px; min-height: 28px; padding: 0 6px; }
QFrame#pill QPushButton:hover { background: #3a3a3c; }
QFrame#pill QPushButton:disabled { color: #6e6e73; background: transparent; }
QPushButton#fav[on="true"] { color: #ff375f; }
QPushButton#undo { color: #f5b748; }
QLabel#chosen { border-radius: 8px; padding: 2px 9px; font-size: 11px; font-weight: 700; color: #111; }
QPushButton#info[on="true"] { background: #48484a; }
QSlider::groove:horizontal { height: 4px; background: #636366; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #d1d1d6; border-radius: 2px; }
QSlider::handle:horizontal { width: 18px; height: 18px; margin: -7px 0; background: #f2f2f7;
                             border-radius: 9px; }
QSlider::groove:horizontal:disabled { background: #48484a; }
QSlider::sub-page:horizontal:disabled { background: #636366; }
QSlider::handle:horizontal:disabled { background: #636366; }
QLabel#heading { font-size: 15px; font-weight: 700; }
QLabel#subtitle, QLabel#counter { color: #98989f; font-size: 12px; }

/* foto a tutto schermo, sullo stesso grigio della finestra */
QGraphicsView { border: none; background: #1c1c1e; }
QLabel#stamp { background: rgba(0, 0, 0, 130); color: #ffffff; font-size: 13px; font-weight: 600;
               border-radius: 12px; padding: 5px 12px; }
QLabel#chip { background: rgba(28, 28, 30, 215); color: #ffb340; font-size: 12px; font-weight: 600;
              border: 1px solid rgba(255, 179, 64, 90); border-radius: 12px; padding: 5px 12px; }
QLabel#toast { background: rgba(44, 44, 46, 235); color: #ff6961; font-size: 13px;
               border: 1px solid #48484a; border-radius: 14px; padding: 8px 16px; }

/* barra della striscia (Live e video): pillola che galleggia sotto la foto */
QFrame#scenebar { background: #2c2c2e; border: 1px solid #48484a; border-radius: 18px; }
QFrame#scenebar QLabel { color: #98989f; font-size: 12px; }
QFrame#scenebar QPushButton { background: #3a3a3c; border: none; border-radius: 13px; padding: 5px 12px; }
QFrame#scenebar QPushButton:hover { background: #48484a; }
QFrame#scenebar QPushButton#arrow { background: transparent; font-size: 16px; color: #f2f2f7;
    border: 1.5px solid #8e8e93; border-radius: 15px; min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px; padding: 0; }
QFrame#scenebar QPushButton#arrow:hover { background: #3a3a3c; border-color: #d1d1d6; }
QFrame#scenebar QPushButton#play { background: transparent; font-size: 16px; color: #f2f2f7;
    border: 1.5px solid #8e8e93; border-radius: 15px; min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px; padding: 0; }
QFrame#scenebar QPushButton#play:hover { background: #3a3a3c; border-color: #d1d1d6; }
/* pulsanti della striscia in basso: bordo e hover, come quelli dei fotogrammi */
QPushButton#stripnav { background: transparent; color: #f2f2f7; font-size: 13px;
    border: 1.5px solid #8e8e93; border-radius: 15px; padding: 3px 10px; }
QPushButton#stripnav:hover { background: #3a3a3c; border-color: #d1d1d6; }
QFrame#scenebar QPushButton#live { background: #ffd60a; color: #1c1c1e; font-weight: 700; }
QFrame#scenebar QPushButton#live:hover { background: #ffe14d; }

/* scelta, stile Tinder: cerchi scuri con anello e simbolo colorati; al passaggio si riempiono */
QPushButton[round="true"] { background: #232325; border: 2px solid #3a3a3c; padding: 0; font-weight: 700; }
QPushButton#no      { border-color: #ff4458; color: #ff4458; border-radius: 33px; font-size: 28px; }
QPushButton#yes     { border-color: #2ad48e; color: #2ad48e; border-radius: 33px; font-size: 28px; }
QPushButton#skip    { border-color: #3ca4ff; color: #3ca4ff; border-radius: 24px; font-size: 20px; }
QPushButton#trash   { border-color: #b46cff; color: #b46cff; border-radius: 24px; font-size: 18px; }
QPushButton#yesvideo{ border-color: #4fd1c5; color: #4fd1c5; border-radius: 24px; font-size: 20px; }
/* al passaggio e a scelta fatta il simbolo resta colorato pieno; il cerchio prende una tinta */
QPushButton#no:hover      { background: rgba(255, 68, 88, 50); border-width: 3px; }
QPushButton#yes:hover     { background: rgba(42, 212, 142, 50); border-width: 3px; }
QPushButton#skip:hover    { background: rgba(60, 164, 255, 50); border-width: 3px; }
QPushButton#trash:hover   { background: rgba(180, 108, 255, 50); border-width: 3px; }
QPushButton#yesvideo:hover{ background: rgba(79, 209, 197, 50); border-width: 3px; }
QPushButton[round="true"]:pressed { background: #48484a; }
/* già deciso (tornando indietro): il cerchio della scelta fatta resta tinto, anello spesso */
QPushButton#no[chosen="true"]    { background: rgba(255, 68, 88, 80); border-width: 4px; }
QPushButton#yes[chosen="true"]   { background: rgba(42, 212, 142, 80); border-width: 4px; }
QPushButton#skip[chosen="true"]  { background: rgba(60, 164, 255, 80); border-width: 4px; }
QPushButton#trash[chosen="true"] { background: rgba(180, 108, 255, 80); border-width: 4px; }
QPushButton[round="true"]:disabled { background: #1f1f21; border-color: #48484a; color: #6e6e73; }
/* con l'ID le regole sopra vincono su [round]:disabled: serve ripeterlo per ogni pulsante */
QPushButton#no:disabled, QPushButton#yes:disabled, QPushButton#skip:disabled,
QPushButton#trash:disabled, QPushButton#yesvideo:disabled { background: #1f1f21; border-color: #48484a;
                                                             color: #6e6e73; }
QLabel#cap { color: #8e8e93; font-size: 11px; }
QLabel#cap:disabled { color: #545456; }
QLabel#snaps { color: #7fe3b4; font-size: 11px; font-weight: 700; padding-bottom: 4px;
               border-bottom: 1px solid #3a3a3c; }
QLabel#snaps[empty="true"] { background: transparent; border: none; }
QFrame#next { background: #2c2c2e; border: 1px solid #3a3a3c; border-radius: 12px; }
QFrame#next QLabel { background: transparent; }
QLabel#muted { color: #98989f; }
QPushButton#small { font-size: 12px; padding: 4px 9px; border-radius: 12px; }
QLabel#details { color: #d1d1d6; font-size: 12px; }
QFrame#settings { background: #2c2c2e; border: 1px solid #48484a; border-radius: 14px; }
QFrame#settings QPushButton { background: #3a3a3c; border: none; border-radius: 8px; text-align: left; padding: 7px 12px; }
QFrame#settings QPushButton:hover { background: #48484a; }
QFrame#settings QComboBox { background: #3a3a3c; border: none; }

/* pannello laterale (cartelle e impostazioni), come il pannello Regola di Foto */
QFrame#side { background: #232325; border-left: 1px solid #2f2f31; }
QLabel#section { color: #98989f; font-size: 11px; font-weight: 700; padding-top: 10px;
                 border-bottom: 1px solid #3a3a3c; padding-bottom: 4px; }
QScrollArea#sidescroll, QScrollArea#sidescroll > QWidget > QWidget#sidebody,
QScrollArea#setupscroll, QScrollArea#setupscroll > QWidget > QWidget#setuppage { background: transparent; }
QFrame#side QPushButton { border-radius: 8px; text-align: left; padding: 7px 12px; }
QFrame#side QPushButton#small { font-size: 12px; padding: 4px 9px; border-radius: 12px; text-align: center; }
QComboBox { background: #2c2c2e; border: 1px solid #545456; border-radius: 8px; padding: 5px 10px; }
QComboBox:hover { background: #3a3a3c; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url(__CHEVRON__); width: 10px; height: 6px; }

/* focus da tastiera visibile (Tab) */
QPushButton:focus { outline: none; border: 2px solid #0a84ff; }
QPushButton#start:focus { border: 2px solid #0a84ff; }
QComboBox:focus, QCheckBox:focus, QRadioButton:focus { outline: none; }
QComboBox:focus { border: 2px solid #0a84ff; }

/* barre di scorrimento scure, sottili */
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: #545456; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QComboBox QAbstractItemView { background: #2c2c2e; border: 1px solid #48484a; color: #f2f2f7;
                              selection-background-color: #0a84ff; outline: 0; padding: 4px; }
/* ogni voce dell'elenco ha il suo bordo; al passaggio del mouse si evidenzia */
QComboBox QAbstractItemView::item { min-height: 26px; padding: 6px 12px; margin: 2px 4px;
    border: 1px solid #48484a; border-radius: 8px; color: #f2f2f7; }
QComboBox QAbstractItemView::item:hover { background: #3a3a3c; border: 1px solid #8e8e93; }
QComboBox QAbstractItemView::item:selected { background: #0a84ff; border: 1px solid #0a84ff; color: #ffffff; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #636366; border-radius: 4px; background: #2c2c2e; }
QCheckBox::indicator:checked { background: #0a84ff; border-color: #0a84ff; }

/* messaggi a tutta pagina (download, fine) */
QLabel#big { font-size: 17px; color: #d1d1d6; }

/* schermata iniziale */
QFrame#setup { background: #232325; border: 1px solid #48484a; border-radius: 18px; }
QFrame#setup QPushButton { border-radius: 10px; }
QRadioButton { spacing: 8px; padding: 2px 0; }
QRadioButton::indicator { width: 14px; height: 14px; border-radius: 8px; border: 2px solid #8e8e93;
                          background: #2c2c2e; }
QRadioButton::indicator:checked { background: #0a84ff; border-color: #0a84ff; }
QLabel#h1 { font-size: 24px; font-weight: 700; }
QLabel#step { font-size: 16px; font-weight: 600; }
QLabel#warn { color: #ffb340; }
QLabel#path { background: #1c1c1e; border: 1px solid #545456; border-radius: 8px; padding: 8px 10px;
              color: #d1d1d6; }
QLabel#path[empty="true"] { color: #8e8e93; }
QPushButton#start, QPushButton#primary { background: #ffd60a; color: #1c1c1e; border: none;
                    border-radius: 18px; font-size: 16px; font-weight: 700; padding: 9px 26px; }
QPushButton#start:hover, QPushButton#primary:hover { background: #ffe14d; }
QPushButton#start:disabled { background: #3a3a3c; color: #8e8e93; }
"""


HELP_TEXT = """PULSANTI PRINCIPALI
✓ SÌ (Y o Invio) – approva: copia in export.
   • Foto e panorami: copia identica dell'originale.
   • Live: salva come foto il fotogramma scelto sulla striscia
     (all'inizio è quello della fotocamera), a risoluzione piena.
   • Video: copia il video nella sottocartella "Video" dell'export.
     Se hai preso delle foto con 📷, SÌ tiene solo le foto;
     "＋ SÌ e copia anche il video" tiene le foto e copia anche il video.
✗ NO (N) – scarta, non copia niente.
🗑 Sposta in “cancellare” (X) – sposta l'originale nella cartella “cancellare”
   (dentro la cartella che stai guardando). Non cancella: lo fai tu a mano.
↪ Salta (S) – decidi dopo: a fine giro puoi rivedere le saltate.
＋ SÌ e copia anche il video (Maiusc+Y) – Live: salva la foto e copia anche il video.
↩ Annulla (Z) – torna all'ultima scelta (se era un Sì, toglie i file copiati).
‹ Precedente (↑) / Successivo › (↓), in alto a sinistra – rivedi anche quelle già decise o in
   “cancellare”: una nuova scelta sostituisce la vecchia (e rimette a posto i file).
♡ Preferita (.), in alto a destra – le preferite approvate vanno in export/Preferite.
In basso le miniature prima e dopo questa: clic per andarci, il pallino è la scelta fatta.
A destra il pannello Info: giorno, luogo, fotocamera, scatto e file (ⓘ o I lo nasconde).

LIVE
La Live si apre come FOTO. Sotto c'è la striscia dei fotogrammi (come in Foto):
clic o trascina per scegliere la foto, ← → un fotogramma alla volta.
Il riquadro bianco è la foto che SÌ salverà.
▶ Vedi Live (L) – guarda il video.   ↺ Foto della fotocamera (R) – torna a quella originale.
✨ Più nitida (P) – cerca il fotogramma meno mosso lì vicino.

VIDEO
Clic sulla striscia (o pausa, ← →) – ti fermi sul fotogramma esatto.
📷 Prendi foto (F) – lo salva come foto: diventa un segno verde sulla striscia
   e l'etichetta dice “✓ già salvato”. Puoi prenderne quante vuoi (Z annulla l'ultima).
⟲ Rivedi video (V) – dall'inizio, con l'audio.   ▶ / ⏸ (Spazio) – riproduci / pausa.

ZOOM
Cursore sopra la foto, in alto a sinistra; due dita su/giù sul trackpad (o pizzico) = zoom, trascina per spostarti,
doppio clic = di nuovo intera. Ogni foto si apre sempre intera.

IMPOSTAZIONI (⚙ in alto a destra)
Apri cartella – ① la cartella da guardare, ② la cartella export, poi Inizia.
Mostra: tutto / solo foto – nasconde i video (restano foto, Live e panorami).
Export – cambia la cartella dove copiare.   Mostra export – la apre nel Finder.
JPEG / PNG 16-bit – formato dei fotogrammi estratti (JPEG va bene per la stampa).
Ora – fuso orario da scrivere nella data delle foto esportate.

Le scelte vengono salvate subito in un file nascosto dentro la cartella
che apri (.photoswipe-session.json). Se riapri quella cartella, l'app ti dice
se il lavoro è a metà o completato, quando l'avevi chiuso, e ti chiede se riprendere.
I file su iCloud si scaricano da soli, e i 10 successivi in anticipo."""


def help_html(text: str) -> str:
    """Aiuto in HTML: titoletti (righe in MAIUSCOLO) piccoli, grigi e staccati dal testo."""
    from html import escape
    out = []
    for line in text.split("\n"):
        if line and line.isupper() and len(line) < 40:
            out.append("<p style='color:#98989f; font-size:11px; font-weight:700; letter-spacing:1px;"
                       f" margin:16px 0 4px 0'>{escape(line)}</p>")
        elif not line.strip():
            out.append("<p style='margin:6px 0'></p>")
        else:
            lead = len(line) - len(line.lstrip(" "))
            out.append(f"<p style='margin:2px 0 2px {lead * 6}px'>{escape(line.lstrip(' '))}</p>")
    return "".join(out)


FILE_MANAGER = "Finder" if sys.platform == "darwin" else "Esplora file"


class TipStyle(QProxyStyle):
    """Suggerimenti meno frequenti: compaiono dopo un attimo più lungo e, passando da un pulsante
    all'altro, non si riaprono subito (Qt li farebbe comparire senza attesa entro 2 secondi)."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ToolTip_WakeUpDelay:
            return 1000  # ms prima della comparsa (default Qt: 700)
        if hint == QStyle.SH_ToolTip_FallAsleepDelay:
            return 0     # nessuna riapertura immediata passando da un pulsante a un altro
        return super().styleHint(hint, option, widget, returnData)


class ElidedLabel(QLabel):
    """Etichetta su una riga che non allarga mai la finestra: se il testo non ci sta lo accorcia
    con "…" e lo mostra intero nel suggerimento."""

    def __init__(self, text: str = "", mode=Qt.ElideRight):
        super().__init__(text)
        self._mode = mode
        self._tip = ""
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)  # minimo 0: mai più larga

    def setToolTip(self, tip: str) -> None:
        self._tip = tip
        super().setToolTip(tip)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 8, super().sizeHint().height())

    def paintEvent(self, e):
        r = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), self._mode, r.width())
        tip = self.text() if text != self.text() else self._tip
        if self.toolTip() != tip:
            QLabel.setToolTip(self, tip)
        p = QPainter(self)
        opt = QStyleOption()   # sfondo e bordo del foglio di stile (es. il riquadro del percorso)
        opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        self.style().drawItemText(p, r, int(self.alignment()) | Qt.AlignVCenter, self.palette(),
                                  self.isEnabled(), text, self.foregroundRole())


def trash_pixmap(color: str, size: int = 22, dpr: float = 2.0) -> QPixmap:
    """Cestino disegnato a linee, di un solo colore come gli altri simboli (l'emoji 🗑 è grigia)."""
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), size / 11)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    u = size / 22
    p.drawLine(QPointF(4 * u, 6 * u), QPointF(18 * u, 6 * u))          # coperchio
    p.drawLine(QPointF(9 * u, 3.5 * u), QPointF(13 * u, 3.5 * u))       # maniglia
    p.drawLine(QPointF(9 * u, 3.5 * u), QPointF(9 * u, 6 * u))
    p.drawLine(QPointF(13 * u, 3.5 * u), QPointF(13 * u, 6 * u))
    body = QPainterPath(QPointF(6 * u, 6 * u))
    body.lineTo(7 * u, 18.5 * u)
    body.lineTo(15 * u, 18.5 * u)
    body.lineTo(16 * u, 6 * u)
    p.drawPath(body)
    p.drawLine(QPointF(9.5 * u, 9 * u), QPointF(9.8 * u, 15.5 * u))
    p.drawLine(QPointF(12.5 * u, 9 * u), QPointF(12.2 * u, 15.5 * u))
    p.end()
    return pm


def chevron_file() -> str:
    """Freccia ⌄ dei menu a tendina, disegnata e salvata in un PNG temporaneo (il foglio di stile
    vuole un file); senza, i menu sembrano normali pulsanti."""
    import tempfile
    path = Path(tempfile.gettempdir()) / "photoswipe-chevron.png"
    pm = QPixmap(20, 12)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#98989f"), 2.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(3, 3), QPointF(10, 9), QPointF(17, 3)])
    p.end()
    pm.save(str(path), "PNG")
    return path.as_posix()


class TrashButton(QPushButton):
    """Pulsante rotondo con il cestino disegnato: viola (anche col cerchio tinto, al passaggio del
    mouse o a scelta già fatta), spento se disattivato. Stessi colori del foglio di stile."""
    COLORS = {"normal": "#b46cff", "filled": "#b46cff", "off": "#6e6e73"}

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setIconSize(QSize(22, 22))
        self.refresh_icon()

    def refresh_icon(self) -> None:
        state = ("off" if not self.isEnabled()
                 else "filled" if self.underMouse() or self.property("chosen") == "true" else "normal")
        if getattr(self, "_state", None) != state:
            self._state = state
            self.setIcon(trash_pixmap(self.COLORS[state], 22, max(2.0, self.devicePixelRatioF())))

    def enterEvent(self, e):
        super().enterEvent(e)
        self.refresh_icon()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.refresh_icon()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.EnabledChange:
            self.refresh_icon()


class OverlayLabel(QLabel):
    """Etichetta sopra la foto (avvisi in alto a destra, messaggi in basso al centro, come le
    notifiche di Foto). Vuota = nascosta; si riposiziona da sola a ogni testo nuovo.
    Con hide_after_ms il messaggio sparisce da solo (così non resta sopra la foto)."""

    def __init__(self, parent: QWidget, anchor: str, hide_after_ms: int = 0):
        super().__init__("", parent)
        self.anchor = anchor
        self.hide_after_ms = hide_after_ms
        self.avoid: list[QWidget] = []   # altre etichette sopra la foto da non coprire (la data)
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.setText(""))
        self.hide()

    def setText(self, text: str, ms: int | None = None) -> None:
        super().setText(text)
        self.place()
        ms = self.hide_after_ms if ms is None else ms
        if text and ms:
            self.timer.start(ms)
        else:
            self.timer.stop()

    def place(self) -> None:
        par = self.parentWidget()
        if not self.text():
            self.hide()
            return
        self.ensurePolished()
        maxw = max(160, par.width() - 80)
        self.setWordWrap(False)
        hint = self.sizeHint()
        w = min(hint.width(), maxw)
        self.setWordWrap(w < hint.width())
        h = max(hint.height(), self.heightForWidth(w)) if self.wordWrap() else hint.height()
        self.resize(w, h)
        if self.anchor == "top-right":
            x, y = par.width() - w - 14, 12
            for o in self.avoid:   # se si sovrappone alla data, va sotto
                if o.isVisible() and o.geometry().intersects(QRect(x, y, w, h)):
                    y = max(y, o.geometry().bottom() + 8)
            self.move(x, y)
        else:
            self.move((par.width() - w) // 2, par.height() - h - 16)
        self.show()
        self.raise_()


class Bridge(QObject):
    """Riporta nel thread dell'interfaccia i risultati dei lavori in background."""
    done = Signal(str, object, object)  # tipo, chiave, risultato (o eccezione)


class ImageView(QGraphicsView):
    zoom_changed = Signal(float)   # 0 = adattata, 1 = ingrandimento massimo (per il cursore in alto)
    view_changed = Signal()        # la foto ha cambiato posto/dimensione a schermo (per la data sopra)

    """Foto adattata alla finestra; due dita su/giù o pizzico = zoom, doppio clic = adatta.

    Adattata: l'immagine viene ridotta UNA volta, con filtro di alta qualità, ai pixel reali dello
    schermo (Retina compreso), invece di lasciarla ridurre al volo (più morbido/scalettato).
    Con lo zoom si passa all'originale a piena risoluzione."""

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.loading = self.scene().addSimpleText("")
        self.loading.setBrush(QColor("#9a9ca0"))
        f = self.loading.font()
        f.setPointSize(16)
        self.loading.setFont(f)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)
        self.full = QImage()
        self.zoomed = False

    def set_loading(self, text: str) -> None:
        self.full = QImage()
        self.zoomed = False  # la prossima immagine arriva adattata, non ingrandita
        self.item.setPixmap(QPixmap())
        self.loading.setText(text)
        self.resetTransform()
        self.scene().setSceneRect(self.loading.boundingRect())
        self.centerOn(self.loading)

    def set_image(self, img: QImage, keep_zoom: bool = False) -> None:
        self.loading.setText("")
        self.full = img
        if keep_zoom and self.zoomed:
            self._show_full(keep_view=True)
        else:
            self.fit()

    def _show_full(self, keep_view: bool = False) -> None:
        if self.full.isNull():
            return
        if not keep_view:  # stessa dimensione a schermo di prima, ma con tutti i pixel
            shown_w = self.item.boundingRect().width() * self.transform().m11()
            self.item.setPixmap(QPixmap.fromImage(self.full))
            self.resetTransform()
            k = shown_w / self.full.width() if self.full.width() else 1
            self.scale(k, k)
        else:
            self.item.setPixmap(QPixmap.fromImage(self.full))
        self.scene().setSceneRect(self.item.boundingRect())

    def _fit_k(self) -> float:
        """Scala (punti per pixel dell'immagine) che riempie la finestra: ingrandisce anche le
        foto piccole, come Foto. Nessun limite a 1 pixel fisico per pixel."""
        return min(self.viewport().width() / self.full.width(),
                   self.viewport().height() / self.full.height())

    def _limits(self) -> tuple[float, float]:
        """Zoom minimo (adattata) e massimo: 4 pixel dello schermo per pixel della foto."""
        dpr = self.devicePixelRatioF()
        fit_k = self._fit_k()
        return fit_k, max(fit_k * 2, 4 / dpr)

    def zoom_level(self) -> float:
        if self.full.isNull() or not self.zoomed:
            return 0.0
        lo, hi = self._limits()
        k = self.transform().m11() * self.item.pixmap().width() / max(1, self.full.width())
        return 0.0 if hi <= lo else max(0.0, min(1.0, math.log(k / lo) / math.log(hi / lo)))

    def set_zoom_level(self, t: float) -> None:
        """Cursore dello zoom: 0 = foto intera, 1 = 4 pixel dello schermo per pixel. Centro fisso."""
        if self.full.isNull():
            return
        if t <= 0:
            self.fit()
            return
        lo, hi = self._limits()
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        if not self.zoomed:
            self.zoomed = True
            self._show_full()
        k = lo * (hi / lo) ** t
        self.scale(k / self.transform().m11(), k / self.transform().m11())
        self.setTransformationAnchor(anchor)
        self.view_changed.emit()

    def fit(self) -> None:
        self.zoomed = False
        self.zoom_changed.emit(0.0)
        self.resetTransform()
        if self.full.isNull():
            return
        dpr = self.devicePixelRatioF()
        k = self._fit_k()
        target_w = max(1, round(self.full.width() * k * dpr))
        target_h = max(1, round(self.full.height() * k * dpr))
        pm = QPixmap.fromImage(self.full.scaled(target_w, target_h, Qt.KeepAspectRatio,
                                                Qt.SmoothTransformation))
        pm.setDevicePixelRatio(dpr)
        self.item.setPixmap(pm)
        # il pixmap è già alla dimensione della finestra: niente fitInView, che aggiunge un margine
        # e lascia la foto qualche pixel più piccola della misura calcolata
        self.scene().setSceneRect(self.item.boundingRect())
        self.view_changed.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.zoomed:
            self.fit()

    MAX_STEP = 1.08   # ogni evento (scatto di rotella, pezzo di pizzico) cambia al massimo l'8%

    def wheelEvent(self, e):
        self.zoom_by(1.0015 ** e.angleDelta().y())

    def event(self, e):
        if e.type() == QEvent.NativeGesture and e.gestureType() == Qt.ZoomNativeGesture:
            self.zoom_by(1.0 + e.value() * 0.5)  # pizzico sul trackpad, più dolce
            return True
        return super().event(e)

    def zoom_by(self, factor: float) -> None:
        if self.full.isNull():
            return
        factor = max(1 / self.MAX_STEP, min(self.MAX_STEP, factor))
        if not self.zoomed:
            if factor <= 1:
                return  # già adattata: non si rimpicciolisce oltre
            self.zoomed = True
            self._show_full()
        fit_k = self._fit_k()
        k = min(self.transform().m11() * factor, self._limits()[1])
        if k <= fit_k:
            self.fit()  # tornati alla dimensione intera: di nuovo adattata
            return
        self.scale(k / self.transform().m11(), k / self.transform().m11())
        self.zoom_changed.emit(self.zoom_level())
        self.view_changed.emit()

    def mouseDoubleClickEvent(self, e):
        self.fit()


class FilmStrip(QWidget):
    """Striscia di fotogrammi come in Foto di macOS: clic o trascina per scegliere il momento.

    Il riquadro bianco è il fotogramma scelto/mostrato, la linea sottile segue il video mentre va,
    i segni verdi sono le foto già salvate con 📷."""
    picked = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(72)   # in alto c'è posto per il pallino della foto originale
        self.setMinimumWidth(200)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.owner: str | None = None
        self.frames = 0
        self.thumbs: list[QImage] = []
        self.selected: int | None = None
        self.playhead: int | None = None
        self.marks: list[int] = []
        self.original: int | None = None   # Live: foto scelta dalla fotocamera (pallino)
        self._drag = False
        self._last: int | None = None

    def set_video(self, frames_: int, owner: str | None = None) -> None:
        self.owner, self.frames, self.thumbs = owner, frames_, []
        self.selected = self.playhead = self.original = None
        self.marks = []
        self.update()

    def set_thumbs(self, thumbs: list[QImage]) -> None:
        self.thumbs = thumbs
        self.update()

    def set_state(self, selected: int | None, marks: list[int], original: int | None = None) -> None:
        self.selected, self.marks, self.original = selected, marks, original
        if selected is not None:
            self.playhead = None   # fermi su una foto: niente linea di riproduzione
        self.update()

    def set_playhead(self, n: int | None) -> None:
        self.playhead = n
        self.update()

    def _strip(self) -> QRectF:
        return QRectF(14, 10, max(1, self.width() - 28), self.height() - 16)

    def frame_at_x(self, x: float) -> int:
        r = self._strip()
        t = min(1.0, max(0.0, (x - r.left()) / r.width()))
        return round(t * (self.frames - 1))

    def x_of(self, n: int) -> float:
        r = self._strip()
        return r.left() + (n / max(1, self.frames - 1)) * r.width()

    def _emit(self, x: float) -> None:
        if self.frames <= 0:
            return
        n = self.frame_at_x(x)
        if n != self._last:
            self._last = n
            self.picked.emit(n)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag, self._last = True, None
            self._emit(e.position().x())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._emit(e.position().x())

    def mouseReleaseEvent(self, e):
        self._drag = False

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self._strip()
        clip = QPainterPath()
        clip.addRoundedRect(r, 6, 6)
        p.fillPath(clip, QColor("#26292d"))
        if self.thumbs:
            p.save()
            p.setClipPath(clip)
            w = r.width() / len(self.thumbs)
            for i, im in enumerate(self.thumbs):  # ogni miniatura riempie la sua casella (ritaglio centrale)
                cell = QRectF(r.left() + i * w, r.top(), w + 0.5, r.height())
                k = max(cell.width() / im.width(), cell.height() / im.height())
                sw, sh = cell.width() / k, cell.height() / k
                p.drawImage(cell, im, QRectF((im.width() - sw) / 2, (im.height() - sh) / 2, sw, sh))
            p.restore()
        if self.frames <= 0:
            return
        for n in self.marks:  # foto già salvate
            x = self.x_of(n)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#3fd17a"))
            p.drawRoundedRect(QRectF(x - 2, r.bottom() - 9, 4, 12), 2, 2)
        if self.original is not None:  # pallino sopra la striscia, come la "foto chiave" di Foto
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffffff") if self.original == self.selected else QColor("#ffd60a"))
            p.drawEllipse(QPointF(self.x_of(self.original), 2.75), 2.25, 2.25)
        if self.playhead is not None and self.selected is None:
            x = self.x_of(self.playhead)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(int(x), int(r.top()) - 3, int(x), int(r.bottom()) + 3)
        if self.selected is not None:
            x = self.x_of(self.selected)
            bw = r.height() * 0.75
            box = QRectF(x - bw / 2, r.top() - 4, bw, r.height() + 8)
            p.setPen(QPen(QColor("#ffffff"), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box, 5, 5)


class SnapGallery(QWidget):
    """Le foto prese dal video che stai guardando, in miniatura (pannello a destra, in basso).
    Clic = il video torna su quel fotogramma per rivederlo; doppio clic = apre il file salvato;
    ✕ sulla miniatura = la toglie da export."""
    picked = Signal(int)        # fotogramma
    opened = Signal(str)        # file in export
    removed = Signal(str)       # chiave della foto (id#fN)
    COLS, GAP, CAP = 2, 8, 16

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.entries: list[tuple[str, int, str | None]] = []   # (chiave, fotogramma, file)
        self.current: int | None = None
        self._hover: int | None = None
        self._cache: dict[str, QImage] = {}
        self.setFixedHeight(0)

    def set_entries(self, entries: list[tuple[str, int, str | None]], current: int | None) -> None:
        self.entries, self.current = sorted(entries, key=lambda e: e[1]), current
        rows = math.ceil(len(self.entries) / self.COLS)
        self.setFixedHeight(rows * (self._cell_h() + self.CAP + self.GAP) if rows else 0)
        self.update()

    def _cell_w(self) -> float:
        return (self.width() - self.GAP * (self.COLS - 1)) / self.COLS

    def _cell_h(self) -> int:
        return round((max(200, self.width()) - self.GAP * (self.COLS - 1)) / self.COLS * 9 / 16)

    def _rect(self, i: int) -> QRectF:
        r, c = divmod(i, self.COLS)
        return QRectF(c * (self._cell_w() + self.GAP), r * (self._cell_h() + self.CAP + self.GAP),
                      self._cell_w(), self._cell_h())

    def _close_rect(self, i: int) -> QRectF:
        r = self._rect(i)
        return QRectF(r.right() - 24, r.top() + 4, 20, 20)

    def _at(self, pos) -> int | None:
        for i in range(len(self.entries)):
            if self._rect(i).adjusted(0, 0, 0, self.CAP).contains(pos):
                return i
        return None

    def _thumb(self, path: str | None) -> QImage | None:
        if not path:
            return None
        if path not in self._cache:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():   # JPEG: si decodifica già ridotto, è veloce anche col 4K
                reader.setScaledSize(size.scaled(QSize(480, 270), Qt.KeepAspectRatioByExpanding))
            im = reader.read()
            if im.isNull():
                return None      # export non ancora finito: si riprova al prossimo aggiornamento
            self._cache[path] = im
        return self._cache[path]

    def mouseMoveEvent(self, e):
        i = self._at(e.position())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        i = self._at(e.position())
        if i is None or e.button() != Qt.LeftButton:
            return
        key, frame, _ = self.entries[i]
        if self._close_rect(i).contains(e.position()):
            self.removed.emit(key)
        else:
            self.picked.emit(frame)

    def mouseDoubleClickEvent(self, e):
        i = self._at(e.position())
        if i is not None and self.entries[i][2] and not self._close_rect(i).contains(e.position()):
            self.opened.emit(self.entries[i][2])

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        for i, (key, frame, path) in enumerate(self.entries):
            r = self._rect(i)
            clip = QPainterPath()
            clip.addRoundedRect(r, 6, 6)
            p.fillPath(clip, QColor("#2c2c2e"))
            im = self._thumb(path)
            if im is not None:
                k = max(r.width() / im.width(), r.height() / im.height())
                sw, sh = r.width() / k, r.height() / k
                p.save()
                p.setClipPath(clip)
                p.drawImage(r, im, QRectF((im.width() - sw) / 2, (im.height() - sh) / 2, sw, sh))
                p.restore()
            else:
                p.setPen(QColor("#8e8e93"))
                p.drawText(r, Qt.AlignCenter, "salvo…")
            if frame == self.current:  # è il fotogramma che stai guardando
                p.setPen(QPen(QColor("#ffffff"), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
            if i == self._hover:
                c = self._close_rect(i)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 170))
                p.drawEllipse(c)
                p.setPen(QPen(QColor("#ffffff"), 1.6))
                p.drawLine(c.center() + QPointF(-4, -4), c.center() + QPointF(4, 4))
                p.drawLine(c.center() + QPointF(-4, 4), c.center() + QPointF(4, -4))
            p.setPen(QColor("#98989f"))
            f = p.font()
            f.setPixelSize(11)
            p.setFont(f)
            p.drawText(QRectF(r.left(), r.bottom() + 2, r.width(), self.CAP - 2),
                       Qt.AlignLeft | Qt.AlignVCenter, f"fotogramma {frame + 1}")


class ThumbStrip(QWidget):
    """Miniature degli elementi prima e dopo quello che guardi, come la striscia in fondo a Foto.
    Quella attuale è al centro, più grande e con il bordo; un pallino colorato dice la scelta già
    fatta. Clic = vai a quell'elemento."""
    picked = Signal(int)
    CELL_W, CELL_H, GAP = 74, 52, 6
    DOT = {"yes": "#2ad48e", "no": "#ff4458", "skip": "#3ca4ff", "trash": "#b46cff", "snap": "#2ad48e"}

    def __init__(self):
        super().__init__()
        self.setFixedHeight(self.CELL_H + 18)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.entries: list[tuple[int, QImage | None, str | None, bool, str]] = []
        self.current: int | None = None
        self._rects: list[tuple[QRectF, int]] = []
        self.pan = 0.0            # spostamento attuale (pixel): la striscia si muove da qui
        self._target = 0.0        # dove deve arrivare: lo scorrimento è morbido, come in Foto
        self._vel = 0.0           # velocità del trascinamento, poi l'inerzia la fa decrescere
        self._press = None        # (x iniziale, pan iniziale, x precedente) mentre si trascina
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_entries(self, entries, current: int | None) -> None:
        """entries: (indice, miniatura o None, scelta o None, è un video/Live, nome file)."""
        if current != self.current:
            self.pan = self._target = 0.0   # cambia la foto guardata: la striscia torna centrata
            self._vel = 0.0
        self.entries, self.current = entries, current
        self.update()

    def _limit(self) -> float:
        """Quanto si può spostare: fino all'ultima miniatura da una parte e dall'altra."""
        return max(0.0, (len(self.entries) * (self.CELL_W + self.GAP) - self.width()) / 2 + self.CELL_W)

    def _clamp(self, v: float) -> float:
        lim = self._limit()
        return max(-lim, min(lim, v))

    def _start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        """Un passo di animazione: inerzia dopo il trascinamento, e avvicinamento al punto di arrivo."""
        if self._press is None:
            if abs(self._vel) > 0.2:
                self._target = self._clamp(self._target + self._vel)
                self._vel *= 0.92                  # l'inerzia si spegne piano, come sul trackpad
            else:
                self._vel = 0.0
        self.pan += (self._target - self.pan) * 0.22   # arriva al punto con un movimento morbido
        self.update()
        if self._press is None and abs(self._target - self.pan) < 0.3 and self._vel == 0.0:
            self.pan = self._target
            self._timer.stop()
            self.update()

    def nudge(self, px: float) -> None:
        """Sposta la striscia di px pixel (positivo = verso destra), con movimento morbido."""
        self._target = self._clamp(self._target + px)
        self._vel = 0.0
        self._start()

    def recenter(self) -> None:
        """Riporta la striscia centrata sulla foto che stai guardando."""
        self._target = 0.0
        self._vel = 0.0
        self._start()

    def wheelEvent(self, e):
        pd = e.pixelDelta()
        if not pd.isNull():                        # trackpad: segue le dita, l'inerzia la dà il sistema
            d = pd.x() or pd.y()
            self._target = self.pan = self._clamp(self.pan + d)
            self._vel = 0.0
            self.update()
        else:                                      # rotella: uno scatto = una finestra di miniature
            steps = (e.angleDelta().x() or e.angleDelta().y()) / 120
            self.nudge(-steps * 2.5 * (self.CELL_W + self.GAP))
        self._start()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            x = e.position().x()
            self._press = (x, self.pan, x)
            self._vel = 0.0

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        x0, pan0, last = self._press
        x = e.position().x()
        if abs(x - x0) > 3:                        # trascinamento: la striscia segue il dito
            self.pan = self._target = self._clamp(pan0 + (x - x0))
            self._vel = x - last                   # serve per l'inerzia al rilascio
            self._press = (x0, pan0, x)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._press is None:
            return
        x0, _, _ = self._press
        self._press = None
        if abs(e.position().x() - x0) <= 3:        # un clic, non un trascinamento
            self._vel = 0.0
            for r, i in self._rects:
                if r.contains(e.position()):
                    self.picked.emit(i)
                    break
        self._vel = max(-60.0, min(60.0, self._vel * 1.5))
        self._start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self._rects = []
        if not self.entries:
            return
        cw, ch, gap = self.CELL_W, self.CELL_H, self.GAP
        big = 1.18
        cx = self.width() / 2 + self.pan
        cy = self.height() / 2
        pos = [k for k, en in enumerate(self.entries) if en[0] == self.current]
        center_k = pos[0] if pos else len(self.entries) - 0.5
        for k, (i, img, choice, clip, name) in enumerate(self.entries):
            scale = big if i == self.current else 1.0
            w, h = cw * scale, ch * scale
            off = (k - center_k) * (cw + gap)
            if pos and k != center_k:  # spazio in più attorno a quella grande
                off += (cw * (big - 1) / 2 + 2) * (1 if k > center_k else -1)
            r = QRectF(cx + off - w / 2, cy - h / 2, w, h)
            if r.right() < 0 or r.left() > self.width():
                continue
            self._rects.append((r, i))
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            p.fillPath(path, QColor("#2c2c2e"))
            if img is not None and not img.isNull():
                p.save()
                p.setClipPath(path)
                k_ = max(r.width() / img.width(), r.height() / img.height())
                sw, sh = r.width() / k_, r.height() / k_
                p.drawImage(r, img, QRectF((img.width() - sw) / 2, (img.height() - sh) / 2, sw, sh))
                p.restore()
            else:
                p.setPen(QColor("#8e8e93"))
                f = p.font()
                f.setPixelSize(10)
                p.setFont(f)
                p.drawText(r.adjusted(4, 4, -4, -4), Qt.AlignCenter | Qt.TextWrapAnywhere, name)
            if i != self.current:
                p.fillPath(path, QColor(0, 0, 0, 70 if choice is None else 120))  # già decise: più scure
            if clip:   # ▶ su un dischetto scuro: leggibile anche su miniature chiare
                disc = QRectF(r.left() + 4, r.bottom() - 18, 14, 14)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 140))
                p.drawEllipse(disc)
                p.setPen(QColor("#ffffff"))
                f = p.font()
                f.setPixelSize(8)
                p.setFont(f)
                p.drawText(disc.adjusted(1, 0, 1, 0), Qt.AlignCenter, "▶")
            if choice in self.DOT:
                p.setPen(QPen(QColor("#1c1c1e"), 1.5))
                p.setBrush(QColor(self.DOT[choice]))
                p.drawEllipse(QRectF(r.right() - 13, r.top() + 4, 9, 9))
            if i == self.current:
                p.setPen(QPen(QColor("#ffffff"), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 7, 7)
        # ai bordi le miniature sfumano nello sfondo invece di finire tagliate di netto
        fade = 40
        for x0, x1 in ((0, fade), (self.width(), self.width() - fade)):
            g = QLinearGradient(x0, 0, x1, 0)
            g.setColorAt(0, QColor(28, 28, 30, 255))
            g.setColorAt(1, QColor(28, 28, 30, 0))
            p.fillRect(QRectF(min(x0, x1), 0, fade, self.height()), g)


_GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
_GIORNI_LUNGHI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MESI_LUNGHI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
                "settembre", "ottobre", "novembre", "dicembre"]
_MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def fmt_datetime(d) -> str:
    return f"{_GIORNI[d.weekday()]} {d.day} {_MESI[d.month - 1]} {d.year}   {d:%H:%M:%S}"


def pil_to_qimage(img) -> QImage:
    img = img.convert("RGB")
    data = img.tobytes()
    return QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888).copy()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.unified = sys.platform == "darwin" and hasattr(Qt, "NoTitleBarBackgroundHint")
        if self.unified:
            # come Foto: niente barra del titolo bianca, i semafori stanno dentro la barra degli
            # strumenti scura (il nome e la versione sono nel pannello Info)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                self.setWindowFlag(Qt.ExpandedClientAreaHint, True)
                self.setWindowFlag(Qt.NoTitleBarBackgroundHint, True)
            self.setAttribute(Qt.WA_ContentsMarginsRespectsSafeArea, False)
            self.setWindowTitle("")
        self.resize(1440, 900)  # ridotta da main() se lo schermo è più piccolo
        # panorami enormi (20000×4000 = 320 MB in memoria): il limite di Qt (256 MB) li rifiutava
        QImageReader.setAllocationLimit(2048)
        # PHOTOSWIPE_PROFILE separa le impostazioni dei test da quelle dell'utente
        self.settings_store = QSettings("PhotoSwipe", os.environ.get("PHOTOSWIPE_PROFILE", "PhotoSwipe"))

        self.bg = ThreadPoolExecutor(max_workers=4)
        self.dl = ThreadPoolExecutor(max_workers=6)        # download dell'elemento corrente
        self.pre = ThreadPoolExecutor(max_workers=2)       # anticipo dei successivi (2 alla volta)
        self.waiters = ThreadPoolExecutor(max_workers=4)   # attese dei download correnti
        self.export_q = ThreadPoolExecutor(max_workers=1)  # export in ordine, uno alla volta
        self.bridge = Bridge()
        self.bridge.done.connect(self.on_done)

        self.root: Path | None = None
        self.export_dir: Path | None = None
        self.session: exporter.Session | None = None
        self.items: list[Item] = []
        self.idx = 0
        self.review_skipped = False
        self.history: list[tuple[int, str, dict | None]] = []
        self.export_futures: dict[str, Future] = {}
        # dove sono ORA le copie spostate (Preferite) secondo la coda export: la sessione lo sa solo
        # dopo, e un Annulla o un altro ♥ in coda subito dietro userebbero i percorsi vecchi.
        # Letto e scritto SOLO dai lavori di export_q (un solo thread, in ordine).
        self.copy_paths: dict[str, list[str]] = {}
        self.still_owner: str | None = None   # elemento la cui foto è ora a schermo
        self.pending: set[tuple[str, str]] = set()
        self.ready: set[str] = set()
        self.infos: dict[str, frames.VideoInfo] = {}
        self.camera_frames: dict[str, int] = {}
        # stato della scena per l'elemento corrente
        self.scene_mode = False
        self.live_view = False   # Live: False = si vede la foto, True = si vede il video
        self._last_decision = 0.0
        self._yes_without_preview: str | None = None
        self.frame: int | None = None   # fotogramma scelto a mano
        self.shown_frame = 0
        self._player_item: str | None = None   # elemento caricato nel lettore video
        self._playing_proxy = False
        self.exact_cache: dict[tuple[str, int], QImage] = {}  # ultimi fotogrammi esatti (4K)
        self._preview_busy = False
        self._preview_again = False
        self.meta: dict[str, metadata.Meta] = {}    # metadati per il pannello Info
        self.thumbs: dict[str, list[QImage]] = {}   # miniature della striscia, per elemento
        self.next_thumbs: dict[str, QImage] = {}    # anteprima dell'elemento successivo
        self._by_id: dict[str, Item] = {}
        self._trash_view: tuple[str, int, Item] | None = None
        self.photos_only = self.settings_store.value("filter", "all") == "photos"

        self._build_ui()
        self._build_shortcuts()
        self.show_setup()

    # ------------------------------------------------------------------ interfaccia
    def _build_ui(self):
        """Layout ispirato a Foto di macOS: barra in alto (navigazione · titolo e data · preferita,
        aiuto, impostazioni), la foto grande al centro, la striscia della Live/video in una pillola
        sotto, e la scelta stile Tinder (pulsanti rotondi centrati). Le impostazioni stanno in un
        pannello laterale che si apre con ⋯ (o I)."""
        central = QWidget()
        self.setCentralWidget(central)
        if self.unified:
            central.setAttribute(Qt.WA_ContentsMarginsRespectsSafeArea, False)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        main = QWidget()
        lay = QVBoxLayout(main)
        lay.setContentsMargins(14, 6 if self.unified else 10, 14, 12)
        lay.setSpacing(8)
        outer.addWidget(main, 1)

        def pill(*buttons):
            f = QFrame()
            f.setObjectName("pill")
            h = QHBoxLayout(f)
            h.setContentsMargins(4, 3, 4, 3)
            h.setSpacing(2)
            for b in buttons:
                b.setFocusPolicy(Qt.NoFocus)
                h.addWidget(b)
            return f

        # ---- barra in alto
        self.btn_back = QPushButton("‹")
        self.btn_back.setToolTip("Precedente (↑ o B): torna all'elemento prima, anche se già deciso\n"
                                 "(approvato, scartato, in “cancellare”). La nuova scelta sostituisce la vecchia.")
        self.btn_back.clicked.connect(self.go_back)
        self.btn_fwd = QPushButton("›")
        self.btn_fwd.setToolTip("Successivo (↓): vai all'elemento dopo senza decidere.")
        self.btn_fwd.clicked.connect(self.go_forward)
        self.btn_undo = QPushButton("↩")
        self.btn_undo.setObjectName("undo")
        self.btn_undo.setToolTip("Annulla l'ultima scelta e torna indietro (Z).\n"
                                 "Se era un Sì, toglie anche i file copiati in export.")
        self.btn_undo.clicked.connect(self.undo)
        self.nav_pill = pill(self.btn_back, self.btn_fwd, self.btn_undo)
        left = QHBoxLayout()
        left.setSpacing(10)
        if self.unified:
            left.addSpacing(62)   # spazio per i semafori (chiudi, riduci, schermo intero)
        left.addWidget(self.nav_pill)
        minus, plus = QLabel("–"), QLabel("+")
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(0, 100)
        self.zoom_slider.setFixedWidth(110)
        self.zoom_slider.setFocusPolicy(Qt.NoFocus)
        self.zoom_slider.setToolTip("Zoom (anche due dita sul trackpad o rotella; doppio clic = foto intera)")
        self.zoom_pill = QFrame()   # sopra la foto, sotto la data (vedi place_zoom)
        self.zoom_pill.setObjectName("zoompill")
        zl = QHBoxLayout(self.zoom_pill)
        zl.setContentsMargins(12, 3, 12, 3)
        zl.setSpacing(8)
        for w in (minus, self.zoom_slider, plus):
            zl.addWidget(w)
        for w in (minus, plus):
            w.setObjectName("muted")
        left.addStretch(1)

        self.badge = QLabel("")
        self.heading = ElidedLabel(mode=Qt.ElideMiddle)
        self.heading.setObjectName("heading")
        self.chosen_tag = QLabel("")
        self.chosen_tag.setObjectName("chosen")
        self.chosen_tag.setToolTip("Questo elemento è già stato deciso. Premi un'altra scelta per cambiarla:\n"
                                   "la nuova sostituisce la vecchia e i file tornano a posto (Z annulla).")
        self.chosen_tag.hide()
        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        head_row.addStretch(1)
        head_row.addWidget(self.badge)
        head_row.addWidget(self.heading, 0)
        head_row.addWidget(self.chosen_tag)
        head_row.addStretch(1)
        self.title = ElidedLabel()
        self.title.setObjectName("subtitle")
        self.title.setAlignment(Qt.AlignCenter)
        center = QVBoxLayout()
        center.setSpacing(1)
        center.addLayout(head_row)
        center.addWidget(self.title)

        self.btn_fav = QPushButton("♡")
        self.btn_fav.setObjectName("fav")
        self.btn_fav.setToolTip("Preferita (.): le preferite approvate vengono copiate in\n"
                                "export/Preferite invece che in export.")
        self.btn_fav.clicked.connect(self.toggle_favorite)
        self.btn_help = QPushButton("?")
        self.btn_help.setToolTip("Come funziona (? o H): spiega tutti i pulsanti e i tasti.\n"
                                 "Da qui apri anche il file di log.")
        self.btn_help.clicked.connect(self.show_help)
        self.btn_info = QPushButton("ⓘ")
        self.btn_info.setObjectName("info")
        self.btn_info.setToolTip("Mostra / nascondi il pannello delle informazioni (I).")
        self.btn_info.clicked.connect(self.toggle_side)
        self.btn_settings = QPushButton("⚙︎")
        self.btn_settings.setToolTip("Impostazioni: cartella, export, filtro, formato e ora.")
        self.btn_settings.clicked.connect(self.show_settings)
        self.fav_pill = pill(self.btn_fav)
        right = QHBoxLayout()
        right.setSpacing(8)
        right.addStretch(1)
        right.addWidget(self.fav_pill)
        right.addWidget(pill(self.btn_info, self.btn_settings, self.btn_help))

        top = QGridLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setHorizontalSpacing(12)
        top.addLayout(left, 0, 0)
        top.addLayout(center, 0, 1)
        top.addLayout(right, 0, 2)
        top.setColumnStretch(0, 1)   # colonne laterali uguali: il titolo resta centrato davvero
        top.setColumnStretch(1, 2)
        top.setColumnStretch(2, 1)
        lay.addLayout(top)

        # ---- impostazioni: finestrella che si apre dal pulsante ⚙ (come i menu di Foto)
        self.btn_open = QPushButton("📂  Apri cartella…")
        self.btn_open.clicked.connect(self.choose_root)
        self.btn_export = QPushButton("Export: —")
        self.btn_export.clicked.connect(self.choose_export)
        self.btn_show_export = QPushButton(f"Mostra export in {FILE_MANAGER}")
        self.btn_show_export.clicked.connect(self.open_export)
        self.fmt = QComboBox()
        self.fmt.addItems(["JPEG qualità massima", "PNG 16-bit (senza perdita)"])
        self.tz = QComboBox()
        self.tz.addItem("Ora: della fotocamera", None)
        for h in range(-12, 15):
            self.tz.addItem(f"Ora: UTC{h:+d}", float(h))
        self.view_filter = QComboBox()
        self.view_filter.addItems(["Mostra: tutto", "Mostra: solo foto (anche Live e panorami)"])
        self.view_filter.setCurrentIndex(1 if self.photos_only else 0)
        self.view_filter.currentIndexChanged.connect(self.on_filter_changed)
        btn_help2 = QPushButton("?  Come funziona")
        btn_help2.clicked.connect(self.show_help)
        tips = {
            self.btn_open: "Scegli la cartella con foto e video (vengono lette anche le sottocartelle).",
            self.btn_export: "Cartella dove vengono COPIATE le foto approvate. Gli originali non si toccano.",
            self.btn_show_export: f"Apre la cartella export in {FILE_MANAGER}.",
            self.fmt: "Formato dei fotogrammi estratti da Live e video.\n"
                      "JPEG qualità massima: accettato da tutti i siti di stampa.\n"
                      "PNG 16-bit: senza perdita, file molto grandi (~40 MB).\n"
                      "Foto e panorami vengono sempre copiati identici.",
            self.tz: "Fuso orario scritto nella data delle foto esportate.\n"
                     "'Della fotocamera' usa l'ora registrata in ogni file.",
            self.view_filter: "Solo foto: nasconde i video (restano foto, Live e panorami).\n"
                              "I video nascosti non vengono toccati: li ritrovi con 'Mostra: tutto'.",
            btn_help2: self.btn_help.toolTip(),
        }
        for w, t in tips.items():
            w.setToolTip(t)
            w.setFocusPolicy(Qt.NoFocus)
        self.settings_pop = QFrame(self, Qt.Popup)
        self.settings_pop.setAttribute(Qt.WA_TranslucentBackground)
        pv = QVBoxLayout(self.settings_pop)
        pv.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("settings")
        pv.addWidget(card)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(16, 8, 16, 16)
        cv.setSpacing(7)
        for head, widgets in (("CARTELLE", (self.btn_open, self.btn_export, self.btn_show_export)),
                              ("VISUALIZZA", (self.view_filter,)),
                              ("FOTOGRAMMI ESPORTATI", (self.fmt, self.tz)),
                              ("AIUTO", (btn_help2,))):
            lab = QLabel(head)
            lab.setObjectName("section")
            cv.addWidget(lab)
            for w in widgets:
                cv.addWidget(w)
        for b in (self.btn_open, self.btn_export, self.btn_show_export, btn_help2):
            b.clicked.connect(self.settings_pop.hide)  # le finestre di scelta si aprono sopra
        self.settings_pop.setFixedWidth(310)

        # ---- pannello a destra: solo informazioni utili (come il pannello Info di Foto)
        self.side = QFrame()
        self.side.setObjectName("side")
        self.side.setFixedWidth(280)
        # scelta dell'utente (ⓘ o I), ricordata; nella schermata iniziale resta nascosto
        self.side_wanted = self.settings_store.value("side", "1") != "0"
        # il contenuto scorre: con molti metadati o foto prese non impone più l'altezza della finestra
        side_body = QWidget()
        side_body.setObjectName("sidebody")
        side_scroll = QScrollArea()
        side_scroll.setObjectName("sidescroll")
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_scroll.setWidget(side_body)
        side_outer = QVBoxLayout(self.side)
        side_outer.setContentsMargins(0, 0, 0, 0)
        side_outer.addWidget(side_scroll)
        sv = QVBoxLayout(side_body)
        sv.setContentsMargins(18, 14, 18, 18)
        sv.setSpacing(8)
        self.side_layout = sv
        self.side_info = QLabel("INFO")
        self.side_info.setObjectName("section")
        sv.addWidget(self.side_info)
        self.side_details = QLabel("")
        self.side_details.setObjectName("details")
        self.side_details.setWordWrap(True)
        self.side_details.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.side_details.setOpenExternalLinks(True)   # solo il link "Apri nella mappa", se cliccato
        sv.addWidget(self.side_details)
        self.side_slot = sv.count()   # qui arrivano le foto prese da un video
        sel = QLabel("SELEZIONE")
        sel.setObjectName("section")
        sv.addWidget(sel)
        self.counter = QLabel("")
        self.counter.setObjectName("details")
        self.counter.setWordWrap(True)
        sv.addWidget(self.counter)
        self.side_sel = sel
        # salvataggio: deve essere chiaro che è automatico, quando è avvenuto e dove sta
        self.save_head = QLabel("SALVATAGGIO")
        self.save_head.setObjectName("section")
        sv.addWidget(self.save_head)
        self.save_info = QLabel("")
        self.save_info.setObjectName("details")
        self.save_info.setWordWrap(True)
        self.save_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sv.addWidget(self.save_info)
        self.btn_save_now = QPushButton("Salva ora")
        self.btn_save_now.setToolTip("Non serve: si salva da solo a ogni scelta.\n"
                                     "Se vuoi esserne sicuro, questo salva subito.")
        self.btn_save_now.clicked.connect(self.save_now)
        self.btn_show_save = QPushButton("Mostra")
        self.btn_show_save.setToolTip(f"Mostra in {FILE_MANAGER} il file con i progressi.")
        self.btn_show_save.clicked.connect(self.reveal_session)
        self.btn_side_export = QPushButton("Export")
        self.btn_side_export.setToolTip(f"Apre in {FILE_MANAGER} la cartella con le foto approvate.")
        self.btn_side_export.clicked.connect(self.open_export)
        self.save_row = QWidget()
        srow = QHBoxLayout(self.save_row)
        srow.setContentsMargins(0, 2, 0, 0)
        srow.setSpacing(6)
        for b in (self.btn_save_now, self.btn_show_save, self.btn_side_export):
            b.setObjectName("small")
            b.setFocusPolicy(Qt.NoFocus)
            srow.addWidget(b)
        srow.addStretch(1)
        sv.addWidget(self.save_row)
        sv.addStretch(1)
        ver = QLabel(APP_TITLE)
        ver.setObjectName("muted")
        sv.addWidget(ver)
        outer.addWidget(self.side)

        # carica preferenze
        self.fmt.setCurrentIndex(1 if self.settings_store.value("fmt") == "png16" else 0)
        tz = self.settings_store.value("tz")
        if tz not in (None, ""):
            i = self.tz.findData(float(tz))
            if i >= 0:
                self.tz.setCurrentIndex(i)
        self.fmt.currentIndexChanged.connect(self.save_prefs)
        self.tz.currentIndexChanged.connect(self.save_prefs)

        # ---- foto / video / messaggi / schermata iniziale
        self.stack = QStackedWidget()
        self.image_view = ImageView()
        self.zoom_slider.valueChanged.connect(lambda v: self.image_view.set_zoom_level(v / 100))
        self.image_view.zoom_changed.connect(self.on_zoom_changed)
        self.image_view.view_changed.connect(lambda: self.place_stamp())
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background: #1c1c1e;")
        self.message = QLabel("")
        self.message.setObjectName("big")
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setWordWrap(True)
        msg_page = QWidget()
        mlay = QVBoxLayout(msg_page)
        mlay.addStretch(1)
        mlay.addWidget(self.message)
        mlay.addSpacing(18)
        self.msg_buttons = QHBoxLayout()
        self.msg_buttons.setSpacing(10)
        self.msg_btn1 = QPushButton()
        self.msg_btn2 = QPushButton()
        for b in (self.msg_btn1, self.msg_btn2):
            b.setFocusPolicy(Qt.TabFocus)
            b.setMinimumHeight(36)
            self.msg_buttons.addWidget(b)
        hb = QHBoxLayout()
        hb.addStretch(1)
        hb.addLayout(self.msg_buttons)
        hb.addStretch(1)
        mlay.addLayout(hb)
        mlay.addStretch(1)
        self.setup_page = self._build_setup()
        for w in (self.image_view, self.video_widget, msg_page, self.setup_page):
            self.stack.addWidget(w)
        self.msg_page = msg_page
        lay.addWidget(self.stack, 1)
        # in sovraimpressione: data e ora (SOLO a schermo, mai nei file esportati), avvisi, messaggi
        self.zoom_pill.setParent(self.stack)
        self.zoom_pill.hide()
        self.stamp = QLabel("", self.stack)
        self.stamp.setObjectName("stamp")
        self.stamp.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.stamp.hide()
        self.warn = OverlayLabel(self.stack, "top-right")
        self.warn.setObjectName("chip")
        self.warn.avoid = [self.stamp, self.zoom_pill]
        self.status = OverlayLabel(self.stack, "bottom", hide_after_ms=8000)   # errori: un po' di più
        self.status.setObjectName("toast")
        self.stack.installEventFilter(self)
        self.stack.currentChanged.connect(lambda *_: self.refresh_stamp())
        self.stack.currentChanged.connect(lambda *_: self.refresh_chrome())

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)
        self.video_widget.videoSink().videoSizeChanged.connect(lambda: self.place_stamp())
        self.player.errorOccurred.connect(self.on_player_error)

        # ---- barra della scena (solo Live e video): pillola sotto la foto, come in Foto
        self.scene_bar = QFrame()
        self.scene_bar.setObjectName("scenebar")
        self.scene_bar.setMaximumWidth(980)
        vbar = QVBoxLayout(self.scene_bar)
        vbar.setContentsMargins(12, 8, 12, 8)
        vbar.setSpacing(6)
        timeline = QHBoxLayout()
        timeline.setSpacing(4)
        sl = QHBoxLayout()
        sl.setSpacing(8)
        self.btn_play = QPushButton("⏸")
        self.btn_play.setObjectName("play")
        self.btn_play.setToolTip("Play / Pausa (barra spaziatrice)")
        self.btn_play.clicked.connect(self.play_pause)
        self.btn_prev = QPushButton("‹")
        self.btn_prev.setObjectName("arrow")
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.strip = FilmStrip()
        self.strip.picked.connect(self.on_strip_picked)
        self.time_label = QLabel("")
        tf = self.time_label.font()
        if hasattr(tf, "setFeature"):   # cifre a larghezza fissa: il tempo non "balla" (Qt ≥ 6.7)
            try:
                tf.setFeature(QFont.Tag("tnum"), 1)
                self.time_label.setFont(tf)
            except (AttributeError, TypeError):
                pass
        self.time_label.setMinimumWidth(118)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.btn_next = QPushButton("›")
        self.btn_next.setObjectName("arrow")
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.frame_label = ElidedLabel()
        self.frame_label.setAlignment(Qt.AlignCenter)
        self.btn_live = QPushButton("▶  Vedi Live (L)")
        self.btn_live.setObjectName("live")
        self.btn_live.setToolTip("Guarda il video della Live (L). Lì puoi anche cambiare fotogramma.")
        self.btn_live.clicked.connect(self.toggle_live)
        self.btn_replay = QPushButton("⟲  Rivedi (V)")
        self.btn_replay.setToolTip("Riguarda il video dall'inizio, con l'audio (V).")
        self.btn_replay.clicked.connect(self.replay)
        self.btn_snap = QPushButton("📷  Prendi foto (F)")
        self.btn_snap.setToolTip("Salva SUBITO come foto il fotogramma che stai guardando (F)\n"
                                 "e resta su questo video: puoi prenderne quante vuoi.\n"
                                 "Le foto salvate sono i segni verdi sulla striscia.\n"
                                 "Poi con SÌ / NO decidi se tenere anche il video.")
        self.btn_snap.clicked.connect(self.take_photo)
        self.btn_sharp = QPushButton("✨  Più nitida (P)")
        self.btn_sharp.clicked.connect(self.pick_sharpest)
        self.btn_reset = QPushButton("↺  Originale (R)")
        self.btn_reset.clicked.connect(self.reset_frame)
        self.btn_prev.setToolTip("Fotogramma precedente (←, Maiusc+← = 10 indietro)")
        self.btn_next.setToolTip("Fotogramma successivo (→, Maiusc+→ = 10 avanti)")
        self.strip.setToolTip("Clic o trascina sulla striscia per scegliere il fotogramma.\n"
                              "Live: quello scelto diventa la foto (SÌ salva questa).\n"
                              "Live: il pallino giallo è la foto scelta dalla fotocamera (R per tornarci).\n"
                              "Video: si ferma lì, poi 📷 Prendi foto.  ← → un fotogramma alla volta.")
        self.btn_sharp.setToolTip("Cerca il fotogramma più nitido (meno mosso) vicino a quello mostrato (P).")
        self.btn_reset.setToolTip("Torna al fotogramma che la fotocamera aveva scelto come foto (R).")
        for w in (self.btn_play, self.btn_prev, self.strip, self.btn_next, self.time_label):
            w.setFocusPolicy(Qt.NoFocus)
            timeline.addWidget(w, 1 if w is self.strip else 0)
        sl.addStretch(1)
        for w in (self.btn_live, self.btn_replay, self.btn_snap, self.btn_sharp, self.btn_reset):
            w.setFocusPolicy(Qt.NoFocus)
            sl.addWidget(w)
        sl.addStretch(1)
        vbar.addLayout(timeline)
        vbar.addLayout(sl)
        vbar.addWidget(self.frame_label)
        scene_row = QHBoxLayout()
        scene_row.addStretch(1)
        scene_row.addWidget(self.scene_bar, 100)
        scene_row.addStretch(1)
        lay.addLayout(scene_row)
        self.player.positionChanged.connect(self.on_position)
        self.player.playbackStateChanged.connect(self.on_play_state)

        # ---- scelta, stile Tinder: pulsanti rotondi centrati, con il tasto scritto sotto
        self.choice_btns: list[QPushButton] = []

        def round_btn(text, name, size, tip, slot, cls=QPushButton):
            b = cls(text)
            b.setObjectName(name)
            b.setProperty("round", "true")
            b.setFixedSize(size, size)
            b.base_size = size   # misura a finestra normale; con lo schermo grande cresce (layout_choices)
            self.choice_btns.append(b)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            return b

        self.btn_trash = round_btn("", "trash", 48,
                                   "Sposta in “cancellare” (X). Non cancella: SPOSTA l'originale\n"
                                   "(e la sua anteprima .LRF) nella cartella “cancellare” dentro la\n"
                                   "cartella che stai guardando, con le stesse sottocartelle.\n"
                                   "Poi lo cancelli tu a mano, se vuoi. Z lo rimette al suo posto.",
                                   lambda: self.decide("trash"), TrashButton)
        self.btn_no = round_btn("✕", "no", 66, "NO (N): scarta, non viene copiato niente.",
                                lambda: self.decide("no"))
        self.btn_skip = round_btn("↪", "skip", 48,
                                  "Salta (S): decidi dopo. A fine giro puoi rivedere tutte le saltate.",
                                  lambda: self.decide("skip"))
        self.btn_yes = round_btn("✓", "yes", 66,
                                 "SÌ (Y o Invio): approva e copia in export.\n"
                                 "Foto/panorami: copia identica.  Live: salva la foto.\n"
                                 "Video: copia il video in export/Video (per le foto usa 📷 Prendi foto).",
                                 lambda: self.decide("yes"))
        self.btn_yes_video = round_btn("＋", "yesvideo", 48,
                                       "SÌ e copia anche il video (Maiusc+Y).\n"
                                       "Live: salva la foto E copia il video MP4 originale in export/Video.\n"
                                       "Video: si attiva dopo aver preso almeno una foto con 📷;\n"
                                       "tiene le foto e copia anche il video in export/Video.",
                                       lambda: self.decide("yes", with_video=True))
        choices = QHBoxLayout()
        choices.setSpacing(16)
        self.choice_caps: dict[str, QLabel] = {}
        self.cap_of: dict[QPushButton, QLabel] = {}
        for b, cap in ((self.btn_trash, "No e cancella (X)"),
                       (self.btn_no, "No (N)"), (self.btn_skip, "Salta (S)"),
                       (self.btn_yes, "Sì (Y)"), (self.btn_yes_video, "Sì + video (⇧Y)")):
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addStretch(1)
            col.addWidget(b, 0, Qt.AlignHCenter)
            b.setAccessibleName(cap.replace(" (", ", tasto ").rstrip(")"))  # VoiceOver: non "segno di moltiplicazione"
            c = QLabel(cap)
            self.choice_caps[b.objectName()] = c
            c.setObjectName("cap")
            c.setAlignment(Qt.AlignCenter)
            c.setFixedWidth(104)   # larghezza fissa: i pulsanti non si spostano quando cambia il testo
            c.setWordWrap(True)
            self.cap_of[b] = c
            b.installEventFilter(self)   # pulsante spento → didascalia spenta
            col.addWidget(c, 0, Qt.AlignHCenter)
            choices.addLayout(col)

        self.snaps_label = QLabel("")
        self.snaps_label.setObjectName("snaps")
        self.snaps_label.setWordWrap(True)
        self.snaps_label.setProperty("empty", "true")
        self.snaps_label.setToolTip("Foto prese da questo video con 📷 Prendi foto.\n"
                                    "Restano salvate in export anche se premi NO.\n"
                                    "Z annulla l'ultima presa.")
        self.next_box = QFrame()
        self.next_box.setObjectName("next")
        nb = QVBoxLayout(self.next_box)
        nb.setContentsMargins(8, 6, 8, 8)
        nb.setSpacing(4)
        self.next_txt = ElidedLabel()
        self.next_txt.setObjectName("muted")
        self.next_img = QLabel("")
        self.next_img.setObjectName("muted")
        self.next_img.setAlignment(Qt.AlignCenter)
        nb.addWidget(self.next_txt)
        nb.addWidget(self.next_img)
        self.next_box.setToolTip("Anteprima dell'elemento che arriva dopo questa scelta.")
        self.next_box.hide()
        self.next_img.setFixedSize(234, 132)
        self.snap_gallery = SnapGallery()
        self.snap_gallery.picked.connect(self.review_snap)
        self.snap_gallery.opened.connect(lambda f: QDesktopServices.openUrl(QUrl.fromLocalFile(f)))
        self.snap_gallery.removed.connect(self.remove_snap)
        self.snap_gallery.setToolTip("Foto prese da questo video.\nClic: il video torna su quel "
                                     "fotogramma per rivederlo.\nDoppio clic: apre il file salvato.\n"
                                     "✕: toglie la foto da export (puoi riprenderla con F).")
        # in basso a destra, sopra il numero di versione
        self.side_layout.insertWidget(self.side_layout.count() - 1, self.snaps_label)
        self.side_layout.insertWidget(self.side_layout.count() - 1, self.snap_gallery)
        self.side_layout.insertSpacing(self.side_layout.count() - 1, 6)
        self.side_layout.insertWidget(self.side_slot, self.next_box)
        self.next_box.setVisible(False)   # sostituita dalla striscia delle miniature in basso
        self.decision_bar = QWidget()
        bottom = QHBoxLayout(self.decision_bar)
        bottom.setContentsMargins(0, 2, 0, 0)
        bottom.addStretch(1)
        bottom.addLayout(choices)   # sempre al centro, sotto la foto
        bottom.addStretch(1)
        lay.addWidget(self.decision_bar)
        self.thumbs_strip = ThumbStrip()
        self.thumbs_strip.setToolTip("Le foto prima e dopo questa. Clic per andarci.\n"
                                     "Il pallino colorato è la scelta già fatta.")
        self.thumbs_strip.picked.connect(self.jump_to)
        # filtro della striscia: mostra solo le miniature con una certa scelta (o ancora da fare)
        # Pulsante che apre un popup personalizzato (il QComboBox nativo è brutto su macOS)
        self._strip_filter_key = self.settings_store.value("strip_filter", "all")
        self._strip_filter_label = dict(STRIP_FILTERS).get(self._strip_filter_key,
                                                            STRIP_FILTERS[0][0])
        # Trova l'etichetta corrispondente alla chiave salvata
        for lbl, k in STRIP_FILTERS:
            if k == self._strip_filter_key:
                self._strip_filter_label = lbl
                break
        self.strip_filter_btn = QPushButton(self._strip_filter_label + "  ▾")
        self.strip_filter_btn.setObjectName("stripnav")
        self.strip_filter_btn.setFocusPolicy(Qt.NoFocus)
        self.strip_filter_btn.setToolTip("Quali miniature mostrare nella striscia in basso.\n"
                                         "Quella che stai guardando resta sempre visibile.")
        self.strip_filter_btn.setFixedWidth(220)
        self.strip_filter_btn.clicked.connect(self._show_strip_filter_popup)
        # Il popup del filtro: una card scura con le voci come pulsanti
        self._strip_filter_pop = QFrame(self, Qt.Popup)
        self._strip_filter_pop.setAttribute(Qt.WA_TranslucentBackground)
        _sfp_outer = QVBoxLayout(self._strip_filter_pop)
        _sfp_outer.setContentsMargins(0, 0, 0, 0)
        _sfp_card = QFrame()
        _sfp_card.setObjectName("settings")
        _sfp_outer.addWidget(_sfp_card)
        _sfp_v = QVBoxLayout(_sfp_card)
        _sfp_v.setContentsMargins(8, 8, 8, 8)
        _sfp_v.setSpacing(3)
        self._strip_filter_btns: list[tuple[QPushButton, str]] = []
        for label, key in STRIP_FILTERS:
            fb = QPushButton(label)
            fb.setFocusPolicy(Qt.NoFocus)
            fb.setStyleSheet("")  # stile dalla card
            fb.clicked.connect(lambda _=False, k=key, l=label: self._pick_strip_filter(k, l))
            _sfp_v.addWidget(fb)
            self._strip_filter_btns.append((fb, key))
        self._strip_filter_pop.setFixedWidth(240)
        self._update_strip_filter_highlight()
        # Oggetto finto per compatibilità: currentData() usato in update_thumb_strip
        class _StripFilterProxy:
            def __init__(self, owner): self._owner = owner
            def currentData(self): return self._owner._strip_filter_key
            def setVisible(self, v): self._owner.strip_filter_btn.setVisible(v)
            def isVisible(self): return self._owner.strip_filter_btn.isVisible()
        self.strip_filter = _StripFilterProxy(self)
        strip_row = QHBoxLayout()
        strip_row.setSpacing(8)
        # a sinistra: il filtro e, sotto, il ritorno all'analisi
        left_col = QVBoxLayout()
        left_col.setSpacing(4)
        left_col.addWidget(self.strip_filter_btn, 0, Qt.AlignVCenter)
        self.btn_locate = QPushButton("⤳  Torna all'analisi")
        self.btn_locate.setObjectName("stripnav")
        self.btn_locate.setToolTip("Torna alla prima foto ancora da decidere\n"
                                   "(la prossima da giudicare)")
        self.btn_locate.setFocusPolicy(Qt.TabFocus)
        self.btn_locate.setFixedWidth(180)
        self.btn_locate.clicked.connect(self.locate_thumb)
        left_col.addWidget(self.btn_locate, 0, Qt.AlignVCenter)
        strip_row.addLayout(left_col)
        # intorno alla striscia: frecce per scorrere avanti e indietro tra le miniature
        self.btn_thumb_prev = QPushButton("‹")
        self.btn_thumb_next = QPushButton("›")
        for b, step in ((self.btn_thumb_prev, -1), (self.btn_thumb_next, 1)):
            b.setObjectName("stripnav")
            b.setFixedSize(30, 30)
            b.setFocusPolicy(Qt.TabFocus)
            b.setToolTip("Scorri le miniature indietro" if step < 0 else "Scorri le miniature avanti")
            b.clicked.connect(lambda _=False, st=step: self.scroll_thumbs(st))
        strip_row.addWidget(self.btn_thumb_prev, 0, Qt.AlignVCenter)
        strip_row.addWidget(self.thumbs_strip, 1)
        strip_row.addWidget(self.btn_thumb_next, 0, Qt.AlignVCenter)
        self.btn_return = QPushButton("⤳ Torna all'ultima")
        self.btn_return.setToolTip("Torna alla foto da cui sei tornato indietro (con ↑ o B).")
        self.btn_return.setFocusPolicy(Qt.TabFocus)
        self.btn_return.setFixedWidth(180)
        self.btn_return.setVisible(False)
        self.btn_return.clicked.connect(self.return_to_last)
        strip_row.addWidget(self.btn_return, 0, Qt.AlignVCenter)
        self.return_idx: int | None = None   # dove eri prima di tornare indietro
        lay.addLayout(strip_row)

        self.dl_timer = QTimer(self)
        self.dl_timer.setInterval(500)
        self.dl_timer.timeout.connect(self.update_download_message)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(90)
        self.preview_timer.timeout.connect(self.request_preview)

    def on_zoom_changed(self, t: float):
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(round(t * 100))
        self.zoom_slider.blockSignals(False)

    def show_settings(self):
        pop = self.settings_pop
        pop.adjustSize()
        b = self.btn_settings
        pos = b.mapToGlobal(b.rect().bottomRight())
        pop.move(pos.x() - pop.width() + 6, pos.y() + 10)
        pop.show()

    def toggle_side(self):
        self.side_wanted = not self.side_wanted
        self.side.setVisible(self.side_wanted and self.stack.currentWidget() is not self.setup_page)
        self.settings_store.setValue("side", "1" if self.side_wanted else "0")
        self.update_btn_info()

    def refresh_chrome(self):
        """Nella schermata iniziale niente barra della scelta né navigazione: solo il riquadro."""
        browsing = self.stack.currentWidget() is not self.setup_page
        self.decision_bar.setVisible(browsing)
        self.nav_pill.setVisible(browsing)
        self.place_zoom()
        self.zoom_slider.setEnabled(self.stack.currentWidget() is self.image_view)
        self.fav_pill.setVisible(browsing)
        self.btn_info.setVisible(browsing)   # nella schermata iniziale non ha niente da mostrare
        # schermata iniziale: niente pannello Info vuoto, così il riquadro resta al centro
        self.side.setVisible(browsing and self.side_wanted)
        self.update_btn_info()
        for w in (self.side_info, self.side_details, self.side_sel, self.counter, self.snaps_label,
                  self.snap_gallery, self.save_head, self.save_info, self.save_row,
                  self.thumbs_strip, self.strip_filter):
            w.setVisible(browsing)

    def update_btn_info(self):
        self.btn_info.setProperty("on", "true" if self.side_wanted else "false")
        self.btn_info.style().unpolish(self.btn_info)
        self.btn_info.style().polish(self.btn_info)

    def layout_choices(self) -> None:
        """Cerchi ✕ ✓ ↪ 🗑 ＋: più grandi quando lo schermo lo permette (finestra alta)."""
        k = min(1.6, max(1.0, self.height() / 760))   # 1.0 fino a ~760 px di altezza, 1.6 a schermo grande
        for b in self.choice_btns:
            size = round(b.base_size * k)
            fs = round((28 if b.objectName() in ("no", "yes") else 20) * k)
            b.setFixedSize(size, size)
            b.setIconSize(QSize(round(22 * k), round(22 * k)))
            b.setStyleSheet(f"border-radius: {size // 2}px; font-size: {fs}px;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "choice_btns", None):
            self.layout_choices()

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "choice_btns", None):
            self.layout_choices()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.EnabledChange and obj in getattr(self, "cap_of", {}):
            self.cap_of[obj].setEnabled(obj.isEnabled())
        if obj is self.stack and e.type() == QEvent.Resize:
            self.warn.place()
            self.status.place()
            self.place_stamp()
        return super().eventFilter(obj, e)

    def _build_setup(self) -> QWidget:
        """Schermata iniziale: 1) cartella da guardare, 2) cartella export, poi Inizia."""
        self.pick_root: Path | None = None
        self.pick_export: Path | None = None
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addStretch(1)
        box = QFrame()
        box.setObjectName("setup")
        box.setMaximumWidth(780)
        v = QVBoxLayout(box)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(10)
        title = QLabel(f"Nuova selezione   <span style='font-size:13px; color:#9a9ca0; font-weight:400'>"
                       f"{APP_TITLE}</span>")
        title.setObjectName("h1")
        v.addWidget(title)
        self.setup_note = QLabel("")
        self.setup_note.setObjectName("warn")
        self.setup_note.setWordWrap(True)
        v.addWidget(self.setup_note)

        def step(num, head, desc, button_text, slot):
            v.addSpacing(8)
            h = QLabel(f"{num}  {head}")
            h.setObjectName("step")
            d = QLabel(desc)
            d.setObjectName("muted")
            d.setWordWrap(True)
            row = QHBoxLayout()
            path = ElidedLabel("", mode=Qt.ElideMiddle)   # percorsi lunghi: "…" in mezzo
            path.setObjectName("path")
            btn = QPushButton(button_text)
            btn.setFocusPolicy(Qt.TabFocus)   # raggiungibile con Tab, Invio/Spazio lo premono
            btn.setMinimumHeight(36)
            btn.clicked.connect(slot)
            row.addWidget(path, 1)
            row.addWidget(btn)
            for w in (h, d):
                v.addWidget(w)
            v.addLayout(row)
            return path, btn

        self.src_label, self.btn_pick_src = step(
            "①", "Cartella da guardare",
            "La cartella copiata dalla scheda SD (per esempio DCIM). "
            "Vengono lette anche tutte le sottocartelle.",
            "Scegli cartella…", self.pick_source)
        self.dst_label, self.btn_pick_dst = step(
            "②", "Cartella export: dove copiare quelle approvate",
            "Le foto approvate vengono copiate qui, i video nella sottocartella “Video”. "
            "Gli originali non vengono mai spostati né modificati.",
            "Scegli cartella…", self.pick_destination)
        v.addSpacing(8)
        self.q_local = QLabel("")
        self.q_local.setObjectName("muted")
        self.q_local.setWordWrap(True)
        self.q_local.setMinimumHeight(2 * self.q_local.fontMetrics().lineSpacing() + 4)
        v.addWidget(self.q_local)
        v.addSpacing(14)
        row = QHBoxLayout()
        self.btn_resume = QPushButton("")
        self.btn_resume.setFocusPolicy(Qt.TabFocus)
        self.btn_resume.clicked.connect(self.resume_last)
        self.btn_start = QPushButton("Inizia  ▶")
        self.btn_start.setObjectName("start")
        self.btn_start.setMinimumSize(150, 50)
        self.btn_start.setFocusPolicy(Qt.TabFocus)
        self.btn_start.clicked.connect(self.start_from_setup)
        row.addWidget(self.btn_resume)
        row.addStretch(1)
        row.addWidget(self.btn_start)
        v.addLayout(row)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(box, 10)
        h.addStretch(1)
        outer.addLayout(h)
        outer.addStretch(1)
        # in un'area che scorre: la schermata iniziale non impone più la sua altezza alla finestra
        # (le pagine del contenitore valgono tutte, anche mentre si guardano le foto)
        scroll = QScrollArea()
        scroll.setObjectName("setupscroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        page.setObjectName("setuppage")
        return scroll

    def show_setup(self, note: str = ""):
        self.player.stop()
        self.scene_bar.setVisible(False)
        for w in (self.badge, self.heading, self.title, self.warn, self.side_details):
            w.setText("")
        self.badge.setStyleSheet("")
        self.set_buttons_enabled(False)
        self.setup_note.setText(note)
        self.setup_note.setVisible(bool(note))
        self.refresh_setup()
        self.stack.setCurrentWidget(self.setup_page)
        self.refresh_chrome()

    @staticmethod
    def cloud_files_in(root: Path, limit: int = 400) -> int | None:
        """Quanti file (su un campione) sono solo su iCloud. None = cartella non leggibile."""
        n = seen = 0
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for name in filenames:
                    if name.startswith(".") and not name.endswith(".icloud"):
                        continue
                    seen += 1
                    if name.endswith(".icloud") or not cloud.is_local(Path(dirpath) / name):
                        n += 1
                    if seen >= limit:
                        return n
        except OSError:
            return None
        return n

    def refresh_setup(self):
        self.src_label.setText(str(self.pick_root) if self.pick_root else "— nessuna cartella scelta —")
        if self.pick_export:
            self.dst_label.setText(str(self.pick_export))
        elif self.pick_root:
            self.dst_label.setText(f"{self.pick_root / 'export'}   (proposta)")
        else:
            self.dst_label.setText("— prima scegli la cartella da guardare —")
        for lab, empty in ((self.src_label, not self.pick_root),
                           (self.dst_label, not self.pick_root and not self.pick_export)):
            if lab.property("empty") != ("true" if empty else "false"):
                lab.setProperty("empty", "true" if empty else "false")   # segnaposto in grigio
                lab.style().unpolish(lab)
                lab.style().polish(lab)
        self.btn_pick_dst.setEnabled(self.pick_root is not None)
        on_cloud = self.cloud_files_in(self.pick_root) if self.pick_root else None
        local = self.pick_root is not None and on_cloud == 0
        # sempre presente (anche vuota): la scheda non salta quando compare il messaggio
        self.q_local.setText(
            "💽 Cartella su disco (non su iCloud): nessun download, si parte subito." if local else
            "☁️ Questa cartella ha file su iCloud: ogni originale verrà scaricato quando lo apri "
            "(qualità sempre massima, ma con attesa). Per andare veloci usa una cartella su disco."
            if on_cloud else "")
        self.btn_start.setEnabled(self.pick_root is not None)
        last = self.settings_store.value("last_root", "")
        last_exp = self.settings_store.value("last_export", "")
        self.btn_resume.setVisible(bool(last))
        if last:
            self.btn_resume.setText(f"↻  Riprendi l'ultima sessione:  {Path(last).name}  →  "
                                    f"{Path(last_exp).name if last_exp else 'export'}")
            self.btn_resume.setToolTip(f"Da: {last}\nExport: {last_exp}")

    def pick_source(self):
        start = str(self.pick_root or self.settings_store.value("last_root", "") or Path.home())
        d = QFileDialog.getExistingDirectory(self, "①  Scegli la cartella con foto e video da guardare",
                                             start)
        if d:
            self.pick_root = Path(d)
            self.pick_export = None
            self.refresh_setup()
            self.ask_about_saved_work(self.pick_root)

    def ask_about_saved_work(self, root: Path):
        """Cartella già lavorata: mostra lo stato e chiede se riprendere."""
        info = exporter.Session.peek(root)
        if not info:
            return
        c = info["counts"]
        fw = exporter.fmt_when
        total = info["total"] or "?"
        detail = (f"Decise: {info['decided']} su {total}\n"
                  f"✓ {c['yes']} approvate   ✗ {c['no']} scartate   ↪ {c['skip']} saltate"
                  + (f"   🗑 {c['trash']} in “cancellare”" if c.get("trash") else "")
                  + (f"   📷 {c['snap']} foto da video" if c.get("snap") else "") + "\n\n"
                  f"Iniziato il {fw(info['created'])}\n"
                  f"Ultima modifica il {fw(info['updated'])}\n"
                  f"Export: {info['export']}"
                  + ("" if info.get("export_ok", True) else
                     "\n(questa cartella export non c'è su questo computer: "
                     "riprendendo ti chiedo dove copiare)"))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        if info["completed"]:
            box.setWindowTitle("Lavoro completato")
            box.setText(f"<b>Questa cartella è già stata completata</b> "
                        f"(chiuso il {fw(info['closed'] or info['updated'])}).<br>Vuoi riaprirla?")
            resume = box.addButton("Riapri", QMessageBox.AcceptRole)
        else:
            box.setWindowTitle("Lavoro non completato")
            when = fw(info["closed"] or info["updated"])
            box.setText(f"<b>In questa cartella c'è un lavoro a metà</b> (interrotto il {when}).<br>"
                        f"Vuoi riprendere da dove eri?")
            resume = box.addButton("Riprendi da dove eri", QMessageBox.AcceptRole)
        box.setInformativeText(detail)
        restart = box.addButton("Ricomincia da capo", QMessageBox.DestructiveRole)
        box.addButton("Annulla", QMessageBox.RejectRole)
        box.setDefaultButton(resume)
        box.exec()
        clicked = box.clickedButton()
        if clicked is resume:
            if not info.get("export_ok", True):
                # salvataggio fatto su un altro computer (o disco export scollegato): le scelte
                # si riprendono, ma le nuove copie vanno in una cartella che esiste qui
                self.pick_export = None
                self.refresh_setup()
                self.setup_note.setText(
                    f"Le scelte salvate verranno riprese. La cartella export di allora "
                    f"({info['export']}) non c'è su questo computer: scegli dove copiare "
                    f"le prossime con ②, poi Inizia.")
                self.setup_note.setVisible(True)
                return
            self.pick_export = Path(info["export"])
            self.start_from_setup()
        elif clicked is restart:
            sure = QMessageBox.question(
                self, "Ricomincia da capo",
                "Le scelte salvate verranno messe da parte (il file viene rinominato, non "
                "cancellato).\nLe foto già copiate in export restano dove sono.\n\nContinuare?")
            if sure == QMessageBox.Yes:
                # cartella già aperta: va azzerata la sessione IN MEMORIA, altrimenti alla
                # chiusura (o a Inizia) riscriverebbe sul disco tutte le scelte vecchie
                live = self.session
                if live is None or Path(live.root).resolve() != Path(root).resolve():
                    live = None
                (live or exporter.Session(root, Path(info["export"]))).archive()
                if live is not None:
                    live.save()
                    self.history.clear()
                self.refresh_setup()

    def pick_destination(self):
        if not self.pick_root:
            return
        start = self.pick_export or self.pick_root
        d = QFileDialog.getExistingDirectory(
            self, "②  Scegli (o crea con “Nuova cartella”) dove copiare le approvate", str(start))
        if d:
            problem = exporter.export_dir_problem(self.pick_root, Path(d))
            if problem:
                self.setup_note.setText(problem)
                self.setup_note.setVisible(True)
                return
            self.pick_export = Path(d)
            self.refresh_setup()

    def start_from_setup(self):
        if not self.pick_root:
            return
        self.root = self.pick_root
        self.export_dir = self.pick_export or self.pick_root / "export"
        self.start_scan()

    def _build_shortcuts(self):
        keys = {
            "Y": lambda: self.decide("yes"), "Return": lambda: self.decide("yes"),
            "Enter": lambda: self.decide("yes"),
            "Shift+Y": lambda: self.decide("yes", with_video=True),
            "Shift+Return": lambda: self.decide("yes", with_video=True), "N": lambda: self.decide("no"),
            "S": lambda: self.decide("skip"), "X": lambda: self.decide("trash"), "Z": self.undo, "Ctrl+Z": self.undo,
            "C": self.toggle_scene, "Left": lambda: self.step(-1), "Right": lambda: self.step(1),
            "Shift+Left": lambda: self.step(-10), "Shift+Right": lambda: self.step(10),
            "P": self.pick_sharpest, "R": self.reset_frame, "Space": self.play_pause,
            "?": self.show_help, "H": self.show_help, "V": self.replay, "L": self.toggle_live, "F": self.take_photo,
            "Up": self.go_back, "B": self.go_back, "Down": self.go_forward, ".": self.toggle_favorite,
            "I": self.toggle_side,

        }
        def press_focused_or(fn):
            # un pulsante raggiunto con Tab si preme con Invio/Spazio (le scorciatoie vincerebbero)
            def run():
                w = QApplication.focusWidget()
                if isinstance(w, QPushButton) and w.isVisible() and w.isEnabled() \
                        and w.focusPolicy() != Qt.NoFocus and w.hasFocus():
                    w.click()
                else:
                    fn()
            return run

        for k, fn in keys.items():
            if k in ("Return", "Enter", "Space"):
                fn = press_focused_or(fn)
            sc = QShortcut(QKeySequence(k), self, activated=fn)
            sc.setAutoRepeat(k in ("Left", "Right", "Shift+Left", "Shift+Right"))

    def save_prefs(self):
        self.settings_store.setValue("fmt", self.current_settings().fmt)
        tz = self.tz.currentData()
        self.settings_store.setValue("tz", "" if tz is None else tz)

    def current_settings(self, with_video: bool = False) -> exporter.Settings:
        return exporter.Settings(fmt="png16" if self.fmt.currentIndex() == 1 else "jpeg",
                                 copy_video=with_video,
                                 tz_override_hours=self.tz.currentData())

    # ------------------------------------------------------------------ lavori in background
    def submit(self, kind: str, key, fn, *args, queue=None) -> Future:
        fut = (queue or self.bg).submit(fn, *args)

        def finished(f: Future):
            try:
                res = f.result()
            except Exception as e:  # noqa: BLE001 - mostrato all'utente
                res = e
            self.bridge.done.emit(kind, key, res)
        fut.add_done_callback(finished)
        return fut

    def on_done(self, kind: str, key, res):
        # schermata iniziale aperta: i risultati si conservano ma non cambiano cosa si vede
        cur = self.current() if self.stack.currentWidget() is not self.setup_page else None
        if isinstance(res, Exception):
            log.error("%s %s: %r", kind, key, res, exc_info=res)
        elif kind in ("scan", "ready", "export"):
            log.info("%s %s: %s", kind, key if kind != "scan" else self.root,
                     f"{len(res)} elementi" if kind == "scan" else res)
        if kind == "scan":
            self.on_scanned(res)
        elif kind == "ready":
            if isinstance(res, Exception) and ("ready-now", key) not in self.pending:
                self.pending.discard(("ready-pre", key))
                return  # anticipo non riuscito: si riprova quando l'elemento viene aperto
            self.pending.discard(("ready-now", key))
            self.pending.discard(("ready-pre", key))
            if isinstance(res, Exception):
                if cur and cur.id == key:
                    self.show_message(f"Download da iCloud non riuscito:\n{res}")
                return
            self.ready.add(key)
            if cur and cur.id == key:
                self.show_item()
        elif kind == "analyze":
            self.pending.discard(("analyze", key))
            if isinstance(res, Exception):
                self.status.setText(f"Analisi video non riuscita: {res}")
                return
            info, cam = res
            self.infos[key] = info
            self.camera_frames[key] = cam
            if cur and cur.id == key:
                self.update_item_labels()
                if self.scene_mode:  # "Cambia scena" premuto prima della fine dell'analisi
                    self.scene_mode = False
                    self.toggle_scene()
                elif self.showing_still(cur):
                    self.show_live_still()
                self.update_scene_controls()
        elif kind == "preview":
            self.on_preview(key, res)
        elif kind == "meta":
            self.pending.discard(("meta", key))
            self.meta[key] = res if not isinstance(res, Exception) else metadata.Meta()
            if cur and cur.id == key:
                self.update_item_labels()
        elif kind == "thumb":
            self.pending.discard(("thumb", key))
            self.next_thumbs[key] = res if not isinstance(res, Exception) else QImage()
            self.update_next_preview()
        elif kind == "relocate":
            item_id, token = key
            if not isinstance(res, Exception) and res and self.session:
                self.session.relocated(item_id, token, res)
        elif kind == "strip":
            self.pending.discard(("strip", key))
            if not isinstance(res, Exception):
                self.thumbs[key] = res
                if self.strip.owner == key:
                    self.strip.set_thumbs(res)
        elif kind == "sharpest":
            if cur and cur.id == key and not isinstance(res, Exception):
                self.set_frame(res, manual=True)
        elif kind == "export":
            item_id, frame, token = key
            # l'esito vale solo per la decisione che ha avviato questo export (non annullata,
            # non rifatta, stessa cartella); un errore non cancella la scelta
            outcome = self.session.record_export(item_id, token, res) if self.session else "stale"
            if outcome == "failed":
                self.status.setText(f"Export non riuscito per {Path(item_id).name}: {res} "
                                    "(la scelta resta: si riprova alla prossima apertura)")
            elif outcome == "stale":
                log.info("export %s: esito ignorato, la scelta è cambiata", item_id)
            if cur and item_id == cur.id:
                self.update_item_labels()   # pannello Info: "copia in corso" -> "COPIATA"
            self.update_counter()

    # ------------------------------------------------------------------ cartelle
    def choose_root(self):
        self.pick_root, self.pick_export = self.root, self.export_dir
        self.show_setup()

    def resume_last(self):
        root = self.settings_store.value("last_root", "")
        export = self.settings_store.value("last_export", "")
        if root and Path(root).is_dir():
            self.root, self.export_dir = Path(root), Path(export or Path(root) / "export")
            self.start_scan()
        else:
            self.show_setup("La cartella dell'ultima sessione non è raggiungibile "
                            "(disco scollegato?).")

    def show_help(self):
        # finestra che si scorre: il testo è lungo e non deve uscire dallo schermo
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Come funziona — {APP_TITLE}")
        v = QVBoxLayout(dlg)
        text = QTextBrowser()
        text.setHtml(help_html(HELP_TEXT))
        text.setStyleSheet("QTextBrowser { background: #232325; border: 1px solid #3a3a3c;"
                           " border-radius: 10px; padding: 10px; font-size: 13px; }")
        v.addWidget(text, 1)
        row = QHBoxLayout()
        logs = QPushButton("Mostra il file di log")
        logs.clicked.connect(self.reveal_log)
        close = QPushButton("Chiudi")
        close.setObjectName("primary")
        close.clicked.connect(dlg.accept)
        row.addWidget(logs)
        row.addStretch(1)
        row.addWidget(close)
        v.addLayout(row)
        avail = self.screen().availableGeometry()
        dlg.resize(min(680, avail.width() - 60), min(720, int(avail.height() * 0.85)))
        dlg.exec()

    def reveal_log(self):
        path = applog.log_path()
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def choose_export(self):
        if not self.root:
            return
        d = QFileDialog.getExistingDirectory(self, "Cartella dove copiare le scelte",
                                             str(self.export_dir or self.root))
        if d:
            problem = exporter.export_dir_problem(self.root, Path(d))
            if problem:
                QMessageBox.warning(self, APP_TITLE, problem)
                return
            self.export_dir = Path(d)
            self.start_scan()

    def open_export(self):
        if self.export_dir:
            self.export_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.export_dir)))

    def start_scan(self):
        self.root = self.root.resolve()  # come la scansione: link simbolici (es. ~/Dropbox)
        log.info("apro cartella %s -> export %s", self.root, self.export_dir)
        self.player.stop()
        self.settings_store.setValue("last_root", str(self.root))
        self.settings_store.setValue("last_export", str(self.export_dir))
        self.btn_export.setText(f"Export: {self.export_dir.name}")
        self.btn_export.setToolTip(f"Le foto approvate vengono copiate in:\n{self.export_dir}")
        self.show_message("Lettura della cartella…")
        # anche le cartelle export usate prima (dopo un cambio di export): le copie fatte lì
        # non devono tornare come elementi nuovi da scegliere
        used = self.settings_store.value("export_history") or []
        used = [str(p) for p in ([used] if isinstance(used, str) else used) if p]
        used = list(dict.fromkeys([str(self.export_dir.resolve())] + used))[:50]
        self.settings_store.setValue("export_history", used)
        self.submit("scan", None, scan, self.root,
                    [self.export_dir, self.root / exporter.TRASH_DIR] + [Path(p) for p in used])

    def on_scanned(self, res):
        if isinstance(res, Exception):
            self.show_setup(f"Errore nella lettura della cartella: {res}")
            return
        self.items = res
        if self.session:
            self.session.close()
            self.session = None
        try:
            self.session = exporter.Session(self.root, self.export_dir, ids=[it.id for it in res])
        except OSError as e:  # salvataggio presente ma illeggibile: non si salva sopra
            self.show_setup(f"Impossibile leggere il lavoro salvato in questa cartella: {e}")
            return
        self.session.save()
        if self.session.corrupt_backup:
            QMessageBox.warning(
                self, APP_TITLE,
                "Il lavoro salvato in questa cartella era danneggiato e non si è potuto leggere.\n"
                f"È stato conservato come:\n{self.session.corrupt_backup}\n\n"
                "Si riparte senza le scelte precedenti. I file in “cancellare” sono ancora lì.")
        self.history.clear()
        self.export_q.submit(exporter.clean_partial, self.export_dir)   # dopo gli export in corso
        self.ready.clear()
        self.review_skipped = False
        if not self.items:
            self.show_setup("Nessuna foto o video trovati in questa cartella.")
            return
        by_id = self._by_id = {it.id: it for it in self.items}
        # copie mai finite (app chiusa o export fallito): si rifanno. Non si cancella nulla.
        pending = self.session.pending_exports(by_id)
        export_warning = ""
        if pending and not exporter.export_reachable(self.export_dir):
            export_warning = (f"⚠ Cartella export non raggiungibile ({self.export_dir}): "
                              f"{len(pending)} copie in sospeso verranno rifatte alla prossima apertura")
            log.warning(export_warning)
            pending = []
        for key in pending:
            d = self.session.decisions[key]
            self.queue_export(by_id[key.split("#")[0]], d.get("frame"), key=key,
                              snapshot=d["choice"] == "snap",
                              with_video=d.get("with_video", False))
        self.idx = self.next_index(-1)
        done = sum(1 for it in self.items if self.session.get(it.id) is not None)
        if export_warning:
            self.status.setStyleSheet("color:#f0b860;")
            self.status.setText(export_warning, ms=0)   # importante: resta finché non si cambia elemento
        elif done:
            self.status.setStyleSheet("color:#7fd19a;")
            self.status.setText(f"Ripreso da dove eri: {done} già decise")
        self.show_item(keep_status=bool(done or export_warning))

    # ------------------------------------------------------------------ navigazione
    def current(self) -> Item | None:
        if self.session and 0 <= self.idx < len(self.items):
            it = self.items[self.idx]
            d = self.session.get(it.id)
            if d and d["choice"] == "trash" and d.get("moved"):
                return self.in_trash(it, d["moved"])  # tornando indietro: si guarda da “cancellare”
            return it
        return None

    def in_trash(self, it: Item, moved: list[list[str]]) -> Item:
        if self._trash_view and self._trash_view[:2] == (it.id, id(moved)):
            return self._trash_view[2]
        where = {Path(a): Path(b) for a, b in moved}
        view = dataclasses.replace(it, **{k: where.get(getattr(it, k), getattr(it, k))
                                          for k in ("image", "raw", "video") if getattr(it, k)})
        self._trash_view = (it.id, id(moved), view)
        return view

    def item_by_id(self, item_id: str) -> Item | None:
        return self._by_id.get(item_id.split("#")[0])

    def visible(self, item: Item) -> bool:
        """Filtro "solo foto": i video normali si nascondono (le Live sono foto)."""
        return not (self.photos_only and item.kind == "video")

    def is_open(self, item: Item) -> bool:
        if not self.visible(item):
            return False
        d = self.session.get(item.id) if self.session else None
        if d is None:
            return True
        return self.review_skipped and d["choice"] == "skip"

    def next_index(self, frm: int) -> int:
        for i in range(frm + 1, len(self.items)):
            if self.is_open(self.items[i]):
                return i
        return len(self.items)

    def show_item(self, keep_status: bool = False):
        self.player.stop()
        self.player.setSource(QUrl())
        self._player_item = None
        self.image_view.zoomed = False  # ogni elemento si apre adattato alla finestra
        if not keep_status:
            self.status.setStyleSheet("")
            self.status.setText("")
        self.scene_mode = False
        self.frame = None
        self._yes_without_preview = None  # SÌ senza anteprima: solo per il DNG mostrato ora
        self.update_counter()
        if self.return_idx is not None and self.idx == self.return_idx:
            self.return_idx = None
            self.btn_return.setVisible(False)
        item = self.current()
        if item is None:
            self.show_end()
            return
        if item.id not in self.ready:
            if all(cloud.is_local(p) for p in item.needed_files()):
                self.ready.add(item.id)
            else:
                self.update_item_labels()
                self.scene_bar.setVisible(False)
                self.show_download(item)
                self.request_ready(item, now=True)   # prima l'elemento corrente…
                self.prefetch()                      # …poi l'anticipo dei successivi
                return
        self.prefetch()
        if item.video and not item.image and item.duration == 0:
            item.set_duration(mp4_duration(item.preview_video))  # LRF: stessa durata, già locale
        self.update_item_labels()
        self.set_buttons_enabled(True)
        if item.is_clip:
            self.scene_bar.setVisible(True)
            if item.id not in self.infos and ("analyze", item.id) not in self.pending:
                self.pending.add(("analyze", item.id))
                self.submit("analyze", item.id, self.analyze, item)
            self.live_view = False
            if item.kind == "live":
                self.show_live_still()
            else:
                self.play(item)
            self.update_scene_controls()
        else:
            self.scene_bar.setVisible(False)
            reader = QImageReader(str(item.image or item.raw))
            reader.setAutoTransform(True)
            img = reader.read()
            if img.isNull() and item.raw and not item.image:  # solo DNG: Qt non legge i RAW
                pil = raw_preview(item.raw)
                if pil is not None:
                    img = pil_to_qimage(pil)
            if img.isNull():
                if item.raw and not item.image:
                    # DNG senza anteprima: si può comunque approvare (si copia l'originale)
                    self._yes_without_preview = item.id
                    self.show_message(f"Anteprima non disponibile per {item.main.name}\n"
                                      "SÌ copia comunque il DNG originale in export.")
                else:
                    self.show_message(f"Impossibile aprire {item.main.name}")
                return
            self.image_view.set_image(img)
            self.still_owner = item.id
            self.stack.setCurrentWidget(self.image_view)

    @staticmethod
    def analyze(item: Item):
        """Analisi sul video leggero (LRF) se l'originale non è sul disco: stessi fotogrammi."""
        src = item.preview_video
        info = frames.probe(src)
        cam = info.frames // 2
        if item.kind == "live":
            cam = frames.camera_frame(src, info, item.screennail)
        if src != item.video:
            info.source = src
            dims = (frames.probe(item.video).width, frames.probe(item.video).height) \
                if cloud.is_local(item.video) else frames.spotlight_dims(item.video)
            info.original_dims = dims
        return info, cam

    def request_ready(self, item: Item, now: bool = True):
        """Scarica i file dell'elemento. now=True: è quello che stai guardando, ha la precedenza
        (pool dedicato); now=False: anticipo dei successivi, max 2 download alla volta."""
        key = ("ready-now" if now else "ready-pre", item.id)
        if key in self.pending:
            return
        self.pending.add(key)
        files = [p for p in item.needed_files() if not cloud.is_local(p)]
        if now:
            def job(files=files, pool=self.dl):
                pairs = [(p, pool.submit(cloud.download, p)) for p in files]
                for p, f in pairs:
                    if not f.result():
                        raise RuntimeError(f"{p.name} non disponibile")
                return True
            self.submit("ready", item.id, job, queue=self.waiters)
        else:
            def job(files=files):
                for p in files:  # uno dopo l'altro: non toglie banda all'elemento corrente
                    if not cloud.download(p):
                        raise RuntimeError(f"{p.name} non disponibile")
                return True
            self.submit("ready", item.id, job, queue=self.pre)

    def prefetch(self):
        i, n = self.idx, 0
        while n < PREFETCH:
            i = self.next_index(i)
            if i >= len(self.items):
                break
            it = self.items[i]
            if it.id not in self.ready and not all(cloud.is_local(p) for p in it.needed_files()):
                self.request_ready(it, now=False)
            n += 1

    def play(self, item: Item):
        self.ensure_player(item)  # sempre l'originale
        live = item.kind == "live"
        self.player.setLoops(QMediaPlayer.Infinite if live else 1)
        self.audio.setMuted(live)
        self.stack.setCurrentWidget(self.video_widget)
        self.player.play()

    def on_player_error(self, *_):
        item = self.current()
        # Riserva: se l'originale non si riesce a riprodurre, si prova l'LRF (solo per guardare)
        if item and item.proxy and cloud.is_local(item.proxy) and not self._playing_proxy:
            log.warning("riproduzione originale non riuscita, uso LRF: %s", item.id)
            self._playing_proxy = True
            self.player.setSource(QUrl.fromLocalFile(str(item.proxy)))
            self.player.play()

    def take_photo(self):
        """Video: salva come foto il fotogramma che vedi e ti ci ferma sopra, così vedi
        esattamente quale è stato salvato. Live: niente foto in più, la foto è quella scelta."""
        item = self.current()
        if not item or not item.is_clip or self.stack.currentWidget() is self.msg_page:
            return
        info = self.infos.get(item.id)
        if not info:
            self.status.setText("Attendi: sto analizzando il video…")
            return
        n = self.current_frame()
        if item.kind == "live":
            if self.live_view:  # durante il video: questo fotogramma diventa la foto
                self.set_frame(n, manual=True)
                self.flash(f"📸 Foto della Live: fotogramma {n + 1}  (SÌ per salvarla)")
            return
        key = f"{item.id}#f{n}"
        if not self.scene_mode:
            self.set_frame(n, manual=True)  # fermo sul fotogramma salvato, esatto
        if self.session.get(key):
            self.flash(f"📷 Fotogramma {n + 1} già salvato")
            return
        self.history.append((self.idx, key, None))
        self.session.set(key, "snap", [], n)
        self.queue_export(item, n, key=key, snapshot=True)
        self.flash(f"📷 Foto salvata: fotogramma {n + 1}  (Z per annullare)")
        self.set_buttons_enabled(True)
        self.update_scene_controls()
        self.btn_undo.setEnabled(True)
        self.update_counter()

    def update_snaps_label(self):
        item = self.current()
        k = len(self.snaps_of(item)) if item and item.is_clip and self.session else 0
        if k:
            self.snaps_label.setText(f"📷  {k} foto salvat{'a' if k == 1 else 'e'} da questo video")
            entries = []
            for key in self.snaps_of(item):
                d = self.session.get(key)
                files = [f for f in d.get("files", []) if Path(f).suffix.lower() in (".jpg", ".png")]
                entries.append((key, d["frame"], files[0] if files else None))
            self.snap_gallery.set_entries(entries, self.snap_gallery.current)
        else:
            self.snaps_label.setText("")
            self.snap_gallery.set_entries([], None)
        self.snaps_label.setProperty("empty", "false" if k else "true")
        self.snaps_label.style().unpolish(self.snaps_label)
        self.snaps_label.style().polish(self.snaps_label)

    def review_snap(self, n: int):
        """Clic su una foto presa: il video si ferma su quel fotogramma, così la rivedi grande."""
        item = self.current()
        if item and item.kind == "video":
            self.set_frame(n, manual=True)

    def remove_snap(self, key: str):
        """✕ su una foto presa: toglie la copia da export (l'originale non si tocca mai)."""
        d = self.session.get(key) if self.session else None
        if not d or d["choice"] != "snap" or not self.revert_effects(key, d):
            return
        self.session.clear(key)
        self.flash(f"Foto tolta: fotogramma {d['frame'] + 1} (F per riprenderla)")
        self.set_buttons_enabled(True)
        self.update_scene_controls()
        self.update_counter()

    def update_save_info(self):
        """Pannello a destra: i progressi sono salvati? quando? dove? e dove vanno le foto."""
        ses = self.session
        if not ses:
            self.save_info.setText("")
            return
        esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace("/", "/\u200b")
        saved = ses.path.exists()
        when = ses.updated[11:19] if saved and len(ses.updated) >= 19 else ""
        day = ses.updated[:10] if saved else ""
        from datetime import date
        if saved and day != date.today().isoformat():
            when = f"{day[8:10]}/{day[5:7]} {when}"
        state = (f"<span style='color:#7fe3b4; font-weight:600'>✓ Progressi salvati</span>"
                 f"<span style='color:#98989f'> · alle {when}</span>" if saved else
                 "<span style='color:#ffb340; font-weight:600'>⚠ Non ancora salvato</span>")
        where = self.short_folder(str(ses.path.parent))
        self.save_info.setText(
            f"{state}<br><span style='color:#98989f'>Si salvano da soli a ogni scelta: puoi chiudere "
            f"quando vuoi e riprendere da qui.</span>"
            f"<table cellspacing='0' style='margin-top:6px'>"
            f"<tr><td style='color:#98989f; padding:2px 10px 2px 0'>Progressi</td>"
            f"<td>{esc(where)}/{esc(ses.path.name)}</td></tr>"
            f"<tr><td style='color:#98989f; padding:2px 10px 2px 0'>Foto scelte</td>"
            f"<td>{esc(self.short_path(self.export_dir))}</td></tr></table>")

    def file_status(self, item: Item, d: dict | None) -> tuple[str, str, list[tuple[str, str]]]:
        """Cosa è successo AI FILE di questo elemento: copiato in export, spostato in “cancellare”,
        o niente. (colore, testo, link "Apri …") per il pannello Info: niente percorsi lunghi."""
        grey = "#98989f"
        if not d:
            return grey, "da decidere · niente copiato né spostato", []
        choice = d["choice"]
        if choice == "no":
            return CHOICE_COLOR["no"], "✗ scartata · niente copiato, l'originale resta al suo posto", []
        if choice == "skip":
            return CHOICE_COLOR["skip"], "↪ saltata · niente copiato né spostato", []
        if choice == "trash":
            moved = [dst for _, dst in d.get("moved", [])]
            return (CHOICE_COLOR["trash"], "🗑 originale SPOSTATO in “cancellare” (Z lo rimette a posto)",
                    self.open_links(moved))
        if choice == "yes" and d.get("noexport"):
            return CHOICE_COLOR["yes"], "✓ approvata · video non copiato (tenute solo le foto prese)", []
        if d.get("export_failed"):
            return ("#ffb340", f"⚠ copia non riuscita: {d['export_failed']}\n"
                               "(si riprova alla prossima apertura)", [])
        files = d.get("files") or []
        if not files:
            return "#ffb340", "⏳ copia in export in corso…", []
        return (CHOICE_COLOR["yes"], "✓ approvata · COPIATA in export (l'originale resta al suo posto)",
                self.open_links(files))

    @staticmethod
    def open_links(files: list[str]) -> list[tuple[str, str]]:
        """Un link per la prima foto e uno per il primo video tra i file indicati."""
        links = []
        for exts, label in ((IMAGE_EXTS, "Apri foto"), (VIDEO_EXTS, "Apri video")):
            f = next((f for f in files if Path(f).suffix.lower() in exts and Path(f).exists()), None)
            if f:
                links.append((label, f))
        return links

    def short_path(self, path) -> str:
        """Percorso leggibile: dentro la cartella aperta come "dji pocket/export", altrove con ~."""
        short = self.short_folder(str(path))
        if short != str(path):
            return short
        home = str(Path.home())
        return "~" + str(path)[len(home):] if str(path).startswith(home) else str(path)

    def save_now(self):
        if not self.session:
            return
        try:
            self.session.save()
        except OSError as e:
            self.status.setStyleSheet("color:#f0b860;")
            self.status.setText(f"Salvataggio non riuscito: {e}")
            return
        self.flash("💾 Progressi salvati")
        self.update_save_info()

    def reveal_session(self):
        if not self.session or not self.session.path.exists():
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(self.session.path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session.path.parent)))

    def flash(self, text: str):
        self.status.setStyleSheet("color:#7fd19a;")
        self.status.setText(text, ms=3500)

    def replay(self):
        item = self.current()
        if not item or not item.is_clip or self.stack.currentWidget() is self.msg_page:
            return
        if item.kind == "live":
            self.live_view = False
            self.toggle_live()
            self.player.setPosition(0)   # "rivedi": sempre dall'inizio
            return
        self.scene_mode = False
        self.ensure_player(item)
        self.stack.setCurrentWidget(self.video_widget)
        self.audio.setMuted(False)
        self.player.setPosition(0)
        self.player.play()
        self.update_scene_controls()

    def on_play_state(self, state):
        playing = state == QMediaPlayer.PlayingState
        self.btn_play.setText("⏸" if playing else "▶")
        self.btn_play.setToolTip("Pausa (barra spaziatrice)" if playing else "Play (barra spaziatrice)")

    def showing_still(self, item: Item) -> bool:
        return item.kind == "live" and not self.live_view

    def show_download(self, item: Item):
        """Attesa del download da iCloud: file, dimensione e secondi trascorsi."""
        log.info("attendo iCloud per %s", item.id)
        self._dl_item, self._dl_start = item.id, time.monotonic()
        self._dl_files = [p for p in item.needed_files() if not cloud.is_local(p)]
        self.show_message("")
        self.set_buttons_enabled(True)
        self.btn_yes.setEnabled(False)          # SÌ solo quando il file è arrivato
        self.btn_yes_video.setEnabled(False)
        self.msg_btn2.setText("↪  Salta questo  (S)")
        self.msg_btn2.clicked.connect(lambda: self.decide("skip"))
        self.msg_btn2.setVisible(True)
        self.update_download_message()
        self.dl_timer.start()

    def update_download_message(self):
        item = self.current()
        if not item or item.id != getattr(self, "_dl_item", None) or item.id in self.ready \
                or self.stack.currentWidget() is not self.msg_page:
            self.dl_timer.stop()
            return
        elapsed = time.monotonic() - self._dl_start
        secs = int(elapsed)
        names = "\n".join(f"{p.name}  ·  {p.stat().st_size / 1e6:.0f} MB" if p.exists() else p.name
                          for p in self._dl_files)
        dots = "." * (secs % 4)
        # percentuale STIMATA dalla velocità dei download già fatti (macOS non la fornisce)
        total_mb = sum(p.stat().st_size for p in self._dl_files if p.exists()) / 1e6
        speed = cloud.estimated_speed()
        expected = max(1.0, total_mb / speed + 2)          # +2 s: avvio del download
        pct = min(95, int(100 * elapsed / expected))
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        left = max(0, int(expected - elapsed))
        eta = f"circa {left} s rimanenti" if left else "quasi finito…"
        if secs and secs % 30 == 0:
            log.info("ancora in attesa di iCloud (%d s) per %s", secs, item.id)
        self.message.setText(
            f"☁️  Scarico da iCloud{dots}\n\n{names}\n\n"
            f"{bar}  ≈ {pct}%\n⏱  {secs} s  ·  {eta}   (stima su {speed:.1f} MB/s)\n"
            "macOS non dice la percentuale vera: la stima usa la velocità dei download già fatti.\n"
            f"I prossimi {PREFETCH} elementi si stanno già scaricando in automatico.\n\n"
            "Intanto puoi premere  S = salta,  N = no,  X = sposta in “cancellare”.")

    def download_next_ten(self):
        nxt, i = [], self.idx
        while len(nxt) < 10:
            i = self.next_index(i)
            if i >= len(self.items):
                break
            nxt.append(self.items[i])
        todo = [p for it in nxt for p in it.needed_files() if not cloud.is_local(p)]
        for p in todo:
            self.dl.submit(cloud.download, p)
        mb = sum(p.stat().st_size for p in todo if p.exists()) / 1e6
        log.info("scarico in anticipo %d file (%.0f MB)", len(todo), mb)
        self.flash(f"☁️ Scarico in anticipo {len(todo)} file ({mb:.0f} MB)")

    def show_live_still(self):
        """Live: si vede la foto (fotogramma della fotocamera o quello scelto), come sull'iPhone."""
        item = self.current()
        if not item:
            return
        self.live_view = False
        self.player.pause()
        info = self.infos.get(item.id)
        if info is None or item.id not in self.camera_frames:
            self.stack.setCurrentWidget(self.image_view)
            self.image_view.set_loading("Carico la foto in 4K…")  # niente anteprime a bassa risoluzione
            return
        self.show_frame(self.live_photo_frame(item), scrub=False)

    def toggle_live(self):
        item = self.current()
        if not item or item.kind != "live" or self.stack.currentWidget() is self.msg_page:
            return
        if self.live_view:
            self.show_live_still()
        else:
            self.live_view = True
            self.play(item)
            self.audio.setMuted(False)
        self.update_scene_controls()

    def play_pause(self):
        item = self.current()
        if not item or not item.is_clip:
            return
        if item.kind == "live":
            self.toggle_live()
        elif self.scene_mode or self.player.playbackState() == QMediaPlayer.PlayingState:
            self.toggle_scene()  # pausa = fermo sul fotogramma esatto; play = riparte da lì
        else:
            self.player.play()

    def update_stamp(self, offset_s: float = 0.0):
        """Data/ora dello scatto (dal nome del file DJI) in alto a sinistra; nei video avanza.
        Su un fotogramma fermo di un video non si mostra: resta solo la foto."""
        item = self.current()
        page = self.stack.currentWidget()
        paused_clip_frame = item is not None and item.kind == "video" and page is self.image_view
        if not item or paused_clip_frame or page not in (self.image_view, self.video_widget):
            self.stamp.hide()
            self.place_zoom()
            return
        from datetime import timedelta
        self.stamp.setText("🕒  " + fmt_datetime(item.taken + timedelta(seconds=offset_s)))
        self.stamp.adjustSize()
        self.stamp.show()
        self.place_stamp()
        self.stamp.raise_()

    def place_stamp(self):
        """La data sta nell'angolo in alto a sinistra DELLA FOTO (o del video), non sul bordo
        scuro accanto: si calcola dove viene disegnata l'immagine adattata alla finestra."""
        if not hasattr(self, "stamp") or self.stamp.isHidden():
            return
        # fissa: sempre nello stesso punto (in alto a sinistra dell'area della foto), anche quando
        # si ingrandisce o si sposta la foto; non segue l'immagine
        area = self.stack.rect()
        x, y = 14, 12
        self.stamp.move(min(x, max(14, area.width() - self.stamp.width() - 14)), y)
        self.place_zoom()
        self.warn.place()

    def place_zoom(self):
        """Cursore dello zoom subito sotto la data, sopra la foto (solo per foto e panorami)."""
        if not hasattr(self, "stamp"):
            return
        item = self.current()
        show = (self.stack.currentWidget() is self.image_view and not self.stamp.isHidden()
                and item is not None and item.kind != "video")   # foto, panorami e Live ferma
        self.zoom_pill.setVisible(show)
        if show:
            self.zoom_pill.adjustSize()
            self.zoom_pill.move(self.stamp.x(), self.stamp.y() + self.stamp.height() + 6)
            self.zoom_pill.raise_()

    def update_item_labels(self):
        item = self.current()
        if not item:
            return
        color = KIND_COLOR[item.kind]
        self.badge.setText(KIND_LABEL[item.kind])
        self.badge.setStyleSheet(f"background:{color}; color:#111; border-radius:8px;"
                                 "font-size:10px; font-weight:800; padding:2px 7px;")
        self.heading.setText(item.main.name)
        t = item.taken
        parts = [f"{t.day} {_MESI_LUNGHI[t.month - 1]} {t.year} alle {t:%H:%M:%S}"]
        warn = []
        info = self.infos.get(item.id)
        dims = None
        if info:
            dims = info.original_dims if info.source else (info.width, info.height)
        if info and dims:
            w_, h_ = dims
            parts.append(f"{w_}×{h_} ({w_ * h_ / 1e6:.1f} MP)")
            if info.source:
                parts.append("anteprima 720p · originale scaricato al SÌ")
            hint = frames.print_hint(w_, h_)
            if hint in ("30×45", "20×30"):
                parts.append(f"stampa fino a {hint}")
            else:
                warn.append(f"⚠ bassa risoluzione: stampa max {hint}")
            if info.is_flat_profile:
                warn.append("⚠ profilo colore piatto (D-Log/HLG)")
        elif info and info.source:
            parts.append("anteprima 720p · originale scaricato al SÌ")
        if item.is_clip and item.duration:
            parts.append(f"{item.duration:.1f} s")
        d = self.session.get(item.id) if self.session else None
        self.show_chosen(d)
        pos, total = self.position()
        self.title.setText(f"{parts[0]}  ·  {pos} di {total}" if total else parts[0])
        self.warn.setText("   ".join(warn))
        self.update_side_info(item, info, parts[1:], warn, d)

    def position(self) -> tuple[int, int]:
        vis = [i for i, it in enumerate(self.items) if self.visible(it)]
        return sum(1 for i in vis if i <= self.idx), len(vis)

    def update_side_info(self, item: Item, info, extra: list[str], warn: list[str], d: dict | None):
        """Pannello Info: giorno, luogo e tutti i metadati che si possono leggere dal file."""
        if item.id not in self.meta and ("meta", item.id) not in self.pending \
                and (not item.is_clip or info is not None) \
                and all(cloud.is_local(p) for p in item.needed_files()):
            self.pending.add(("meta", item.id))
            self.submit("meta", item.id, metadata.read, item, info)
        m = self.meta.get(item.id)
        t = item.taken
        esc = lambda x: (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                         .replace("\n", "<br>").replace("_", "_\u200b").replace("/", "/\u200b"))
        html = [f"<div style='font-size:17px; font-weight:700; color:#f2f2f7'>"
                f"{_GIORNI_LUNGHI[t.weekday()]} {t.day} {_MESI_LUNGHI[t.month - 1]} {t.year}</div>",
                f"<div style='color:#98989f; margin-bottom:8px'>ore {t:%H:%M:%S}</div>"]
        row = ("<tr><td width='78' style='color:#98989f; padding:3px 10px 3px 0; vertical-align:top'>{}</td>"
               "<td style='color:#f2f2f7; padding:3px 0'>{}</td></tr>")
        rows = [("Tipo", KIND_LABEL[item.kind].capitalize())]
        if m and m.gps:
            lat, lon = m.gps
            url = (f"https://maps.apple.com/?ll={lat},{lon}&q={lat},{lon}" if sys.platform == "darwin"
                   else f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=15/{lat}/{lon}")
            place = (esc(metadata.fmt_gps(lat, lon))
                     + (f"<br>altitudine {m.altitude:.0f} m" if m.altitude is not None else "")
                     + f"<br><a style='color:#0a84ff' href='{url}'>Apri nella mappa</a>")
        elif m:
            place = "<span style='color:#8e8e93'>nessuna posizione nel file</span>"
        else:
            place = "<span style='color:#8e8e93'>…</span>"
        html_rows = [row.format("Luogo", place)]
        rows += [(k, v) for k, v in (m.rows if m else [])]
        if not m:
            rows += [("Dettagli", "  ·  ".join(extra))] if extra else []
        else:
            rows += [("Stampa", x) for x in extra if x.startswith("stampa")]
            rows += [("Nota", x) for x in extra if x.startswith("anteprima")]
        if self.session and item.id in self.session.favorites:
            rows.append(("Preferita", "♥ sì"))
        rows = [(k, self.short_folder(v) if k == "Cartella" else v) for k, v in rows]
        html_rows += [row.format(esc(k), esc(v)) for k, v in rows]
        color, status, links = self.file_status(item, d)   # in cima: copiata, spostata o lasciata lì
        link_html = "".join(f"<br><a style='color:#0a84ff' href='{QUrl.fromLocalFile(f).toString()}'>"
                            f"{label}</a>" for label, f in links)
        html_rows.insert(0, row.format("Stato", f"<span style='color:{color}'>{esc(status)}</span>"
                                                + link_html))
        html.append("<table width='100%' cellspacing='0'>" + "".join(html_rows) + "</table>")
        if warn:
            html.append("<div style='color:#ffb340; margin-top:8px'>" + "<br>".join(map(esc, warn))
                        + "</div>")
        self.side_details.setText("".join(html))

    def short_folder(self, folder: str) -> str:
        """Cartella dell'elemento a partire da quella aperta (es. "dji pocket/DCIM/DJI_001"),
        invece del percorso completo che occupa cinque righe nel pannello."""
        try:
            rel = Path(folder).relative_to(self.root)
        except (TypeError, ValueError):
            return folder
        return str(Path(self.root.name) / rel) if str(rel) != "." else self.root.name

    def show_chosen(self, d: dict | None):
        """Elemento già deciso: etichetta colorata grande + pulsante della scelta evidenziato."""
        choice = d["choice"] if d else None
        if choice in CHOICE_NAME:
            self.chosen_tag.setText(f"GIÀ SCELTO  {CHOICE_NAME[choice]}")
            self.chosen_tag.setStyleSheet(f"background:{CHOICE_COLOR[choice]};")
            self.chosen_tag.show()
        else:
            self.chosen_tag.hide()
        for c, b in (("yes", self.btn_yes), ("no", self.btn_no), ("skip", self.btn_skip),
                     ("trash", self.btn_trash)):
            b.setProperty("chosen", "true" if c == choice else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self.btn_trash.refresh_icon()

    def update_counter(self):
        self.update_snaps_label()
        self.update_save_info()
        self.refresh_stamp()
        if not self.session or not self.items:
            self.counter.setText("")
            return
        c = self.session.counts()
        vis = [i for i, it in enumerate(self.items) if self.visible(it)]
        pos = sum(1 for i in vis if i <= self.idx)
        hidden = len(self.items) - len(vis)
        busy = sum(1 for f in self.export_futures.values() if not f.done())
        extra = f"   ⏳ export {busy}" if busy else ""
        if hidden:
            extra += f"   ({hidden} video nascosti)"
        self.update_fav_button()
        self.update_next_preview()
        self.counter.setText(f"Elemento {pos} di {len(vis)}\n"
                             f"✓ {c['yes']} approvate\n✗ {c['no']} scartate\n↪ {c['skip']} saltate"
                             + (f"\n🗑 {c['trash']} in “cancellare”" if c.get("trash") else "")
                             + (f"\n📷 {c['snap']} foto prese dai video" if c.get("snap") else "")
                             + (f"\n{extra.strip()}" if extra else ""))

    def show_message(self, text: str, end: bool = False):
        self.player.stop()
        self.message.setText(text)
        self.stack.setCurrentWidget(self.msg_page)
        self.scene_bar.setVisible(False)
        for b in (self.msg_btn1, self.msg_btn2):
            b.setVisible(False)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    b.clicked.disconnect()
                except (RuntimeError, TypeError):
                    pass
        if end:
            self.msg_btn1.setText("Mostra la cartella export")
            self.msg_btn1.clicked.connect(self.open_export)
            self.msg_btn1.setVisible(True)
            if self.session and self.session.counts()["skip"]:
                self.msg_btn2.setText("↪  Rivedi le saltate")
                self.msg_btn2.clicked.connect(self.review_skips)
                self.msg_btn2.setVisible(True)

    def show_end(self):
        self.show_chosen(None)
        self.badge.setText("")
        self.badge.setStyleSheet("")
        self.heading.setText("")
        self.title.setText("")
        self.side_details.setText("")
        self.warn.setText("")
        self.set_buttons_enabled(False)
        self.btn_undo.setEnabled(bool(self.history))
        c = self.session.counts() if self.session else {"yes": 0, "no": 0, "skip": 0}
        hidden = sum(1 for it in self.items if not self.visible(it)
                     and not (self.session and self.session.get(it.id)))
        # arrivati in fondo saltando avanti (miniature, ↓): prima restano elementi da decidere
        left = sum(1 for it in self.items if self.is_open(it))
        head = (f"Sei in fondo, ma {'manca' if left == 1 else 'mancano'} {left} "
                f"element{'o' if left == 1 else 'i'} da decidere più indietro." if left else "Finito!")
        self.show_message(f"{head}\n\n✓ {c['yes']} approvate    ✗ {c['no']} scartate    "
                          f"↪ {c['skip']} saltate"
                          + (f"\n\n🎬 {hidden} video nascosti dal filtro “solo foto”" if hidden else "")
                          + "\n\n↑ = torna indietro a rivedere", end=True)
        if left:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    self.msg_btn2.clicked.disconnect()   # al posto di "Rivedi le saltate"
                except (RuntimeError, TypeError):
                    pass
            self.msg_btn2.setText("→  Vai al primo da decidere")
            self.msg_btn2.clicked.connect(self.go_first_open)
            self.msg_btn2.setVisible(True)

    def go_first_open(self):
        self.idx = self.next_index(-1)
        self.show_item()

    def review_skips(self):
        self.review_skipped = True
        self.idx = self.next_index(-1)
        self.show_item()

    def set_buttons_enabled(self, on: bool):
        for b in (self.btn_no, self.btn_skip, self.btn_yes, self.btn_trash):
            b.setEnabled(on)
        item = self.current()
        self.btn_yes_video.setEnabled(on and item is not None and (
            item.kind == "live" or (item.kind == "photo" and item.video is not None)
            or (item.kind == "video" and bool(self.snaps_of(item)))))
        # video: le etichette dicono cosa succede davvero (Sì cambia se hai già preso delle foto)
        snaps = item is not None and item.kind == "video" and bool(self.snaps_of(item))
        yes, both = (("Tieni le foto (Y)", "Foto + video (⇧Y)") if snaps
                     else ("Salva video (Y)", "Sì + video (⇧Y)") if item is not None and item.kind == "video"
                     else ("Sì (Y)", "Sì + video (⇧Y)"))
        self.choice_caps["yes"].setText(yes)
        self.choice_caps["yesvideo"].setText(both)
        for name, cap in (("yes", yes), ("yesvideo", both)):
            getattr(self, "btn_yes" if name == "yes" else "btn_yes_video").setAccessibleName(
                cap.replace(" (", ", tasto ").rstrip(")"))

    def snaps_of(self, item: Item) -> list[str]:
        """Foto già prese da questo video con 📷 Prendi foto."""
        if not self.session:
            return []
        prefix = item.id + "#f"
        return [k for k, d in self.session.decisions.items()
                if k.startswith(prefix) and d["choice"] == "snap"]

    # ------------------------------------------------------------------ scena
    # Live: si vede la FOTO (fotogramma della fotocamera o quello scelto sulla striscia, come in
    # Foto di macOS); "Vedi Live" fa partire il video. SÌ salva la foto scelta.
    # Video: si vede il video; clic sulla striscia, frecce o pausa = fermo sul fotogramma esatto
    # (scene_mode), da salvare con 📷 Prendi foto.
    def update_scene_controls(self):
        item = self.current()
        info = self.infos.get(item.id) if item else None
        clip = bool(item) and item.is_clip
        live = clip and item.kind == "live"
        for w in (self.btn_play, self.btn_prev, self.strip, self.btn_next, self.time_label):
            w.setVisible(clip)
        self.btn_live.setVisible(live)
        self.btn_live.setText("🖼  Torna alla foto (L)" if self.live_view else "▶  Vedi Live (L)")
        self.btn_replay.setVisible(clip and not live)
        self.btn_snap.setVisible(clip and not live)
        self.btn_sharp.setVisible(clip and info is not None and (live or self.scene_mode))
        self.btn_reset.setVisible(live and self.frame is not None)
        if not clip:
            return
        self.update_strip()
        if info is None:
            self.frame_label.setText("analisi del video…")
            return
        if live:
            n = self.live_photo_frame(item)
            who = "scelta da te" if self.frame is not None else "della fotocamera"
            self.frame_label.setText(
                f"📸 Foto: fotogramma {n + 1} / {info.frames} ({who})  ·  "
                + ("trascina sulla striscia per sceglierne un'altra" if self.live_view else
                   "trascina sulla striscia o usa ← → per cambiarla  ·  SÌ salva questa"))
            self.update_time_label(n, info)
            return
        if self.scene_mode:
            saved = bool(self.session) and f"{item.id}#f{self.shown_frame}" in self.session.decisions
            self.frame_label.setText(
                f"Fotogramma {self.shown_frame + 1} / {info.frames}  ·  "
                + ("✓ già salvato come foto" if saved else "📷 F = salva questo fotogramma come foto"))
            self.update_time_label(self.shown_frame, info)
        else:
            k = len(self.snaps_of(item))
            self.frame_label.setText(
                f"📷 {k} foto prese (segni verdi)  ·  SÌ = tieni solo le foto  ·  ＋ SÌ e video = anche il video"
                if k else "Clic sulla striscia per fermarti su un fotogramma  ·  SÌ = copia il video in export/Video")

    def live_photo_frame(self, item: Item) -> int:
        """Il fotogramma che SÌ salverà come foto della Live."""
        info = self.infos.get(item.id)
        if self.frame is not None:
            return self.frame
        return self.camera_frames.get(item.id, info.frames // 2 if info else 0)

    def update_strip(self):
        item = self.current()
        info = self.infos.get(item.id) if item else None
        if not item or not item.is_clip or info is None:
            self.strip.set_video(0)
            return
        if self.strip.owner != item.id:
            self.strip.set_video(info.frames, item.id)
            if item.id in self.thumbs:
                self.strip.set_thumbs(self.thumbs[item.id])
            elif ("strip", item.id) not in self.pending:
                self.pending.add(("strip", item.id))
                self.submit("strip", item.id, self.make_strip, item, info)
        if item.kind == "live":
            # durante il video della Live non c'è una foto "scelta" da evidenziare: la striscia
            # mostra la linea del punto in cui è il video (playhead), come in Foto
            sel = None if self.live_view else self.shown_frame
        else:
            sel = self.shown_frame if self.scene_mode else None
        marks = [self.session.get(k)["frame"] for k in self.snaps_of(item)] \
            if item.kind == "video" and self.session else []
        original = self.camera_frames.get(item.id) if item.kind == "live" else None
        self.strip.set_state(sel, marks, original)
        self.snap_gallery.current = sel if item.kind == "video" else None
        self.snap_gallery.update()

    @staticmethod
    def make_strip(item: Item, info: frames.VideoInfo) -> list[QImage]:
        # l'anteprima .LRF (720p) è molto più veloce da leggere, con gli stessi fotogrammi
        src = item.proxy if item.proxy and cloud.is_local(item.proxy) else (info.source or item.video)
        return [pil_to_qimage(im) for im in frames.strip_thumbs(src, info, height=128)]  # nitide anche su Retina

    @staticmethod
    def frame_ms(info: frames.VideoInfo, n: int) -> int:
        """Posizione del lettore (ms) che mostra il fotogramma n."""
        return math.ceil(Fraction(n * 1000) / info.fps) + 1

    def ensure_player(self, item: Item):
        if self._player_item != item.id:
            self._playing_proxy = False
            self.player.setSource(QUrl.fromLocalFile(str(item.video)))
            self._player_item = item.id

    def show_frame(self, n: int, scrub: bool):
        """Mostra il fotogramma n. Mentre si scorre (scrub) si vede subito quello del lettore video,
        poi arriva quello esatto a risoluzione piena; l'etichetta dice sempre quale è."""
        item = self.current()
        info = self.infos.get(item.id) if item else None
        if not info:
            return
        n = max(0, min(info.frames - 1, n))
        self.shown_frame = n
        img = self.exact_cache.get((item.id, n))
        # il fotogramma a schermo resta della STESSA misura: se è già una foto di questo elemento,
        # non si passa al lettore video né si scrive "Carico": si aspetta quello esatto
        same_item_on_screen = self.still_owner == item.id and not self.image_view.full.isNull()
        if img is not None:
            self.image_view.set_image(img, keep_zoom=True)
            self.still_owner = item.id
            self.stack.setCurrentWidget(self.image_view)
        elif scrub and not self.image_view.zoomed and not same_item_on_screen:
            self.ensure_player(item)
            self.player.pause()
            self.player.setPosition(self.frame_ms(info, n))
            self.stack.setCurrentWidget(self.video_widget)
            self.preview_timer.start()
        else:
            if not scrub and not same_item_on_screen:
                self.image_view.set_loading("Carico la foto in 4K…")  # niente anteprime sfocate
            self.stack.setCurrentWidget(self.image_view)
            self.preview_timer.start()
        self.update_scene_controls()
        self.refresh_stamp()

    def request_preview(self):
        """Fotogramma esatto a risoluzione piena: uno alla volta, sempre l'ultimo richiesto."""
        item = self.current()
        info = self.infos.get(item.id) if item else None
        if not info or not (self.scene_mode or self.showing_still(item)):
            return
        key = (item.id, self.shown_frame)
        if key in self.exact_cache:
            return
        if self._preview_busy:
            self._preview_again = True
            return
        self._preview_busy = True
        self.submit("preview", key, frames.frame_rgb, info.source or item.video, info, self.shown_frame)

    def on_preview(self, key, res):
        self._preview_busy = False
        cur = self.current() if self.stack.currentWidget() is not self.setup_page else None
        if not isinstance(res, Exception):
            img = pil_to_qimage(res)
            self.exact_cache[key] = img
            while len(self.exact_cache) > 4:  # 4K = ~25 MB l'una
                self.exact_cache.pop(next(iter(self.exact_cache)))
            item_id, n = key
            if cur and cur.id == item_id and n == self.shown_frame \
                    and (self.scene_mode or self.showing_still(cur)):
                self.image_view.set_image(img, keep_zoom=True)
                self.still_owner = item_id
                self.stack.setCurrentWidget(self.image_view)
        if self._preview_again:
            self._preview_again = False
            self.request_preview()

    def set_frame(self, n: int, manual: bool):
        item = self.current()
        info = self.infos.get(item.id) if item else None
        if not info or not item.is_clip or self.stack.currentWidget() is self.msg_page:
            return
        n = max(0, min(info.frames - 1, n))
        if item.kind == "live":
            self.live_view = False  # si torna alla foto: quella scelta
        else:
            self.scene_mode = True
        if manual:
            self.frame = n
        self.player.pause()
        self.show_frame(n, scrub=True)

    def current_frame(self) -> int | None:
        """Il fotogramma che si sta guardando (fermo o durante la riproduzione)."""
        item = self.current()
        info = self.infos.get(item.id) if item else None
        if not info:
            return None
        if self.scene_mode or self.showing_still(item):
            return self.shown_frame
        return info.frame_at(self.player.position() / 1000)

    def on_strip_picked(self, n: int):
        self.set_frame(n, manual=True)

    def step(self, delta: int):
        n = self.current_frame()  # parte da dove sei, non dal centro del video
        if n is not None:
            self.set_frame(n + delta, manual=True)

    def toggle_scene(self):
        """Video: ferma sul fotogramma esatto / riprende da lì. Live: foto / video."""
        item = self.current()
        if not item or not item.is_clip or self.stack.currentWidget() is self.msg_page:
            return
        if item.kind == "live":
            self.toggle_live()
            return
        info = self.infos.get(item.id)
        if not self.scene_mode:
            n = self.current_frame()
            if n is not None:
                self.set_frame(n, manual=True)
            else:
                self.player.pause()
            return
        self.scene_mode = False
        self.ensure_player(item)
        if info:
            self.player.setPosition(self.frame_ms(info, self.shown_frame))
        self.stack.setCurrentWidget(self.video_widget)
        self.player.play()
        self.update_scene_controls()

    def on_position(self, ms: int):
        """Durante la riproduzione la striscia e l'ora seguono il video."""
        item = self.current()
        info = self.infos.get(item.id) if item else None
        if info is None or self.scene_mode or self.showing_still(item) \
                or self.stack.currentWidget() is not self.video_widget:
            return
        n = info.frame_at(ms / 1000)
        self.update_stamp(ms / 1000)
        self.strip.set_playhead(n)
        if item.kind != "live":
            self.update_time_label(n, info)

    def refresh_stamp(self):
        item = self.current()
        info = self.infos.get(item.id) if item else None
        if item and item.is_clip and info:
            if self.stack.currentWidget() is self.video_widget and not self.scene_mode \
                    and not self.showing_still(item):
                self.update_stamp(self.player.position() / 1000)
            else:
                self.update_stamp(float(self.shown_frame / info.fps))
        else:
            self.update_stamp()

    def update_time_label(self, n: int, info):
        t, total = float(n / info.fps), info.duration
        self.time_label.setText(f"{int(t // 60)}:{t % 60:05.2f} / {int(total // 60)}:{total % 60:05.2f}")

    def reset_frame(self):
        item = self.current()
        info = self.infos.get(item.id) if item else None
        if not info or item.kind != "live":
            return
        self.frame = None
        self.set_frame(self.camera_frames.get(item.id, info.frames // 2), manual=False)

    def pick_sharpest(self):
        item = self.current()
        info = self.infos.get(item.id) if item else None
        n = self.current_frame()
        if info and n is not None:
            self.frame_label.setText("cerco il fotogramma più nitido…")
            self.submit("sharpest", item.id, frames.sharpest_near, info.source or item.video, info, n)

    # ------------------------------------------------------------------ filtro, indietro, preferite
    def on_filter_changed(self):
        self.photos_only = self.view_filter.currentIndex() == 1
        self.settings_store.setValue("filter", "photos" if self.photos_only else "all")
        if not self.session or not self.items:
            return
        cur = self.current()
        if cur is None or not self.visible(cur):
            i = self.next_index(self.idx)
            self.idx = i if i < len(self.items) else self.next_index(-1)
        self.show_item()

    def go_back(self):
        if not self.session or not self.items or self.stack.currentWidget() is self.setup_page:
            return
        i = min(self.idx, len(self.items)) - 1
        while i >= 0 and not self.visible(self.items[i]):
            i -= 1
        if i < 0:
            self.flash("Sei al primo elemento")
            return
        if self.return_idx is None:
            self.return_idx = self.idx   # la foto da cui si è tornati indietro
            self.btn_return.setVisible(True)
        self.idx = i
        self.show_item()

    def locate_thumb(self):
        """Torna alla prima foto ancora da decidere (la prossima da giudicare)."""
        if not self.session or not self.items:
            return
        self.thumbs_strip.recenter()
        i = self.next_index(-1)
        if i >= len(self.items):
            # Tutte decise: resta dove sei
            return
        self.idx = i
        self.show_item()

    def scroll_thumbs(self, step: int):
        """Sposta la striscia di qualche miniatura, avanti (+1) o indietro (-1)."""
        self.thumbs_strip.nudge(-step * 3 * (ThumbStrip.CELL_W + ThumbStrip.GAP))

    def return_to_last(self):
        if self.return_idx is None or not self.session or not self.items:
            return
        i, self.return_idx = self.return_idx, None
        if 0 <= i < len(self.items):
            self.idx = i
            self.show_item()
        self.btn_return.setVisible(False)

    def go_forward(self):
        if not self.session or not self.items or self.stack.currentWidget() is self.setup_page:
            return
        i = self.idx + 1
        while i < len(self.items) and not self.visible(self.items[i]):
            i += 1
        self.idx = min(i, len(self.items))
        self.show_item()

    def toggle_favorite(self):
        item = self.current()
        if not item or not self.session or self.stack.currentWidget() is self.setup_page:
            return
        on = self.session.toggle_favorite(item.id)
        d = self.session.get(item.id)
        if d and d["choice"] == "yes" and not d.get("noexport"):
            # già approvata: le copie si spostano tra export ed export/Preferite (mai sovrascritte)
            fav = self.export_dir / exporter.FAV_SUBDIR
            old_root, new_root = (self.export_dir, fav) if on else (fav, self.export_dir)
            fut = self.export_futures.get(item.id)

            def job(fut=fut, files=list(d["files"]), item_id=item.id):
                files = self.copy_paths.get(item_id) or files
                if not files and fut is not None:
                    try:
                        files = [str(p) for p in fut.result()]
                    except Exception:  # noqa: BLE001 - export fallito: niente da spostare
                        return []
                todo = [f for f in files if fav not in Path(f).parents] if on else files  # già lì: restano
                pairs = exporter.relocate_exports(todo, old_root, new_root)
                moved = {a: b for a, b in pairs}
                self.copy_paths[item_id] = [moved.get(f, f) for f in files]
                return pairs
            self.submit("relocate", (item.id, d.get("export_id")), job, queue=self.export_q)
        self.flash("♥ Preferita: le copie vanno in export/Preferite" if on else "Preferita tolta")
        self.update_fav_button()

    def update_fav_button(self):
        item = self.current()
        on = bool(item and self.session and item.id in self.session.favorites)
        self.btn_fav.setText("♥" if on else "♡")
        self.btn_fav.setProperty("on", "true" if on else "false")
        self.btn_fav.style().unpolish(self.btn_fav)
        self.btn_fav.style().polish(self.btn_fav)

    def jump_to(self, i: int):
        """Clic su una miniatura: vai a quell'elemento (anche se già deciso, come ↑ / ↓)."""
        if not self.session or not (0 <= i < len(self.items)) or i == self.idx \
                or self.stack.currentWidget() is self.setup_page:
            return
        self.idx = i
        self.show_item()

    def _show_strip_filter_popup(self):
        """Apre il popup del filtro della striscia, sopra al pulsante."""
        pop = self._strip_filter_pop
        pop.adjustSize()
        btn = self.strip_filter_btn
        pos = btn.mapToGlobal(btn.rect().topLeft())
        pop.move(pos.x(), pos.y() - pop.height() - 4)
        pop.show()

    def _pick_strip_filter(self, key: str, label: str):
        """Seleziona un filtro dal popup."""
        self._strip_filter_key = key
        self._strip_filter_label = label
        self.strip_filter_btn.setText(label + "  ▾")
        self._strip_filter_pop.hide()
        self._update_strip_filter_highlight()
        self.on_strip_filter()

    def _update_strip_filter_highlight(self):
        """Evidenzia la voce selezionata nel popup del filtro."""
        for fb, key in self._strip_filter_btns:
            if key == self._strip_filter_key:
                fb.setStyleSheet("background: #0a84ff; color: #ffffff; font-weight: 600;")
            else:
                fb.setStyleSheet("")

    def on_strip_filter(self):
        self.settings_store.setValue("strip_filter", self._strip_filter_key)
        self.update_thumb_strip()

    def update_thumb_strip(self):
        """Miniature degli elementi prima e dopo quello attuale (solo quelli visibili col filtro)."""
        if not self.session or not self.items:
            self.thumbs_strip.set_entries([], None)
            return
        want = self.strip_filter.currentData()
        def keep(i: int, it: Item) -> bool:
            if want == "all" or i == self.idx:   # quella attuale resta sempre
                return True
            d = self.session.get(it.id)
            if want == "todo":
                return d is None
            if want == "done":
                return d is not None
            return d is not None and d["choice"] == want
        vis = [i for i, it in enumerate(self.items) if self.visible(it) and keep(i, it)]
        here = next((k for k, i in enumerate(vis) if i >= self.idx), len(vis))
        span = 12
        chosen = vis[max(0, here - span): here + span + 1]
        entries = []
        for i in chosen:
            it = self.items[i]
            d = self.session.get(it.id)
            img = self.next_thumbs.get(it.id)
            if img is None and ("thumb", it.id) not in self.pending \
                    and all(cloud.is_local(p) for p in it.needed_files()):
                self.pending.add(("thumb", it.id))
                self.submit("thumb", it.id, self.make_thumb, it)
            entries.append((i, img, d["choice"] if d else None, it.is_clip, it.main.name))
        self.thumbs_strip.set_entries(entries, self.idx if self.idx < len(self.items) else None)

    def update_next_preview(self):
        """In basso: miniature prima e dopo (prima era un riquadro con il solo successivo)."""
        self.update_thumb_strip()
        if True:  # il vecchio riquadro "Dopo" resta nascosto
            self.next_box.hide()
            return
        if not self.session or not self.items or self.stack.currentWidget() is self.setup_page:
            self.next_box.hide()
            return
        self.next_box.show()
        i = self.next_index(self.idx)
        if i >= len(self.items):
            self.next_txt.setText("Dopo:  fine 🎉")
            self.next_img.setPixmap(QPixmap())
            self.next_img.setText("")
            return
        it = self.items[i]
        self.next_txt.setText(f"Dopo ▸  {KIND_LABEL[it.kind]}" + (f"  ·  {it.duration:.0f} s" if
                                                                   it.kind == "video" and it.duration else ""))
        img = self.next_thumbs.get(it.id)
        if img is not None and not img.isNull():
            pm = QPixmap.fromImage(img)
            dpr = self.devicePixelRatioF()
            box = self.next_img.size()
            pm = pm.scaled(int(box.width() * dpr), int(box.height() * dpr), Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self.next_img.setPixmap(pm)
            return
        self.next_img.setPixmap(QPixmap())
        if img is not None:
            self.next_img.setText(it.main.name)
        elif all(cloud.is_local(p) for p in it.needed_files()):
            self.next_img.setText("…")
            if ("thumb", it.id) not in self.pending:
                self.pending.add(("thumb", it.id))
                self.submit("thumb", it.id, self.make_thumb, it)
        else:
            self.next_img.setText("☁️ in download")

    @staticmethod
    def make_thumb(item: Item) -> QImage:
        if item.is_clip:
            if item.screennail and cloud.is_local(item.screennail):
                img = QImageReader(str(item.screennail)).read()
                if not img.isNull():
                    return img
            src = item.proxy if item.proxy and cloud.is_local(item.proxy) else item.video
            ims = frames.strip_thumbs(src, frames.probe(src), count=1, height=208)
            return pil_to_qimage(ims[0]) if ims else QImage()
        r = QImageReader(str(item.image or item.raw))
        r.setAutoTransform(True)
        size = r.size()
        if size.isValid():
            r.setScaledSize(size.scaled(368, 208, Qt.KeepAspectRatio))
        img = r.read()
        if img.isNull() and item.raw:
            pil = raw_preview(item.raw)
            if pil is not None:
                pil.thumbnail((368, 208))
                img = pil_to_qimage(pil)
        return img

    # ------------------------------------------------------------------ decisioni
    def decide(self, choice: str, with_video: bool = False):
        item = self.current()
        if item:
            log.info("scelta %s%s su %s", choice, " +video" if with_video else "", item.id)
        if not item or self.stack.currentWidget() is self.setup_page:
            return
        # Se l'elemento non si apre (o si sta scaricando) si può comunque dire NO / Salta / X
        if self.stack.currentWidget() is self.msg_page and choice == "yes" \
                and self._yes_without_preview != item.id:
            return
        now = time.monotonic()
        if now - self._last_decision < 0.25:  # doppio tocco involontario
            return
        self._last_decision = now
        snaps = self.snaps_of(item) if item.kind == "video" else []
        with_video = with_video and (item.kind == "live" or bool(snaps)
                                     or (item.kind == "photo" and item.video is not None))
        prev = self.session.get(item.id)
        if prev is not None:  # tornati indietro: la nuova scelta sostituisce la vecchia
            new_frame = None
            if choice == "yes" and item.kind == "live":
                new_frame = self.live_photo_frame(item)
            elif choice == "yes" and item.kind != "video":
                new_frame = self.frame
            same = prev["choice"] == choice and (
                choice != "yes" or (prev.get("frame") == new_frame
                                    and prev.get("with_video", False) == with_video))
            if same:  # niente da cambiare: si va avanti
                self.idx = self.next_index(self.idx)
                self.show_item()
                self.flash(f"Scelta confermata: {CHOICE_NAME.get(choice, choice)}")
                return
            if not self.revert_effects(item.id, prev):
                return
            item = self.items[self.idx]  # di nuovo al suo posto
        self.history.append((self.idx, item.id, prev))
        changed = f"{CHOICE_NAME.get(prev['choice'], prev['choice'])}  →  {CHOICE_NAME.get(choice, choice)}" \
            if prev is not None else ""
        frame = None
        if choice == "yes" and item.kind == "video":
            # Con foto prese: SÌ = tieni solo le foto, "SÌ + video" = copia anche il video.
            # Senza foto prese: SÌ = copia il video.
            self.session.set(item.id, "yes", [], None, with_video)
            if with_video or not snaps:
                self.queue_export(item, None)
            else:  # tiene solo le foto già prese: niente da copiare (né ora né alla ripresa)
                self.session.decisions[item.id]["noexport"] = True
                self.session.save()
        elif choice == "yes":
            frame = self.frame
            if frame is None and item.kind == "live":
                frame = self.camera_frames.get(item.id)
            self.session.set(item.id, "yes", [], frame, with_video)
            self.queue_export(item, frame, with_video=with_video)
        elif choice == "trash":
            self.player.stop()
            self.player.setSource(QUrl())  # rilascia il file prima di spostarlo
            self._player_item = None
            try:
                moved = exporter.move_to_trash(item, self.root)  # tutto o niente
            except (OSError, ValueError) as e:
                self.history.pop()
                self.status.setStyleSheet("")
                self.status.setText(f"Spostamento non riuscito: {e}")
                self.show_item(keep_status=True)
                return
            self.session.set(item.id, "trash", moved=moved)
        else:
            self.session.set(item.id, choice)
        self.idx = self.next_index(self.idx)
        self.show_item()
        if changed:  # tornati indietro e cambiata idea: si dice chiaramente cosa è successo
            self.flash(f"Scelta cambiata: {changed}   (Z annulla)")

    def queue_export(self, item: Item, frame: int | None, key: str | None = None,
                     snapshot: bool = False, with_video: bool = False):
        key = key or item.id
        token = uuid.uuid4().hex  # lega l'esito a questa decisione (vedi on_done)
        self.session.mark_export(key, token)
        dest = self.export_dir
        if key == item.id and item.id in self.session.favorites:
            dest = self.export_dir / exporter.FAV_SUBDIR
        self.export_q.submit(self.copy_paths.pop, key, None)   # copia nuova: posizioni vecchie non valgono
        fut = self.submit("export", (key, frame, token), exporter.export_item, item, frame,
                          dest, self.current_settings(with_video), snapshot,
                          queue=self.export_q)
        self.export_futures[key] = fut

    def revert_effects(self, item_id: str, d: dict) -> bool:
        """Toglie gli effetti di una scelta: rimette a posto i file in “cancellare” o toglie le copie
        fatte in export. False = non riuscito (la scelta resta com'è)."""
        if d["choice"] == "trash":
            self.player.stop()
            self.player.setSource(QUrl())  # rilascia il file prima di spostarlo
            self._player_item = None
            try:
                new_names: dict[Path, Path] = {}
                renamed = exporter.restore_from_trash(d.get("moved", []), new_names)
            except OSError as e:
                self.status.setStyleSheet("")
                self.status.setText(f"Ripristino da “cancellare” non riuscito: {e} (riprova)")
                return False
            item = self.item_by_id(item_id)
            if item and new_names:   # l'elemento ora è il file rinominato, non quello che occupa il posto
                for attr in ("image", "raw", "video"):
                    p = getattr(item, attr)
                    if p is not None and p in new_names:
                        setattr(item, attr, new_names[p])
            if renamed:
                QMessageBox.information(
                    self, APP_TITLE, "Al posto originale c'era già un file con lo stesso nome: "
                    "nessuno è stato sovrascritto. Ripristinati come:\n"
                    + "\n".join(str(p) for p in renamed))
        elif d["choice"] in ("yes", "snap"):
            fut = self.export_futures.pop(item_id, None)

            def remove(fut=fut, files=list(d["files"]), stamps=d.get("stamps")):
                files = self.copy_paths.pop(item_id, None) or files   # dopo un ♥: i percorsi nuovi
                if not files and fut is not None:
                    try:
                        files = [str(p) for p in fut.result()]
                    except Exception:  # noqa: BLE001 - export fallito: niente da togliere
                        files = []
                exporter.remove_files(files, stamps)  # solo copie in export, mai originali
            self.export_q.submit(remove)  # in coda dopo l'export: toglie i file giusti
        return True

    def reapply(self, item_id: str, d: dict | None) -> None:
        """Annulla: rimette la scelta di prima con i suoi effetti (file spostati o copiati)."""
        if d is None:
            self.session.clear(item_id)
            return
        item = self.item_by_id(item_id)
        if d["choice"] == "trash" and item:
            self.player.stop()
            self.player.setSource(QUrl())
            self._player_item = None
            try:
                d = {**d, "moved": exporter.move_to_trash(item, self.root)}
            except (OSError, ValueError) as e:
                self.status.setText(f"Spostamento non riuscito: {e}")
                self.session.clear(item_id)
                return
        self.session.decisions[item_id] = d
        self.session.save()
        if d["choice"] == "yes" and not d.get("noexport") and item and "#" not in item_id:
            d["files"] = []
            self.queue_export(item, d.get("frame"), with_video=d.get("with_video", False))

    def undo(self):
        if not self.history or not self.session or self.stack.currentWidget() is self.setup_page:
            return
        idx, item_id, prev = self.history[-1]
        cur = self.session.get(item_id)
        if cur and not self.revert_effects(item_id, cur):
            return  # non riuscito: la scelta e l'annullamento restano
        self.history.pop()
        self.reapply(item_id, prev)
        self.idx = idx
        if cur and cur["choice"] == "snap" and self.current() and self.idx == idx \
                and self.stack.currentWidget() is not self.msg_page \
                and item_id.split("#")[0] == self.current().id:
            self.flash("Foto annullata")
            self.set_buttons_enabled(True)
            self.update_scene_controls()
            self.update_counter()
            return
        self.show_item()

    EXIT_WAIT_S = 30

    def mousePressEvent(self, e):
        """Barra in alto senza titolo: trascinando lo spazio vuoto si sposta la finestra."""
        if self.unified and e.button() == Qt.LeftButton and e.position().y() < 52:
            self.windowHandle().startSystemMove()
            return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.unified and e.position().y() < 52:  # doppio clic sulla barra = ingrandisci
            self.showNormal() if self.isMaximized() else self.showMaximized()
            return
        super().mouseDoubleClickEvent(e)

    def closeEvent(self, e):
        """Uscita: si aspettano (max 30 s) solo le copie verso l'export; i download iCloud
        in anticipo e le analisi vengono abbandonati. Le copie non finite si rifanno alla ripresa."""
        self.player.stop()
        self.dl_timer.stop()
        pending = [f for f in self.export_futures.values() if not f.done()]
        # segnaposto in fondo alla coda (un solo thread): quando è fatto sono finiti anche gli
        # annullamenti e gli spostamenti in Preferite, non solo le copie
        try:
            barrier = self.export_q.submit(lambda: None)
        except RuntimeError:   # coda già chiusa (seconda chiusura)
            barrier = Future()
            barrier.set_result(None)
        if not barrier.done():
            log.info("uscita: attendo %d export in corso", len(pending))
            end = time.monotonic() + self.EXIT_WAIT_S
            while time.monotonic() < end and not barrier.done():
                left = max(1, sum(1 for f in pending if not f.done()))
                self.show_message(f"Completo gli export in corso… ({left})\n\n"
                                  "Le copie non finite verranno rifatte alla prossima apertura.")
                QApplication.processEvents()
                time.sleep(0.05)
        for ex in (self.bg, self.dl, self.pre, self.waiters, self.export_q):
            ex.shutdown(wait=False, cancel_futures=True)
        if self.session:
            self.session.close()
        log.info("uscita")
        super().closeEvent(e)


def selftest(root: Path, out: Path) -> int:
    """Autodiagnosi senza finestra (per provare l'app impacchettata): scan + export + controlli."""
    from PIL import Image
    from PIL.JpegImagePlugin import get_sampling
    print(APP_TITLE, "| ffmpeg:", frames.ffmpeg_exe())
    items = scan(root, [out])
    print("elementi:", len(items), {k: sum(1 for i in items if i.kind == k) for k in KIND_LABEL})
    ok = True
    for kind in ("photo", "live"):
        it = next((i for i in items if i.kind == kind), None)
        if not it:
            continue
        files = exporter.export_item(it, None, out, exporter.Settings())
        for f in files:
            if f.suffix.lower() == ".jpg" and kind == "live":
                im = Image.open(f)
                good = get_sampling(im) == 0 and bool(im.info.get("icc_profile"))
                ok &= good
                print(kind, f.name, im.size, "4:4:4+sRGB" if good else "ERRORE qualità")
            else:
                same = f.read_bytes() == (it.image or it.video).read_bytes()
                ok &= same
                print(kind, f.name, "copia identica" if same else "ERRORE copia")
    print("ESITO:", "OK" if ok else "ERRORE")
    return 0 if ok else 1


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":
        sys.exit(selftest(Path(sys.argv[2]), Path(sys.argv[3])))
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoSwipe")
    if hasattr(app.styleHints(), "setColorScheme"):
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)  # finestre di sistema scure
    if sys.platform != "darwin":
        # Windows/Linux: Fusion scuro, così finestre di dialogo e menu non restano chiari
        app.setStyle("Fusion")
        pal = QPalette()
        for role, col in ((QPalette.Window, "#1c1c1e"), (QPalette.WindowText, "#f2f2f7"),
                          (QPalette.Base, "#2c2c2e"), (QPalette.AlternateBase, "#232325"),
                          (QPalette.Text, "#f2f2f7"), (QPalette.Button, "#2c2c2e"),
                          (QPalette.ButtonText, "#f2f2f7"), (QPalette.Highlight, "#0a84ff"),
                          (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#2c2c2e"),
                          (QPalette.ToolTipText, "#f2f2f7")):
            pal.setColor(role, QColor(col))
        app.setPalette(pal)
    app.setStyle(TipStyle(app.style()))  # stile di base invariato, solo i tempi dei suggerimenti
    app.setStyleSheet(STYLE.replace("__CHEVRON__", chevron_file()))
    w = MainWindow()
    avail = w.screen().availableGeometry()  # schermi piccoli o scalati al 125-150%
    w.resize(min(w.width(), avail.width() - 40), min(w.height(), avail.height() - 40))
    w.show()
    if len(sys.argv) > 1:  # cartella passata da riga di comando
        w.root = Path(sys.argv[1])
        w.export_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else w.root / "export"
        problem = exporter.export_dir_problem(w.root, w.export_dir)
        if problem:   # come dalla schermata iniziale: export non valido (es. uguale alla sorgente)
            w.show_setup(problem)
        else:
            w.start_scan()
    rc = app.exec()
    logging.shutdown()
    # Uscita immediata: senza questo Python aspetterebbe i download iCloud ancora in corso
    # nei thread in background (anche minuti) e l'app resterebbe appesa.
    os._exit(rc)


if __name__ == "__main__":
    main()
