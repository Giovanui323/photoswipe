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

from PySide6.QtCore import QEvent, QObject, QRectF, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QImage, QImageReader, QKeySequence, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap, QShortcut)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                               QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QGridLayout,
                               QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QRadioButton,
                               QSizePolicy, QSlider, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

import applog
import cloud
import exporter
import frames
import metadata
from scanner import Item, mp4_duration, raw_preview, scan

# Versione: sale di 1 a ogni build, a decine: 1.1.9 -> 1.2.0 (lo fa packaging/build_dmg.sh)
APP_VERSION = "1.1.7"
APP_TITLE = f"PhotoSwipe {APP_VERSION}"

log = applog.setup(APP_TITLE)

PREFETCH = 10  # elementi successivi scaricati in anticipo da iCloud, in automatico
KIND_LABEL = {"photo": "FOTO", "pano": "PANORAMA", "live": "LIVE", "video": "VIDEO"}
# scelta già fatta su un elemento (tornando indietro): nome e colore dell'etichetta
CHOICE_NAME = {"yes": "✓ SÌ", "no": "✗ NO", "skip": "↷ Salta", "trash": "🗑 In “cancellare”"}
CHOICE_COLOR = {"yes": "#3fa066", "no": "#d0606a", "skip": "#9a9ca0", "trash": "#d08a3a"}
KIND_COLOR = {"photo": "#5b8def", "pano": "#a46bf0", "live": "#f0b429", "video": "#4fb7a8"}

# Stile ispirato a Foto di macOS (scuro, barre a "pillola", accento giallo) e, per la scelta,
# a Tinder: pulsanti rotondi centrati sotto la foto. Font di sistema (SF su Mac, Segoe su Windows).
STYLE = """
QMainWindow, QDialog { background: #1c1c1e; }
QWidget { color: #f2f2f7; font-size: 13px; }
QLabel, QRadioButton, QCheckBox { background: transparent; }
QToolTip { background: #2c2c2e; color: #f2f2f7; border: 1px solid #48484a; border-radius: 6px; padding: 6px; }

/* pulsanti normali: pillole grigie */
QPushButton { background: #2c2c2e; border: 1px solid #3a3a3c; border-radius: 15px; padding: 6px 14px; }
QPushButton:hover { background: #3a3a3c; }
QPushButton:pressed { background: #48484a; }
QPushButton:disabled { color: #636366; background: #242426; border-color: #2c2c2e; }

/* barra in alto, come la barra strumenti di Foto */
QFrame#pill { background: #2c2c2e; border: 1px solid #3a3a3c; border-radius: 18px; }
QFrame#pill QPushButton { background: transparent; border: none; border-radius: 14px;
                          font-size: 17px; min-width: 30px; min-height: 28px; padding: 0 6px; }
QFrame#pill QPushButton:hover { background: #3a3a3c; }
QFrame#pill QPushButton:disabled { color: #48484a; background: transparent; }
QPushButton#fav[on="true"] { color: #ff375f; }
QPushButton#undo { color: #f5b748; }
QLabel#chosen { border-radius: 8px; padding: 2px 9px; font-size: 11px; font-weight: 700; color: #111; }
QPushButton#info[on="true"] { background: #48484a; }
QSlider::groove:horizontal { height: 4px; background: #48484a; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #d1d1d6; border-radius: 2px; }
QSlider::handle:horizontal { width: 18px; height: 18px; margin: -7px 0; background: #f2f2f7;
                             border-radius: 9px; }
QSlider::groove:horizontal:disabled { background: #3a3a3c; }
QSlider::sub-page:horizontal:disabled { background: #48484a; }
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
QFrame#scenebar { background: #2c2c2e; border: 1px solid #3a3a3c; border-radius: 18px; }
QFrame#scenebar QLabel { color: #98989f; font-size: 12px; }
QFrame#scenebar QPushButton { background: #3a3a3c; border: none; border-radius: 13px; padding: 5px 12px; }
QFrame#scenebar QPushButton:hover { background: #48484a; }
QFrame#scenebar QPushButton#arrow { background: transparent; font-size: 18px; color: #d1d1d6; padding: 0; min-width: 22px; }
QFrame#scenebar QPushButton#play { background: transparent; font-size: 18px; min-width: 34px; padding: 0; }
QFrame#scenebar QPushButton#live { background: #ffd60a; color: #1c1c1e; font-weight: 700; }
QFrame#scenebar QPushButton#live:hover { background: #ffe14d; }

/* scelta, stile Tinder: cerchi scuri con anello e simbolo colorati; al passaggio si riempiono */
QPushButton[round="true"] { background: #232325; border: 2px solid #3a3a3c; padding: 0; font-weight: 700; }
QPushButton#no      { border-color: #ff4458; color: #ff4458; border-radius: 33px; font-size: 28px; }
QPushButton#yes     { border-color: #2ad48e; color: #2ad48e; border-radius: 33px; font-size: 28px; }
QPushButton#skip    { border-color: #3ca4ff; color: #3ca4ff; border-radius: 24px; font-size: 20px; }
QPushButton#trash   { border-color: #b46cff; color: #b46cff; border-radius: 24px; font-size: 18px; }
QPushButton#yesvideo{ border-color: #4fd1c5; color: #4fd1c5; border-radius: 24px; font-size: 20px; }
QPushButton#no:hover      { background: #ff4458; color: #ffffff; }
QPushButton#yes:hover     { background: #2ad48e; color: #ffffff; }
QPushButton#skip:hover    { background: #3ca4ff; color: #ffffff; }
QPushButton#trash:hover   { background: #b46cff; color: #ffffff; }
QPushButton#yesvideo:hover{ background: #4fd1c5; color: #1c1c1e; }
QPushButton[round="true"]:pressed { background: #48484a; }
/* già deciso (tornando indietro): il cerchio della scelta fatta resta pieno */
QPushButton#no[chosen="true"]    { background: #ff4458; color: #ffffff; }
QPushButton#yes[chosen="true"]   { background: #2ad48e; color: #ffffff; }
QPushButton#skip[chosen="true"]  { background: #3ca4ff; color: #ffffff; }
QPushButton#trash[chosen="true"] { background: #b46cff; color: #ffffff; }
QPushButton[round="true"]:disabled { background: #1f1f21; border-color: #2c2c2e; color: #48484a; }
QLabel#cap { color: #8e8e93; font-size: 11px; }
QLabel#snaps { background: rgba(42, 212, 142, 28); border: 1px solid rgba(42, 212, 142, 90);
               border-radius: 12px; color: #7fe3b4; font-size: 12px; padding: 8px; }
QLabel#snaps[empty="true"] { background: transparent; border: none; }
QFrame#next { background: #2c2c2e; border: 1px solid #3a3a3c; border-radius: 12px; }
QFrame#next QLabel { background: transparent; }
QLabel#muted { color: #98989f; }
QLabel#details { color: #d1d1d6; font-size: 12px; }
QFrame#settings { background: #2c2c2e; border: 1px solid #48484a; border-radius: 14px; }
QFrame#settings QPushButton { background: #3a3a3c; border: none; border-radius: 8px; text-align: left; padding: 7px 12px; }
QFrame#settings QPushButton:hover { background: #48484a; }
QFrame#settings QComboBox { background: #3a3a3c; border: none; }

/* pannello laterale (cartelle e impostazioni), come il pannello Regola di Foto */
QFrame#side { background: #232325; border-left: 1px solid #2f2f31; }
QLabel#section { color: #98989f; font-size: 11px; font-weight: 700; padding-top: 10px;
                 border-bottom: 1px solid #3a3a3c; padding-bottom: 4px; }
QFrame#side QPushButton { border-radius: 8px; text-align: left; padding: 7px 12px; }
QComboBox { background: #2c2c2e; border: 1px solid #3a3a3c; border-radius: 8px; padding: 5px 10px; }
QComboBox:hover { background: #3a3a3c; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #2c2c2e; border: 1px solid #48484a; color: #f2f2f7;
                              selection-background-color: #0a84ff; outline: 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #636366; border-radius: 4px; background: #2c2c2e; }
QCheckBox::indicator:checked { background: #0a84ff; border-color: #0a84ff; }

/* messaggi a tutta pagina (download, fine) */
QLabel#big { font-size: 17px; color: #d1d1d6; }

/* schermata iniziale */
QFrame#setup { background: #232325; border: 1px solid #3a3a3c; border-radius: 18px; }
QFrame#setup QPushButton { border-radius: 10px; }
QRadioButton { spacing: 8px; padding: 2px 0; }
QRadioButton::indicator { width: 14px; height: 14px; border-radius: 8px; border: 2px solid #8e8e93;
                          background: #2c2c2e; }
QRadioButton::indicator:checked { background: #0a84ff; border-color: #0a84ff; }
QLabel#h1 { font-size: 24px; font-weight: 700; }
QLabel#step { font-size: 16px; font-weight: 600; }
QLabel#warn { color: #ffb340; }
QLabel#path { background: #1c1c1e; border: 1px solid #3a3a3c; border-radius: 8px; padding: 8px 10px;
              color: #d1d1d6; }
QPushButton#start, QPushButton#primary { background: #ffd60a; color: #1c1c1e; border: none;
                    border-radius: 18px; font-size: 16px; font-weight: 700; padding: 9px 26px; }
QPushButton#start:hover, QPushButton#primary:hover { background: #ffe14d; }
QPushButton#start:disabled { background: #3a3a3c; color: #636366; }
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
↷ Salta (S) – decidi dopo: a fine giro puoi rivedere le saltate.
＋ SÌ e copia anche il video (Maiusc+Y) – Live: salva la foto e copia anche il video.
↩ Annulla (Z) – torna all'ultima scelta (se era un Sì, toglie i file copiati).
‹ Precedente (↑) / Successivo › (↓), in alto a sinistra – rivedi anche quelle già decise o in
   “cancellare”: una nuova scelta sostituisce la vecchia (e rimette a posto i file).
♡ Preferita (.), in alto a destra – le preferite approvate vanno in export/Preferite.
In basso le miniature prima e dopo questa: clic per andarci, il pallino è la scelta fatta.
A destra il pannello Info: giorno, luogo, fotocamera, scatto e file.

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
Cursore in alto a sinistra, due dita su/giù sul trackpad (o pizzico) = zoom, trascina per spostarti,
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


FILE_MANAGER = "Finder" if sys.platform == "darwin" else "Esplora file"


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
        self.style().drawItemText(p, r, int(self.alignment()) | Qt.AlignVCenter, self.palette(),
                                  self.isEnabled(), text, self.foregroundRole())


class OverlayLabel(QLabel):
    """Etichetta sopra la foto (avvisi in alto a destra, messaggi in basso al centro, come le
    notifiche di Foto). Vuota = nascosta; si riposiziona da sola a ogni testo nuovo."""

    def __init__(self, parent: QWidget, anchor: str):
        super().__init__("", parent)
        self.anchor = anchor
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def setText(self, text: str) -> None:
        super().setText(text)
        self.place()

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
            self.move(par.width() - w - 14, 12)
        else:
            self.move((par.width() - w) // 2, par.height() - h - 16)
        self.show()
        self.raise_()


class Bridge(QObject):
    """Riporta nel thread dell'interfaccia i risultati dei lavori in background."""
    done = Signal(str, object, object)  # tipo, chiave, risultato (o eccezione)


class ImageView(QGraphicsView):
    zoom_changed = Signal(float)   # 0 = adattata, 1 = ingrandimento massimo (per il cursore in alto)

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

    def _limits(self) -> tuple[float, float]:
        dpr = self.devicePixelRatioF()
        fit_k = min(self.viewport().width() / self.full.width(),
                    self.viewport().height() / self.full.height(), 1 / dpr)
        return fit_k, max(fit_k, 4 / dpr)

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

    def fit(self) -> None:
        self.zoomed = False
        self.zoom_changed.emit(0.0)
        self.resetTransform()
        if self.full.isNull():
            return
        dpr = self.devicePixelRatioF()
        vw, vh = self.viewport().width(), self.viewport().height()
        k = min(vw / self.full.width(), vh / self.full.height(), 1 / dpr)
        target_w = max(1, round(self.full.width() * k * dpr))
        target_h = max(1, round(self.full.height() * k * dpr))
        if target_w < self.full.width():
            pm = QPixmap.fromImage(self.full.scaled(target_w, target_h, Qt.KeepAspectRatio,
                                                    Qt.SmoothTransformation))
        else:
            pm = QPixmap.fromImage(self.full)
        pm.setDevicePixelRatio(dpr)
        self.item.setPixmap(pm)
        self.scene().setSceneRect(self.item.boundingRect())
        self.fitInView(self.item, Qt.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.zoomed:
            self.fit()

    def wheelEvent(self, e):
        self.zoom_by(1.0015 ** e.angleDelta().y())

    def event(self, e):
        if e.type() == QEvent.NativeGesture and e.gestureType() == Qt.ZoomNativeGesture:
            self.zoom_by(1.0 + e.value())  # pizzico sul trackpad
            return True
        return super().event(e)

    def zoom_by(self, factor: float) -> None:
        if self.full.isNull():
            return
        if not self.zoomed:
            if factor <= 1:
                return  # già adattata: non si rimpicciolisce oltre
            self.zoomed = True
            self._show_full()
        dpr = self.devicePixelRatioF()
        fit_k = min(self.viewport().width() / self.full.width(),
                    self.viewport().height() / self.full.height(), 1 / dpr)
        k = min(self.transform().m11() * factor, 4 / dpr)  # massimo 4 pixel dello schermo per pixel
        if k <= fit_k:
            self.fit()  # tornati alla dimensione intera: di nuovo adattata
            return
        self.scale(k / self.transform().m11(), k / self.transform().m11())
        self.zoom_changed.emit(self.zoom_level())

    def mouseDoubleClickEvent(self, e):
        self.fit()


class FilmStrip(QWidget):
    """Striscia di fotogrammi come in Foto di macOS: clic o trascina per scegliere il momento.

    Il riquadro bianco è il fotogramma scelto/mostrato, la linea sottile segue il video mentre va,
    i segni verdi sono le foto già salvate con 📷."""
    picked = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(66)
        self.setMinimumWidth(200)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.owner: str | None = None
        self.frames = 0
        self.thumbs: list[QImage] = []
        self.selected: int | None = None
        self.playhead: int | None = None
        self.marks: list[int] = []
        self._drag = False
        self._last: int | None = None

    def set_video(self, frames_: int, owner: str | None = None) -> None:
        self.owner, self.frames, self.thumbs = owner, frames_, []
        self.selected = self.playhead = None
        self.marks = []
        self.update()

    def set_thumbs(self, thumbs: list[QImage]) -> None:
        self.thumbs = thumbs
        self.update()

    def set_state(self, selected: int | None, marks: list[int]) -> None:
        self.selected, self.marks = selected, marks
        if selected is not None:
            self.playhead = None
        self.update()

    def set_playhead(self, n: int | None) -> None:
        self.playhead = n
        self.update()

    def _strip(self) -> QRectF:
        return QRectF(14, 7, max(1, self.width() - 28), self.height() - 14)

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

    def set_entries(self, entries, current: int | None) -> None:
        """entries: (indice, miniatura o None, scelta o None, è un video/Live, nome file)."""
        self.entries, self.current = entries, current
        self.update()

    def mousePressEvent(self, e):
        for r, i in self._rects:
            if r.contains(e.position()):
                self.picked.emit(i)
                return

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self._rects = []
        if not self.entries:
            return
        cw, ch, gap = self.CELL_W, self.CELL_H, self.GAP
        big = 1.18
        cx = self.width() / 2
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
            if clip:
                p.setPen(QColor("#ffffff"))
                f = p.font()
                f.setPixelSize(10)
                p.setFont(f)
                p.drawText(r.adjusted(5, 0, 0, -3), Qt.AlignLeft | Qt.AlignBottom, "▶")
            if choice in self.DOT:
                p.setPen(QPen(QColor("#1c1c1e"), 1.5))
                p.setBrush(QColor(self.DOT[choice]))
                p.drawEllipse(QRectF(r.right() - 13, r.top() + 4, 9, 9))
            if i == self.current:
                p.setPen(QPen(QColor("#ffffff"), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 7, 7)


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
        self.zoom_pill = QFrame()
        self.zoom_pill.setObjectName("pill")
        zl = QHBoxLayout(self.zoom_pill)
        zl.setContentsMargins(12, 3, 12, 3)
        zl.setSpacing(8)
        for w in (minus, self.zoom_slider, plus):
            zl.addWidget(w)
        for w in (minus, plus):
            w.setObjectName("muted")
        left.addWidget(self.zoom_pill)
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
        right.addWidget(pill(self.btn_settings, self.btn_help))

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
        sv = QVBoxLayout(self.side)
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
            b.setFocusPolicy(Qt.NoFocus)
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
        self.stamp = QLabel("", self.stack)
        self.stamp.setObjectName("stamp")
        self.stamp.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.stamp.hide()
        self.warn = OverlayLabel(self.stack, "top-right")
        self.warn.setObjectName("chip")
        self.status = OverlayLabel(self.stack, "bottom")
        self.status.setObjectName("toast")
        self.stack.installEventFilter(self)
        self.stack.currentChanged.connect(lambda *_: self.refresh_stamp())
        self.stack.currentChanged.connect(lambda *_: self.refresh_chrome())

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)
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
        self.time_label.setMinimumWidth(118)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.btn_next = QPushButton("›")
        self.btn_next.setObjectName("arrow")
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.frame_label = ElidedLabel()
        self.frame_label.setAlignment(Qt.AlignCenter)
        self.btn_live = QPushButton("▶  Vedi Live  L")
        self.btn_live.setObjectName("live")
        self.btn_live.setToolTip("Guarda il video della Live (L). Lì puoi anche cambiare fotogramma.")
        self.btn_live.clicked.connect(self.toggle_live)
        self.btn_replay = QPushButton("⟲  Rivedi  V")
        self.btn_replay.setToolTip("Riguarda il video dall'inizio, con l'audio (V).")
        self.btn_replay.clicked.connect(self.replay)
        self.btn_snap = QPushButton("📷  Prendi foto  F")
        self.btn_snap.setToolTip("Salva SUBITO come foto il fotogramma che stai guardando (F)\n"
                                 "e resta su questo video: puoi prenderne quante vuoi.\n"
                                 "Le foto salvate sono i segni verdi sulla striscia.\n"
                                 "Poi con SÌ / NO decidi se tenere anche il video.")
        self.btn_snap.clicked.connect(self.take_photo)
        self.btn_sharp = QPushButton("✨  Più nitida  P")
        self.btn_sharp.clicked.connect(self.pick_sharpest)
        self.btn_reset = QPushButton("↺  Originale  R")
        self.btn_reset.clicked.connect(self.reset_frame)
        self.btn_prev.setToolTip("Fotogramma precedente (←, Maiusc+← = 10 indietro)")
        self.btn_next.setToolTip("Fotogramma successivo (→, Maiusc+→ = 10 avanti)")
        self.strip.setToolTip("Clic o trascina sulla striscia per scegliere il fotogramma.\n"
                              "Live: quello scelto diventa la foto (SÌ salva questa).\n"
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
        def round_btn(text, name, size, tip, slot):
            b = QPushButton(text)
            b.setObjectName(name)
            b.setProperty("round", "true")
            b.setFixedSize(size, size)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            return b

        self.btn_trash = round_btn("🗑", "trash", 48,
                                   "Sposta in “cancellare” (X). Non cancella: SPOSTA l'originale\n"
                                   "(e la sua anteprima .LRF) nella cartella “cancellare” dentro la\n"
                                   "cartella che stai guardando, con le stesse sottocartelle.\n"
                                   "Poi lo cancelli tu a mano, se vuoi. Z lo rimette al suo posto.",
                                   lambda: self.decide("trash"))
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
        for b, cap in ((self.btn_trash, "No e cancella  X"),
                       (self.btn_no, "No  N"), (self.btn_skip, "Salta  S"),
                       (self.btn_yes, "Sì  Y"), (self.btn_yes_video, "Sì + video  ⇧Y")):
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addStretch(1)
            col.addWidget(b, 0, Qt.AlignHCenter)
            c = QLabel(cap)
            c.setObjectName("cap")
            c.setAlignment(Qt.AlignCenter)
            col.addWidget(c, 0, Qt.AlignHCenter)
            choices.addLayout(col)

        self.snaps_label = QLabel("")
        self.snaps_label.setObjectName("snaps")
        self.snaps_label.setAlignment(Qt.AlignCenter)
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
        self.side_layout.insertWidget(self.side_slot, self.snaps_label)
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
        lay.addWidget(self.thumbs_strip)

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
        self.side.setVisible(not self.side.isVisible())
        self.settings_store.setValue("side", "1" if self.side.isVisible() else "0")
        self.update_btn_info()

    def refresh_chrome(self):
        """Nella schermata iniziale niente barra della scelta né navigazione: solo il riquadro."""
        browsing = self.stack.currentWidget() is not self.setup_page
        self.decision_bar.setVisible(browsing)
        self.nav_pill.setVisible(browsing)
        self.zoom_pill.setVisible(browsing)
        self.zoom_slider.setEnabled(self.stack.currentWidget() is self.image_view)
        self.fav_pill.setVisible(browsing)
        for w in (self.side_info, self.side_details, self.side_sel, self.counter, self.snaps_label,
                  self.thumbs_strip):
            w.setVisible(browsing)

    def update_btn_info(self):
        self.btn_info.setProperty("on", "true" if self.side.isVisible() else "false")
        self.btn_info.style().unpolish(self.btn_info)
        self.btn_info.style().polish(self.btn_info)

    def eventFilter(self, obj, e):
        if obj is self.stack and e.type() == QEvent.Resize:
            self.warn.place()
            self.status.place()
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
            path = QLabel("")
            path.setObjectName("path")
            path.setTextInteractionFlags(Qt.TextSelectableByMouse)
            btn = QPushButton(button_text)
            btn.setFocusPolicy(Qt.NoFocus)
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
            "📂  Scegli cartella…", self.pick_source)
        self.dst_label, self.btn_pick_dst = step(
            "②", "Cartella export: dove copiare quelle approvate",
            "Le foto approvate vengono copiate qui, i video nella sottocartella “Video”. "
            "Gli originali non vengono mai spostati né modificati.",
            "📁  Scegli cartella…", self.pick_destination)
        v.addSpacing(8)
        self.q_local = QLabel("")
        self.q_local.setObjectName("muted")
        self.q_local.setWordWrap(True)
        v.addWidget(self.q_local)
        v.addSpacing(14)
        row = QHBoxLayout()
        self.btn_resume = QPushButton("")
        self.btn_resume.setFocusPolicy(Qt.NoFocus)
        self.btn_resume.clicked.connect(self.resume_last)
        self.btn_start = QPushButton("Inizia  ▶")
        self.btn_start.setObjectName("start")
        self.btn_start.setMinimumSize(150, 50)
        self.btn_start.setFocusPolicy(Qt.NoFocus)
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
        return page

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
        self.btn_pick_dst.setEnabled(self.pick_root is not None)
        on_cloud = self.cloud_files_in(self.pick_root) if self.pick_root else None
        local = self.pick_root is not None and on_cloud == 0
        self.q_local.setVisible(bool(self.pick_root))
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
                  f"✓ {c['yes']} approvate   ✗ {c['no']} scartate   ↷ {c['skip']} saltate"
                  + (f"   🗑 {c['trash']} in “cancellare”" if c.get("trash") else "")
                  + (f"   📷 {c['snap']} foto da video" if c.get("snap") else "") + "\n\n"
                  f"Iniziato il {fw(info['created'])}\n"
                  f"Ultima modifica il {fw(info['updated'])}\n"
                  f"Export: {info['export']}")
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
            self.pick_export = Path(info["export"])
            self.start_from_setup()
        elif clicked is restart:
            sure = QMessageBox.question(
                self, "Ricomincia da capo",
                "Le scelte salvate verranno messe da parte (il file viene rinominato, non "
                "cancellato).\nLe foto già copiate in export restano dove sono.\n\nContinuare?")
            if sure == QMessageBox.Yes:
                exporter.Session(root, Path(info["export"])).archive()
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

        }
        for k, fn in keys.items():
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
        cur = self.current()
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
        text.setPlainText(HELP_TEXT)
        text.setStyleSheet("QTextBrowser { background: #232325; border: 1px solid #3a3a3c;"
                           " border-radius: 10px; padding: 10px; font-size: 13px; }")
        v.addWidget(text, 1)
        row = QHBoxLayout()
        logs = QPushButton("📄  Mostra il file di log")
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
        self.submit("scan", None, scan, self.root,
                    [self.export_dir, self.root / exporter.TRASH_DIR])

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
            self.status.setText(export_warning)
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
            frames_ = sorted(self.session.get(key)["frame"] + 1 for key in self.snaps_of(item))
            shown = ", ".join(map(str, frames_[:6])) + ("…" if len(frames_) > 6 else "")
            self.snaps_label.setText(f"📷 {k} foto salvat{'a' if k == 1 else 'e'}\n"
                                     f"da questo video\n(fotogr. {shown})")
        else:
            self.snaps_label.setText("")
        self.snaps_label.setProperty("empty", "false" if k else "true")
        self.snaps_label.style().unpolish(self.snaps_label)
        self.snaps_label.style().polish(self.snaps_label)

    def flash(self, text: str):
        self.status.setStyleSheet("color:#7fd19a;")
        self.status.setText(text)

    def replay(self):
        item = self.current()
        if not item or not item.is_clip or self.stack.currentWidget() is self.msg_page:
            return
        if item.kind == "live":
            self.live_view = False
            self.toggle_live()
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
        self.msg_btn2.setText("↷  Salta questo  (S)")
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
        """Data/ora dello scatto (dal nome del file DJI) in alto a sinistra; nei video avanza."""
        item = self.current()
        page = self.stack.currentWidget()
        if not item or page not in (self.image_view, self.video_widget):
            self.stamp.hide()
            return
        from datetime import timedelta
        self.stamp.setText("🕒  " + fmt_datetime(item.taken + timedelta(seconds=offset_s)))
        self.stamp.adjustSize()
        self.stamp.move(14, 12)
        self.stamp.show()
        self.stamp.raise_()

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
        row = ("<tr><td style='color:#98989f; padding:3px 10px 3px 0; vertical-align:top'>{}</td>"
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
        if d:
            rows.append(("Scelta", {"yes": "✓ approvata", "no": "✗ scartata", "skip": "↷ saltata",
                                    "trash": "🗑 in “cancellare”"}.get(d["choice"], d["choice"])))
        if self.session and item.id in self.session.favorites:
            rows.append(("Preferita", "♥ sì"))
        html_rows += [row.format(esc(k), esc(v)) for k, v in rows]
        html.append("<table width='100%' cellspacing='0'>" + "".join(html_rows) + "</table>")
        if warn:
            html.append("<div style='color:#ffb340; margin-top:8px'>" + "<br>".join(map(esc, warn))
                        + "</div>")
        self.side_details.setText("".join(html))

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

    def update_counter(self):
        self.update_snaps_label()
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
                             f"✓ {c['yes']} approvate   ✗ {c['no']} scartate   ↷ {c['skip']} saltate"
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
                self.msg_btn2.setText("↷  Rivedi le saltate")
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
        self.show_message(f"Finito!\n\n✓ {c['yes']} scelte    ✗ {c['no']} scartate    "
                          f"↷ {c['skip']} saltate"
                          + (f"\n\n🎬 {hidden} video nascosti dal filtro “solo foto”" if hidden else "")
                          + "\n\n↑ = torna indietro a rivedere", end=True)

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
        self.btn_live.setText("🖼  Torna alla foto  L" if self.live_view else "▶  Vedi Live  L")
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
            sel = self.shown_frame if not self.live_view else self.live_photo_frame(item)
        else:
            sel = self.shown_frame if self.scene_mode else None
        marks = [self.session.get(k)["frame"] for k in self.snaps_of(item)] \
            if item.kind == "video" and self.session else []
        self.strip.set_state(sel, marks)

    @staticmethod
    def make_strip(item: Item, info: frames.VideoInfo) -> list[QImage]:
        # l'anteprima .LRF (720p) è molto più veloce da leggere, con gli stessi fotogrammi
        src = item.proxy if item.proxy and cloud.is_local(item.proxy) else (info.source or item.video)
        return [pil_to_qimage(im) for im in frames.strip_thumbs(src, info)]

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
        if img is not None:
            self.image_view.set_image(img, keep_zoom=True)
            self.stack.setCurrentWidget(self.image_view)
        elif scrub and not self.image_view.zoomed:
            self.ensure_player(item)
            self.player.pause()
            self.player.setPosition(self.frame_ms(info, n))
            self.stack.setCurrentWidget(self.video_widget)
            self.preview_timer.start()
        else:
            if not scrub:
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
        cur = self.current()
        if not isinstance(res, Exception):
            img = pil_to_qimage(res)
            self.exact_cache[key] = img
            while len(self.exact_cache) > 4:  # 4K = ~25 MB l'una
                self.exact_cache.pop(next(iter(self.exact_cache)))
            item_id, n = key
            if cur and cur.id == item_id and n == self.shown_frame \
                    and (self.scene_mode or self.showing_still(cur)):
                self.image_view.set_image(img, keep_zoom=True)
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
        self.idx = i
        self.show_item()

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

            def job(fut=fut, files=list(d["files"])):
                if not files and fut is not None:
                    try:
                        files = [str(p) for p in fut.result()]
                    except Exception:  # noqa: BLE001 - export fallito: niente da spostare
                        return []
                if on:  # quelle già in Preferite restano lì
                    files = [f for f in files if fav not in Path(f).parents]
                return exporter.relocate_exports(files, old_root, new_root)
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

    def update_thumb_strip(self):
        """Miniature degli elementi prima e dopo quello attuale (solo quelli visibili col filtro)."""
        if not self.session or not self.items:
            self.thumbs_strip.set_entries([], None)
            return
        vis = [i for i, it in enumerate(self.items) if self.visible(it)]
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
                renamed = exporter.restore_from_trash(d.get("moved", []))
            except OSError as e:
                self.status.setStyleSheet("")
                self.status.setText(f"Ripristino da “cancellare” non riuscito: {e} (riprova)")
                return False
            if renamed:
                QMessageBox.information(
                    self, APP_TITLE, "Al posto originale c'era già un file con lo stesso nome: "
                    "nessuno è stato sovrascritto. Ripristinati come:\n"
                    + "\n".join(str(p) for p in renamed))
        elif d["choice"] in ("yes", "snap"):
            fut = self.export_futures.pop(item_id, None)

            def remove(fut=fut, files=list(d["files"])):
                if not files and fut is not None:
                    try:
                        files = [str(p) for p in fut.result()]
                    except Exception:  # noqa: BLE001 - export fallito: niente da togliere
                        files = []
                exporter.remove_files(files)  # solo copie in export, mai originali
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
        if pending:
            log.info("uscita: attendo %d export in corso", len(pending))
            end = time.monotonic() + self.EXIT_WAIT_S
            while time.monotonic() < end and any(not f.done() for f in pending):
                left = sum(1 for f in pending if not f.done())
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
    app.setStyleSheet(STYLE)
    w = MainWindow()
    avail = w.screen().availableGeometry()  # schermi piccoli o scalati al 125-150%
    w.resize(min(w.width(), avail.width() - 40), min(w.height(), avail.height() - 40))
    w.show()
    if len(sys.argv) > 1:  # cartella passata da riga di comando
        w.root = Path(sys.argv[1])
        w.export_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else w.root / "export"
        w.start_scan()
    rc = app.exec()
    logging.shutdown()
    # Uscita immediata: senza questo Python aspetterebbe i download iCloud ancora in corso
    # nei thread in background (anche minuti) e l'app resterebbe appesa.
    os._exit(rc)


if __name__ == "__main__":
    main()
