"""PhotoSwipe: scegli con Sì / No / Salta le foto, i panorami e le Live da stampare."""
from __future__ import annotations

import logging
import math
import os
import subprocess
import sys
import dataclasses
import threading
import time
import uuid
import warnings
from concurrent.futures import Future, ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QImage, QImageReader, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider,
                               QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from PIL import Image

import a11y
import applog
import cloud
import editpanel as EP
import edits as E
import exporter
import frames
import infopanel
import metadata
import photobook
import places
import printprep
import similar
import stripfilter
import thumbcache
from thumbqueue import ThumbQueue
from scanner import Item, mp4_duration, raw_preview, refresh_capture_time, scan
from i18n import HELP, LANG, tr
from theme import CHOICE_COLOR, COLORS as C, KIND_COLOR, STRIP_FRAME_COLORS, STYLE, apply_dark_palette
from datefmt import _MESI_LUNGHI, fmt_datetime  # noqa: F401
from editjob import EDIT_FULL_MAX, EDIT_PROXY, print_takes_edit, render_edit_job  # noqa: F401
from widgets import (AbandonedWait, Bridge, ElidedLabel, FilmStrip, ImageView, LruCache, OverlayLabel,  # noqa: F401
                     SnapGallery, StaleResult, ThumbStrip, TipStyle, TrashButton, _MoveFailed, chevron_file,
                     hide_keep_space, pil_to_qimage, qimage_to_pil, wait_downloads)

# Versione: sale di 1 a ogni build, a decine: 1.1.9 -> 1.2.0 (lo fa packaging/build_dmg.sh)
APP_VERSION = "1.4.7"
APP_TITLE = f"PhotoSwipe {APP_VERSION}"

log = applog.setup(APP_TITLE)

PREFETCH = 10  # elementi successivi scaricati in anticipo da iCloud, in automatico
STRIP_FILTERS = ((tr('Mostra: tutte'), "all"), (tr('Mostra: da decidere'), "todo"), (tr('Mostra: già decise'), "done"),
                 (tr('Mostra: ✓ Sì'), "yes"), (tr('Mostra: ✗ No'), "no"), (tr('Mostra: ↪ saltate'), "skip"),
                 (tr('Mostra: 🗑 “cancellare”'), "trash"))
MEDIA_FILTERS = ("all", "photos", "videos")   # filtro di visualizzazione: tutto / solo foto / solo video
KIND_LABEL = {"photo": tr('FOTO'), "pano": tr('PANORAMA'), "live": tr('LIVE'), "video": tr('VIDEO')}
# scelta già fatta su un elemento (tornando indietro): nome e colore dell'etichetta
CHOICE_NAME = {"yes": tr('✓ SÌ'), "no": tr('✗ NO'), "skip": tr('↪ Salta'), "trash": tr('🗑 In “cancellare”')}

HELP_TEXT = HELP[LANG]


def help_html(text: str) -> str:
    """Aiuto in HTML: titoletti (righe in MAIUSCOLO) piccoli, grigi e staccati dal testo."""
    from html import escape
    out = []
    for line in text.split("\n"):
        if line and line.isupper() and len(line) < 40:
            out.append(f"<p style='color:{C['text_2']}; font-size:11px; font-weight:700; letter-spacing:1px;"
                       f" margin:16px 0 4px 0'>{escape(line)}</p>")
        elif not line.strip():
            out.append("<p style='margin:6px 0'></p>")
        else:
            lead = len(line) - len(line.lstrip(" "))
            out.append(f"<p style='margin:2px 0 2px {lead * 6}px'>{escape(line.lstrip(' '))}</p>")
    return "".join(out)


FILE_MANAGER = "Finder" if sys.platform == "darwin" else tr('Esplora file')


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
        self.pre = ThreadPoolExecutor(max_workers=2)       # anticipo dei successivi (2 alla volta)
        # attese dei download dell'elemento corrente: quelle degli elementi lasciati finiscono
        # subito (o non partono), così quello su cui ti fermi non aspetta dietro di loro
        self.waiters = ThreadPoolExecutor(max_workers=4)
        # ("ready-now"|"ready-pre", id) -> [future, abbandonato, gettone] dei download in corso
        self._ready_jobs: dict[tuple[str, str], list] = {}
        self.export_q = ThreadPoolExecutor(max_workers=1)  # export in ordine, uno alla volta
        # fotogrammi da mostrare subito: coda tutta loro, non aspettano dietro le miniature
        self.frames_q = ThreadPoolExecutor(max_workers=2)
        # copia per la stampa (Real-ESRGAN può metterci minuti): coda sua, non blocca il resto
        self.print_q = ThreadPoolExecutor(max_workers=1)
        self.thumb_q = ThumbQueue()   # miniature della striscia: dal centro, annullabili, riprovate
        self._strip_idx: dict[str, int] = {}   # id -> indice, per le miniature ora nella striscia
        self.print_job: str | None = None   # id della foto in preparazione, None = nessun lavoro
        self.bridge = Bridge()
        self.bridge.done.connect(self.on_done)
        self.bridge.progress.connect(self.on_print_progress)

        self.root: Path | None = None
        self.export_dir: Path | None = None
        self.session: exporter.Session | None = None
        self.items: list[Item] = []
        self.idx = 0
        self.review_skipped = False
        self.history: list[tuple[int, str, dict | None]] = []
        self.export_futures: dict[str, Future] = {}
        self._scan_gen = 0
        self._rename_busy = False   # cresce a ogni apertura: i risultati vecchi non vanno nei dati nuovi
        # dove sono ORA le copie spostate (Preferite) secondo la coda export: la sessione lo sa solo
        # dopo, e un Annulla o un altro ♥ in coda subito dietro userebbero i percorsi vecchi.
        # Letto e scritto SOLO dai lavori di export_q (un solo thread, in ordine).
        self.copy_paths: dict[str, list[str]] = {}
        self.still_owner: str | None = None   # elemento la cui foto è ora a schermo
        self.pending: set[tuple[str, str]] = set()
        self._sharp_busy = False      # una ricerca del fotogramma più nitido alla volta
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
        self.exact_cache: LruCache = LruCache(4)   # ultimi fotogrammi esatti (4K)
        # fotogrammi dall'anteprima .LRF (720p), JPEG in memoria: si vedono subito quando scegli
        # un fotogramma, poi arriva quello esatto in 4K. ~18 MB per una Live intera, 2 elementi.
        self.proxy_frames: LruCache = LruCache(2)  # id -> (primo fotogramma, [jpeg, …])
        self._preview_busy = False
        self._preview_again = False
        self.meta: dict[str, metadata.Meta] = {}    # metadati per il pannello Info
        self.burst_ids: set[str] = set()            # vicini guardati per la raffica (similar.py)
        # miniature con un tetto, così la memoria non cresce scorrendo migliaia di foto
        self.thumbs: LruCache = LruCache(12)        # striscia dei fotogrammi: ~1,4 MB per video
        self.next_thumbs: LruCache = LruCache(120)  # striscia in basso (ne mostra 25): ≤0,7 MB l'una
        self._by_id: dict[str, Item] = {}
        self._trash_view: tuple[str, int, Item] | None = None
        saved_filter = self.settings_store.value("filter", "all")
        self.media_filter = saved_filter if saved_filter in MEDIA_FILTERS else "all"
        # Regola / Ritaglia
        self.edit_pool = ThreadPoolExecutor(max_workers=1)
        self.edit_base: QImage | None = None   # foto a schermo, senza modifiche
        self.edit_base_owner: str | None = None
        self._edit_proxy = None
        self._edit_tiny = None
        self.edit_gen = 0
        # i calcoli più vecchi di questo non si mostrano più (altra foto o fotogramma, originale a
        # schermo, copia per la stampa…); quelli più recenti sì, anche se non sono l'ultimo
        self._edit_floor = 0
        self._edit_busy = False
        self._edit_again = False
        self.crop_draft: dict | None = None    # Ritaglia aperto: bozza finché non si preme OK
        self.tone_draft: dict | None = None    # Regola toccata: bozza finché non si preme OK
        self.side_tab = "info"
        self._tab_before_crop = "info"

        self._build_ui()
        self._build_shortcuts()
        a11y.setup(self)   # VoiceOver: nomi dei pulsanti con sola icona; focus solo con Tab
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
        self.btn_home = QPushButton("⌂")
        self.btn_home.setToolTip(tr("Home: torna alla scelta della cartella (la sessione resta salvata)."))
        self.btn_home.clicked.connect(self.go_home)
        self.btn_back = QPushButton("‹")
        self.btn_back.setToolTip(tr("Precedente (← o B): torna all'elemento prima, anche se già deciso\n(approvato, scartato, in “cancellare”). La nuova scelta sostituisce la vecchia."))
        self.btn_back.clicked.connect(self.go_back)
        self.btn_fwd = QPushButton("›")
        self.btn_fwd.setToolTip(tr("Successivo (→): vai all'elemento dopo senza decidere."))
        self.btn_fwd.clicked.connect(self.go_forward)
        self.btn_undo = QPushButton("↩")
        self.btn_undo.setObjectName("undo")
        self.btn_undo.setToolTip(tr("Annulla l'ultima scelta e torna indietro (Z).\nSe era un Sì, toglie anche i file copiati in export."))
        self.btn_undo.clicked.connect(self.undo)
        self.nav_pill = pill(self.btn_home, self.btn_back, self.btn_fwd, self.btn_undo)
        left = QHBoxLayout()
        left.setSpacing(10)
        if self.unified:
            left.addSpacing(62)   # spazio per i semafori (chiudi, riduci, schermo intero)
        left.addWidget(self.nav_pill)
        # come in Foto mentre si modifica: □|□ confronta con l'originale, "Ripristina originale"
        self.btn_compare = EP.CompareButton()
        self.btn_compare.setObjectName("toolround")
        self.btn_compare.setFixedSize(40, 32)
        self.btn_compare.setFocusPolicy(Qt.NoFocus)
        self.btn_compare.setToolTip(tr('Confronta: mostra la foto originale (di nuovo = torna alla modificata).'))
        self.btn_compare.toggled.connect(self.set_compare)
        self.btn_restore = QPushButton(tr('Ripristina originale'))
        self.btn_restore.setObjectName("toolpill")
        self.btn_restore.setFocusPolicy(Qt.NoFocus)
        self.btn_restore.setToolTip(tr('Toglie tutte le modifiche (Regola e Ritaglia): torna la foto originale.'))
        self.btn_restore.clicked.connect(self.discard_edits)
        for b in (self.btn_compare, self.btn_restore):
            b.setCursor(Qt.PointingHandCursor)
            b.setVisible(False)
            left.addWidget(b)
        minus, plus = QLabel("–"), QLabel("+")
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(0, 100)
        self.zoom_slider.setFixedWidth(110)
        self.zoom_slider.setFocusPolicy(Qt.NoFocus)
        self.zoom_slider.setToolTip(tr('Zoom (anche due dita sul trackpad o rotella; doppio clic = foto intera)'))
        self.zoom_pill = QFrame()   # sopra la foto, sotto la data (vedi place_zoom)
        self.zoom_pill.setObjectName("zoompill")
        zl = QHBoxLayout(self.zoom_pill)
        zl.setContentsMargins(12, 3, 12, 3)
        self.zoom_pill.setFixedHeight(28)   # raggio 14 = metà altezza: angoli tondi
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
        self.chosen_tag.setToolTip(tr("Questo elemento è già stato deciso. Premi un'altra scelta per cambiarla:\nla nuova sostituisce la vecchia e i file tornano a posto (Z annulla)."))
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
        self.stamp = ElidedLabel()   # data e ora dello scatto, accanto a "1 di 14": non copre la foto
        self.stamp.setObjectName("subtitle")
        title_row = QHBoxLayout()
        for w, k in ((None, 1), (self.title, 0), (self.stamp, 0), (None, 1)):
            title_row.addStretch(1) if w is None else title_row.addWidget(w, k)
        center = QVBoxLayout()
        center.setSpacing(1)
        center.addLayout(head_row)
        center.addLayout(title_row)

        self.btn_fav = QPushButton("♡")
        self.btn_fav.setObjectName("fav")
        self.btn_fav.setToolTip(tr('Preferita (.): le preferite approvate vengono copiate in\nexport/Foto/Preferite invece che in export/Foto.'))
        self.btn_fav.clicked.connect(self.toggle_favorite)
        self.btn_help = QPushButton("?")
        self.btn_help.setToolTip(tr('Come funziona (? o H): spiega tutti i pulsanti e i tasti.\nDa qui apri anche il file di log.'))
        self.btn_help.clicked.connect(self.show_help)
        self.btn_info = QPushButton("ⓘ")
        self.btn_info.setObjectName("info")
        self.btn_info.setToolTip(tr('Mostra / nascondi il pannello delle informazioni (I).'))
        self.btn_info.clicked.connect(self.toggle_side)
        self.btn_settings = QPushButton("⚙︎")
        self.btn_settings.setToolTip(tr('Impostazioni: cartella, export, filtro, formato e ora.'))
        self.btn_settings.clicked.connect(self.show_settings)
        self.btn_wand = EP.WandButton()
        self.btn_wand.setObjectName("wand")
        self.btn_wand.setToolTip(tr('Migliora automaticamente (bacchetta magica): Luce e Colore automatici.\nDi nuovo = toglie il miglioramento. Poi Conferma le modifiche.'))
        self.btn_wand.clicked.connect(self.auto_enhance)
        self.fav_pill = pill(self.btn_fav, self.btn_wand)
        right = QHBoxLayout()
        right.setSpacing(8)
        right.addStretch(1)
        right.addWidget(self.fav_pill)
        right.addWidget(pill(self.btn_info, self.btn_settings, self.btn_help))
        self.btn_edit_cancel_top = QPushButton(tr("Annulla"))
        self.btn_edit_cancel_top.setObjectName("toolpill")
        self.btn_edit_cancel_top.setToolTip(tr("Lascia la foto com'era prima di queste modifiche (Esc)."))
        self.btn_edit_cancel_top.clicked.connect(self.cancel_edit)
        for b in (self.btn_edit_cancel_top,):
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.setVisible(False)
            right.addWidget(b)

        top = QGridLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setHorizontalSpacing(8)
        top.addLayout(left, 0, 0)
        # il titolo sta sopra tutta la riga, centrato sulla finestra (come le barre di macOS):
        # non si sposta se i pulsanti a sinistra e a destra sono larghi diversi
        self.title_box = QWidget()
        self.title_box.setLayout(center)
        center.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.title_box, 0, 0, 1, 3, Qt.AlignHCenter | Qt.AlignVCenter)
        top.addLayout(right, 0, 2)
        top.setColumnStretch(0, 1)   # colonne laterali uguali: il titolo resta centrato davvero
        top.setColumnStretch(1, 2)
        top.setColumnStretch(2, 1)
        lay.addLayout(top)
        self.top_grid, self.top_left, self.top_right = top, left, right

        # ---- impostazioni: finestrella che si apre dal pulsante ⚙ (come i menu di Foto)
        self.btn_open = QPushButton(tr('📂  Apri cartella…'))
        self.btn_open.clicked.connect(self.choose_root)
        self.btn_export = QPushButton(tr('Export: —'))
        self.btn_export.clicked.connect(self.choose_export)
        self.btn_show_export = QPushButton(tr('Mostra export in {FILE_MANAGER}', FILE_MANAGER=FILE_MANAGER))
        self.btn_show_export.clicked.connect(self.open_export)
        self.fmt = QComboBox()
        self.fmt.addItems([tr('JPEG qualità massima'), tr('PNG 16-bit (senza perdita)')])
        self.tz = QComboBox()
        self.tz.addItem(tr('Ora: della fotocamera'), None)
        for h in range(-12, 15):
            self.tz.addItem(f"Ora: UTC{h:+d}", float(h))
        self.view_filter = QComboBox()
        self.view_filter.addItems([tr('Mostra: tutto'), tr('Mostra: solo foto (anche Live e panorami)'),
                                   tr('Mostra: solo video (Live escluse)')])
        self.view_filter.setCurrentIndex(MEDIA_FILTERS.index(self.media_filter))
        self.view_filter.currentIndexChanged.connect(self.on_filter_changed)
        btn_help2 = QPushButton(tr('?  Come funziona'))
        btn_help2.clicked.connect(self.show_help)
        tips = {
            self.btn_open: tr('Scegli la cartella con foto e video (vengono lette anche le sottocartelle).'),
            self.btn_export: tr('Cartella dove vengono COPIATE le foto approvate. Gli originali non si toccano.'),
            self.fmt: tr('Formato dei fotogrammi estratti da Live e video.\nJPEG qualità massima: accettato da tutti i siti di stampa.\nPNG 16-bit: senza perdita, file molto grandi (~40 MB).\nFoto e panorami vengono sempre copiati identici.'),
            self.tz: tr("Fuso orario scritto nella data delle foto esportate.\n'Della fotocamera' usa l'ora registrata in ogni file."),
            self.view_filter: tr("Solo foto: nasconde i video (restano foto, Live e panorami).\nSolo video: nasconde foto, Live e panorami.\nGli elementi nascosti non vengono toccati: li ritrovi con 'Mostra: tutto'."),
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
        for head, widgets in ((tr('CARTELLE'), (self.btn_open, self.btn_export, self.btn_show_export)),
                              (tr('VISUALIZZA'), (self.view_filter, places.online_switch(self.settings_store))),
                              (tr('FOTOGRAMMI ESPORTATI'), (self.fmt, self.tz)),
                              (tr('AIUTO'), (btn_help2,))):
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
        side_outer.setSpacing(0)
        # in alto la scelta, come Regola · Stili · Ritaglia di Foto: Info (il pannello di sempre),
        # Regola (luce, colore, …) e Ritaglia
        self.side_seg = EP.Segmented([("info", tr('Info')), ("regola", tr('Regola')), ("ritaglia", tr('Ritaglia'))])
        self.side_seg.set_current("info")
        self.side_seg.changed.connect(self.on_side_tab)
        self.side_seg.buttons["info"].setToolTip(tr('Informazioni sulla foto e sulla selezione.'))
        self.side_seg.buttons["regola"].setToolTip(tr("Luce, colore, bianco e nero, curve, nitidezza…\n✓ Sì esporta la foto modificata (l'originale non si tocca)."))
        self.side_seg.buttons["ritaglia"].setToolTip(tr('Ritaglia, raddrizza e proporzioni. Conferma con OK,\npoi ✓ Sì esporta la foto ritagliata.'))
        seg_wrap = QHBoxLayout()
        seg_wrap.setContentsMargins(14, 10, 14, 4)
        seg_wrap.addWidget(self.side_seg)
        side_outer.addLayout(seg_wrap)
        self.side_pages = QStackedWidget()
        self.photobook = photobook.PhotoBook()   # fisso sotto le Info che scorrono: sempre in vista
        self.side_pages.addWidget(photobook.pin_below(side_scroll, self.photobook))
        self.regola = EP.RegolaPanel()
        self.regola.changed.connect(self.on_regola_changed)
        self.regola.auto_requested.connect(self.on_auto)
        self.regola.reset_all.connect(self.reset_regola)
        self.regola.redeye_mode.connect(lambda on: self.update_pick_mode())
        self.side_pages.addWidget(EP.scroll(self.regola, "regolabody"))
        self.ritaglia = EP.RitagliaPanel()
        self.ritaglia.changed.connect(self.on_crop_draft)
        self.ritaglia.aspect_changed.connect(self.on_crop_aspect)
        self.ritaglia.ok.connect(self.crop_ok)
        self.ritaglia.cancel.connect(self.crop_cancel)
        self.ritaglia.btn_ok.hide()       # OK / Annulla stanno in fondo al pannello, per tutti e due
        self.ritaglia.btn_cancel.hide()
        self.ritaglia.auto.connect(self.crop_auto)
        self.side_pages.addWidget(EP.scroll(self.ritaglia, "ritagliabody"))
        side_outer.addWidget(self.side_pages, 1)
        # in fondo, sempre: le modifiche di questa foto e il pulsante per toglierle
        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(18, 6, 18, 12)
        fl.setSpacing(5)
        self.edit_badge = QLabel("")
        self.edit_badge.setObjectName("editbadge")
        self.edit_badge.setWordWrap(True)
        fl.addWidget(self.edit_badge)
        self.btn_confirm_foot = QPushButton(tr('Conferma le modifiche'))
        self.btn_confirm_foot.setObjectName("cropok")
        self.btn_confirm_foot.setFocusPolicy(Qt.NoFocus)
        self.btn_confirm_foot.setCursor(Qt.PointingHandCursor)
        self.btn_confirm_foot.setToolTip(tr('Conferma le modifiche (Invio). Poi ✓ Sì esporta la foto modificata.'))
        self.btn_confirm_foot.clicked.connect(self.finish_edit)
        self.btn_confirm_foot.setVisible(False)
        self.btn_confirm_foot.setFixedHeight(40)   # stessa altezza di "Annulla le modifiche"
        self.btn_confirm_foot.setStyleSheet("border-radius: 20px; font-size: 15px;")   # stessa forma e corpo di "Annulla le modifiche"
        fl.addWidget(self.btn_confirm_foot)
        self.btn_discard = QPushButton(tr('Annulla le modifiche'))
        self.btn_discard.setObjectName("cropbig")
        self.btn_discard.setFixedHeight(40)
        self.btn_discard.setFocusPolicy(Qt.NoFocus)
        self.btn_discard.setToolTip(tr("Toglie regolazioni e ritaglio da questa foto: torna l'originale.\n(Se l'avevi già approvata, premi di nuovo ✓ Sì per esportarla com'era.)"))
        self.btn_discard.clicked.connect(self.discard_edits)
        fl.addWidget(self.btn_discard)
        self.side_foot = foot
        side_outer.addWidget(foot)
        sv = QVBoxLayout(side_body)
        sv.setContentsMargins(18, 10, 18, 18)   # come Regola e Ritaglia
        sv.setSpacing(16)   # aria tra data, scheda, luogo e riquadri
        self.side_layout = sv
        self.side_info = QLabel("")   # titolo solo per le foto prese da un video: la linguetta dice già Info
        self.side_info.setObjectName("panelhead")
        self.side_info.hide()
        sv.addWidget(self.side_info)
        self.side_details = QLabel("")
        self.side_details.setObjectName("details")
        self.side_details.setWordWrap(True)
        self.side_details.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.side_details.setOpenExternalLinks(True)   # solo il link "Apri nella mappa", se cliccato
        sv.addWidget(self.side_details)
        # come l'Info di Foto: una sola scheda grigia con fotocamera e dati di scatto
        self.info_card = QFrame()
        self.info_card.setObjectName("infocard")
        icl = QVBoxLayout(self.info_card)
        icl.setContentsMargins(14, 12, 14, 12)
        self.info_card_text = QLabel("")
        self.info_card_text.setWordWrap(True)
        self.info_card_text.setTextFormat(Qt.RichText)
        self.info_card_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        icl.addWidget(self.info_card_text)
        self.info_card.hide()
        sv.addWidget(self.info_card)
        self.side_more = QLabel("")
        self.side_more.setObjectName("details")
        self.side_more.setWordWrap(True)
        self.side_more.setTextFormat(Qt.RichText)
        self.side_more.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.side_more.setOpenExternalLinks(True)
        sv.addWidget(self.side_more)
        # box a parte: quanto regge la foto in stampa, e la copia migliorata per la stampa
        self.print_box = QFrame()
        self.print_box.setObjectName("printbox")
        pb = QVBoxLayout(self.print_box)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(10)
        ph = QLabel(tr('Stampa').upper())
        ph.setObjectName("subhead")
        pb.addWidget(ph)
        self.print_text = QLabel("")
        self.print_text.setObjectName("details")
        self.print_text.setWordWrap(True)
        self.print_text.setTextFormat(Qt.RichText)
        pb.addWidget(self.print_text)
        self.btn_print_fix = QPushButton(tr('Migliora per la stampa'))
        self.btn_print_fix.setToolTip(tr('Crea una copia per la stampa in export/Stampa: ingrandisce con Real-ESRGAN (se installato) o Lanczos, e aggiunge nitidezza. L\'originale non si tocca.'))
        self.btn_print_fix.setFocusPolicy(Qt.TabFocus)
        self.btn_print_fix.setObjectName("textlink")   # azione secondaria: un link, non il pulsante più grande
        self.btn_print_fix.clicked.connect(self.improve_for_print)
        pb.addWidget(self.btn_print_fix)
        # conferma inline sotto "Migliora per la stampa": Sì avvia la copia, Annulla non fa nulla
        self.print_ask_row = QFrame()
        ask = QVBoxLayout(self.print_ask_row)
        ask.setContentsMargins(0, 0, 0, 0)
        ask.setSpacing(6)
        self.print_ask = QLabel("")
        self.print_ask.setObjectName("details")
        self.print_ask.setWordWrap(True)
        ask.addWidget(self.print_ask)
        ask_btns = QHBoxLayout()
        btn_yes = QPushButton(tr('Sì'))
        btn_yes.setObjectName("cropok")
        btn_yes.setFocusPolicy(Qt.TabFocus)
        btn_yes.clicked.connect(self.print_yes)
        btn_no = QPushButton(tr('Annulla'))
        btn_no.setFocusPolicy(Qt.TabFocus)
        btn_no.clicked.connect(self.print_no)
        ask_btns.addWidget(btn_yes)
        ask_btns.addWidget(btn_no)
        ask.addLayout(ask_btns)
        self.print_ask_row.hide()
        pb.addWidget(self.print_ask_row)
        # dopo la copia: □|□ per vedere la copia al posto della foto (stessa grandezza a schermo)
        self.btn_print_cmp = QPushButton(tr('Confronta con la copia per la stampa'))
        self.btn_print_cmp.setCheckable(True)
        self.btn_print_cmp.setFocusPolicy(Qt.TabFocus)
        self.btn_print_cmp.setToolTip(tr('Premuto: mostra la copia per la stampa. Di nuovo: torna alla foto.'))
        self.btn_print_cmp.toggled.connect(self.set_print_compare)
        self.btn_print_cmp.hide()
        pb.addWidget(self.btn_print_cmp)
        # barra a tempo indeterminato: si vede mentre la copia si prepara
        self.print_busy = QProgressBar()
        self.print_busy.setObjectName("progress")
        self.print_busy.setTextVisible(False)
        self.print_busy.setRange(0, 0)
        self.print_busy.hide()
        pb.addWidget(self.print_busy)
        self.print_box.hide()
        sv.addWidget(self.print_box)
        sel = QLabel(tr('Selezione').upper())
        sel.setObjectName("subhead")
        sv.addWidget(sel)
        # quante già fatte: in evidenza (numero grande e barra), poi il dettaglio
        self.done_label = QLabel("")
        self.done_label.setTextFormat(Qt.RichText)
        sv.addWidget(self.done_label)
        self.progress = QProgressBar()
        self.progress.setObjectName("progress")
        self.progress.setTextVisible(False)
        sv.addWidget(self.progress)
        self.counter = QLabel("")
        self.counter.setObjectName("details")
        self.counter.setWordWrap(True)
        sv.addWidget(self.counter)
        self.side_sel = sel
        # salvataggio: deve essere chiaro che è automatico, quando è avvenuto e dove sta
        self.save_head = QLabel(tr('Salvataggio').upper())
        self.save_head.setObjectName("subhead")
        sv.addWidget(self.save_head)
        self.save_info = QLabel("")
        self.save_info.setObjectName("details")
        self.save_info.setWordWrap(True)
        self.save_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sv.addWidget(self.save_info)
        self.btn_save_now = QPushButton(tr('Salva ora'))
        self.btn_save_now.setToolTip(tr('Non serve: si salva da solo a ogni scelta.\nSe vuoi esserne sicuro, questo salva subito.'))
        self.btn_save_now.clicked.connect(self.save_now)
        self.btn_show_save = QPushButton(tr('Mostra'))
        self.btn_show_save.setToolTip(tr('Mostra in {FILE_MANAGER} il file con i progressi.', FILE_MANAGER=FILE_MANAGER))
        self.btn_show_save.clicked.connect(self.reveal_session)
        self.btn_side_export = QPushButton(tr('Export'))
        self.btn_side_export.setToolTip(tr('Apre in {FILE_MANAGER} la cartella con le foto approvate.', FILE_MANAGER=FILE_MANAGER))
        self.btn_side_export.clicked.connect(self.open_export)
        # una riga di link: si salva da solo, questi servono di rado e non devono pesare
        self.save_row = QWidget()
        srow = QHBoxLayout(self.save_row)
        srow.setContentsMargins(0, 0, 0, 0)
        srow.setSpacing(12)
        for b in (self.btn_save_now, self.btn_show_save, self.btn_side_export):
            b.setObjectName("textlink")
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            srow.addWidget(b)
        srow.addStretch(1)
        sv.addWidget(self.save_row)
        sv.addStretch(1)
        outer.addWidget(self.side)   # la versione è nel titolo della finestra e in Aiuto

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
        self.video_widget.setStyleSheet(f"background: {C['bg_window']};")
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
        self.msg_btn3 = QPushButton(tr('Nuova selezione…'))   # a fine selezione: chiude e apre un'altra cartella
        for b in (self.msg_btn1, self.msg_btn2, self.msg_btn3):
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
        # frecce ai lati della foto: come Su / Giù (foto precedente / successiva)
        self.photo_prev = QPushButton("‹", self.stack)
        self.photo_next = QPushButton("›", self.stack)
        for b, fn, tip in ((self.photo_prev, self.go_back, 'Foto precedente'),
                           (self.photo_next, self.go_forward, 'Foto successiva')):
            b.setObjectName("photoarrow")
            b.setFixedSize(44, 44)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tr(tip))
            b.clicked.connect(lambda _=False, fn=fn: self.nav_unless_editing(fn))
            b.hide()
        self.stamp.hide()
        self.warn = OverlayLabel(self.stack, "top-right")
        self.warn.setObjectName("chip")
        self.warn.avoid = [self.zoom_pill]
        self.status = OverlayLabel(self.stack, "bottom", hide_after_ms=8000)   # errori: un po' di più
        self.status.setObjectName("toast")
        # foto presa dal video, vista a schermo intero (doppio clic sulla miniatura)
        self.snap_key: str | None = None
        self.snap_bar = QFrame(self.stack)
        sb = QHBoxLayout(self.snap_bar)
        sb.setContentsMargins(10, 6, 10, 6)
        sb.setSpacing(8)
        self.snap_fix = QPushButton(tr('Correggi'))
        self.snap_save = QPushButton(tr('Aggiorna foto'))
        self.snap_close = QPushButton(tr('Chiudi ✕'))
        self.snap_fix.clicked.connect(self.fix_snap)
        self.snap_save.clicked.connect(self.save_snap_fix)
        self.snap_close.clicked.connect(self.close_snap)
        for b in (self.snap_fix, self.snap_save, self.snap_close):
            b.setFocusPolicy(Qt.TabFocus)
            sb.addWidget(b)
        self.snap_bar.hide()
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
        self.btn_play.setToolTip(tr('Play / Pausa (barra spaziatrice)'))
        self.btn_play.clicked.connect(self.play_pause)
        self.btn_prev = QPushButton("❮")
        self.btn_prev.setObjectName("bracket")
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
        self.time_label.setMinimumWidth(60)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.btn_next = QPushButton("❯")
        self.btn_next.setObjectName("bracket")
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.frame_label = ElidedLabel()
        self.frame_label.setAlignment(Qt.AlignCenter)
        self.btn_live = QPushButton(tr('▶  Vedi Live (L)'))
        self.btn_live.setObjectName("live")
        self.btn_live.clicked.connect(self.toggle_live)
        self.btn_replay = QPushButton(tr('⟲  Rivedi (V)'))
        self.btn_replay.clicked.connect(self.replay)
        self.btn_snap = QPushButton(tr('📷  Prendi foto (F)'))
        self.btn_snap.setToolTip(tr('Salva SUBITO come foto il fotogramma che stai guardando (F)\ne resta su questo video: puoi prenderne quante vuoi.\nLe foto salvate sono i segni verdi sulla striscia.\nPoi con SÌ / NO decidi se tenere anche il video.'))
        self.btn_snap.clicked.connect(self.take_photo)
        self.btn_sharp = QPushButton(tr('✨  Più nitida (P)'))
        self.btn_sharp.clicked.connect(self.pick_sharpest)
        self.btn_reset = QPushButton(tr('↺  Originale (R)'))
        self.btn_reset.clicked.connect(self.reset_frame)
        self.btn_prev.setToolTip(tr('Fotogramma precedente (↑, Maiusc+↑ = 10 indietro)'))
        self.btn_next.setToolTip(tr('Fotogramma successivo (↓, Maiusc+↓ = 10 avanti)'))
        self.strip.setToolTip(tr('Clic o trascina sulla striscia per scegliere il fotogramma.\nLive: quello scelto diventa la foto (SÌ salva questa).\nLive: il pallino giallo è la foto scelta dalla fotocamera (R per tornarci).\nVideo: si ferma lì, poi 📷 Prendi foto.  ↑ ↓ un fotogramma alla volta.'))
        # come in Foto: la striscia tra due parentesi in un riquadro, poi volume e menu "Live"
        self.strip_box = QFrame()
        self.strip_box.setObjectName("stripbox")
        sbx = QHBoxLayout(self.strip_box)
        sbx.setContentsMargins(2, 2, 2, 2)
        sbx.setSpacing(0)
        for w in (self.btn_prev, self.strip, self.btn_next):
            w.setFocusPolicy(Qt.NoFocus)
            sbx.addWidget(w, 1 if w is self.strip else 0)
        self.btn_volume = EP.VolumeButton()
        self.btn_volume.setObjectName("volume")
        self.btn_volume.setFixedSize(38, 32)
        self.btn_volume.setFocusPolicy(Qt.NoFocus)
        self.btn_volume.setChecked(self.settings_store.value("muted", "0") == "1")
        self.btn_volume.setToolTip(tr("Audio acceso / spento (Live e video)"))
        self.btn_volume.toggled.connect(self.on_volume)
        self.live_mode = self.settings_store.value("live_mode", "live")
        if self.live_mode not in ("live", "loop", "off"):
            self.live_mode = "live"
        self.btn_live_mode = QPushButton()
        self.btn_live_mode.setObjectName("livemode")
        self.btn_live_mode.setFocusPolicy(Qt.NoFocus)
        self.btn_live_mode.setFixedHeight(28)
        self.btn_live_mode.setToolTip(tr("Come si riproduce la Live quando fai clic sulla foto"))
        self.btn_live_mode.clicked.connect(self.show_live_menu)
        self._live_pop = QFrame(self, Qt.Popup)
        self._live_pop.setAttribute(Qt.WA_TranslucentBackground)
        lpo = QVBoxLayout(self._live_pop)
        lpo.setContentsMargins(0, 0, 0, 0)
        lcard = QFrame()
        lcard.setObjectName("settings")
        lpo.addWidget(lcard)
        lv = QVBoxLayout(lcard)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(2)
        self._live_mode_btns = {}
        for key in ("live", "loop", "off"):
            b = QPushButton()
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_live_mode(k))
            lv.addWidget(b)
            self._live_mode_btns[key] = b
        self._live_pop.setFixedWidth(200)
        self.btn_play.setFocusPolicy(Qt.NoFocus)
        self.time_label.setFocusPolicy(Qt.NoFocus)
        timeline.addWidget(self.btn_play)
        timeline.addSpacing(4)
        timeline.addWidget(self.strip_box, 1)
        timeline.addWidget(self.time_label)
        timeline.addWidget(self.btn_volume)
        self.refresh_live_mode()
        # riga 2: il tipo di Live, le azioni e, in piccolo, a che fotogramma sei
        sl.addStretch(1)
        sl.addWidget(self.btn_live_mode)
        for w in (self.btn_live, self.btn_replay, self.btn_snap, self.btn_sharp, self.btn_reset):
            w.setFocusPolicy(Qt.NoFocus)
            sl.addWidget(w)
        sl.addSpacing(6)
        self.frame_label.setObjectName("framestatus")
        self.frame_label.setMaximumWidth(300)
        sl.addWidget(self.frame_label)
        sl.addStretch(1)
        vbar.addLayout(timeline)
        vbar.addLayout(sl)
        scene_row = QHBoxLayout()
        scene_row.addStretch(1)
        scene_row.addWidget(self.scene_bar, 100)
        scene_row.addStretch(1)
        lay.addLayout(scene_row)
        self.player.positionChanged.connect(self.on_position)
        self.player.playbackStateChanged.connect(self.on_play_state)
        self.player.mediaStatusChanged.connect(self.on_media_status)
        self.image_view.clicked.connect(self.on_media_click)
        self.video_widget.installEventFilter(self)   # clic sul video: pausa / play

        # ---- scelta, stile Tinder: pulsanti rotondi centrati, con il tasto scritto sotto
        self.choice_btns: list[QPushButton] = []

        def round_btn(text, name, size, slot, cls=QPushButton):
            b = cls(text)
            b.setObjectName(name)
            b.setProperty("round", "true")
            b.setFixedSize(size, size)
            b.base_size = size   # misura a finestra normale; con lo schermo grande cresce (layout_choices)
            self.choice_btns.append(b)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            return b

        self.btn_trash = round_btn("", "trash", 48,
                                   lambda: self.decide("trash"), TrashButton)
        self.btn_no = round_btn("✕", "no", 66,
                                lambda: self.decide("no"))
        self.btn_skip = round_btn("↪", "skip", 48,
                                  lambda: self.decide("skip"))
        self.btn_yes = round_btn("✓", "yes", 66,
                                 lambda: self.decide("yes"))
        self.btn_yes_video = round_btn("＋", "yesvideo", 48,
                                       lambda: self.decide("yes", with_video=True))
        choices = QHBoxLayout()
        choices.setSpacing(16)
        self.choice_caps: dict[str, QLabel] = {}
        self.cap_of: dict[QPushButton, QLabel] = {}
        for b, cap in ((self.btn_trash, tr('No e cancella (X)')),
                       (self.btn_no, "No (N)"), (self.btn_skip, tr('Salta (S)')),
                       (self.btn_yes, tr('Sì (Y)')), (self.btn_yes_video, tr('Sì + video (⇧Y)'))):
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addStretch(1)
            col.addWidget(b, 0, Qt.AlignHCenter)
            b.setAccessibleName(cap.replace(" (", tr(', tasto ')).rstrip(")"))  # VoiceOver: non "segno di moltiplicazione"
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
        self.snaps_label.setToolTip(tr("Foto prese da questo video con 📷 Prendi foto.\nRestano salvate in export anche se premi NO.\nZ annulla l'ultima presa."))
        self.snap_gallery = SnapGallery()
        self.snap_gallery.picked.connect(self.review_snap)
        self.snap_gallery.viewed.connect(self.open_snap)
        self.snap_gallery.removed.connect(self.remove_snap)
        self.snap_gallery.setToolTip(tr('Foto prese da questo video.\nClic: il video torna su quel fotogramma per rivederlo.\nDoppio clic: mostra la foto intera, con stampabilità e correzioni.\n✕: toglie la foto da export (puoi riprenderla con F).'))
        # in basso a destra, sopra il numero di versione
        self.side_layout.insertWidget(self.side_layout.count() - 1, self.snaps_label)
        self.side_layout.insertWidget(self.side_layout.count() - 1, self.snap_gallery)
        self.side_layout.insertSpacing(self.side_layout.count() - 1, 6)
        self.photobook.opened.connect(lambda k: self.jump_to(next((i for i, it in enumerate(self.items) if it.id == k), -1)))
        self.decision_bar = QWidget()
        bottom = QHBoxLayout(self.decision_bar)
        bottom.setContentsMargins(0, 2, 0, 0)
        bottom.addStretch(1)
        bottom.addLayout(choices)   # sempre al centro, sotto la foto
        bottom.addStretch(1)
        lay.addWidget(self.decision_bar)
        self.thumbs_strip = ThumbStrip()
        self.thumbs_strip.setToolTip(tr('Le foto prima e dopo questa. Clic per andarci.\nIl pallino colorato è la scelta già fatta.'))
        self.thumbs_strip.picked.connect(self.jump_to)
        self.thumbs_strip.wanted.connect(self.request_strip_thumbs)
        self.bg.submit(thumbcache.prune)   # la cache delle miniature su disco non cresce all'infinito
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
        self.strip_filter_btn.setToolTip(tr('Quali miniature mostrare nella striscia in basso.\nQuella che stai guardando resta sempre visibile.'))
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
        self._strip_filter_btns: list[tuple[QPushButton, str, str]] = []
        for label, key in STRIP_FILTERS:
            fb = QPushButton(label)
            fb.setFocusPolicy(Qt.NoFocus)
            fb.setCursor(Qt.PointingHandCursor)
            fb.clicked.connect(lambda _=False, k=key, l=label: self._pick_strip_filter(k, l))
            _sfp_v.addWidget(fb)
            self._strip_filter_btns.append((fb, key, label))
        self._strip_filter_pop.setFixedWidth(240)
        _sfp_v.setSpacing(2)
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
        self.btn_locate = QPushButton(tr("⤳  Torna all'analisi"))
        self.btn_locate.setObjectName("stripnav")
        self.btn_locate.setToolTip(tr('Torna alla prima foto ancora da decidere\n(la prossima da giudicare)'))
        self.btn_locate.setFocusPolicy(Qt.TabFocus)
        self.btn_locate.setFixedWidth(220)
        self.btn_locate.clicked.connect(self.locate_thumb)
        left_col.addWidget(self.btn_locate, 0, Qt.AlignVCenter)
        for b in (self.strip_filter_btn, self.btn_locate):
            b.setFixedHeight(30)   # pillole arrotondate (raggio = metà altezza)
        # colonne laterali della stessa larghezza: la miniatura attuale resta al centro della finestra
        left_box = QWidget()
        left_box.setLayout(left_col)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_box.setFixedWidth(220)
        strip_row.addWidget(left_box, 0, Qt.AlignVCenter)
        # intorno alla striscia: frecce per scorrere avanti e indietro tra le miniature
        self.btn_thumb_prev = QPushButton("‹")
        self.btn_thumb_next = QPushButton("›")
        for b, step in ((self.btn_thumb_prev, -1), (self.btn_thumb_next, 1)):
            b.setObjectName("stripnav")
            b.setFixedSize(30, 30)
            b.setFocusPolicy(Qt.TabFocus)
            b.setToolTip(tr('Scorri le miniature indietro') if step < 0 else tr('Scorri le miniature avanti'))
            b.clicked.connect(lambda _=False, st=step: self.scroll_thumbs(st))
        strip_row.addWidget(self.btn_thumb_prev, 0, Qt.AlignVCenter)
        strip_row.addWidget(self.thumbs_strip, 1)
        strip_row.addWidget(self.btn_thumb_next, 0, Qt.AlignVCenter)
        self.btn_return = QPushButton(tr("⤳ Torna all'ultima"))
        self.btn_return.setToolTip(tr('Torna alla foto da cui sei tornato indietro (con ← o B).'))
        self.btn_return.setFocusPolicy(Qt.TabFocus)
        self.btn_return.setObjectName("stripnav")
        self.btn_return.setFixedSize(220, 30)
        self.btn_return.setVisible(False)
        self.btn_return.clicked.connect(self.return_to_last)
        right_box = QWidget()
        rb = QHBoxLayout(right_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.addWidget(self.btn_return, 0, Qt.AlignVCenter)
        right_box.setFixedWidth(220)
        strip_row.addWidget(right_box, 0, Qt.AlignVCenter)
        self.return_idx: int | None = None   # dove eri prima di tornare indietro
        self.came_from_home = False          # riaperta da ⌂ Riprendi: "Torna all'analisi" e frecce
        self.btn_locate.setProperty("home", "true")   # contorno giallo
        lay.addLayout(strip_row)

        self.dl_timer = QTimer(self)
        self.dl_timer.setInterval(500)
        self.dl_timer.timeout.connect(self.update_download_message)
        self.full_edit_timer = QTimer(self)   # Regola: la foto intera quando la mano si ferma
        self.full_edit_timer.setSingleShot(True)
        self.full_edit_timer.setInterval(450)
        self.full_edit_timer.timeout.connect(self.request_full_edit)
        self.thumbs_timer = QTimer(self)
        self.thumbs_timer.setSingleShot(True)
        self.thumbs_timer.setInterval(220)
        self.thumbs_timer.timeout.connect(self.make_thumbs)
        self.edit_save_timer = QTimer(self)
        self.edit_save_timer.setSingleShot(True)
        self.edit_save_timer.setInterval(600)
        self.edit_save_timer.timeout.connect(lambda: self.session and self.session.save())
        self.image_view.crop_changed.connect(self.on_view_crop)
        self.image_view.picked.connect(self.on_image_picked)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(90)
        self.preview_timer.timeout.connect(self.request_preview)

    def on_zoom_changed(self, t: float):
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(round(t * 100))
        self.zoom_slider.blockSignals(False)
        self.place_zoom()   # a foto ingrandita lo zoom resta visibile

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
        QTimer.singleShot(0, self.balance_top)

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
        for w in (self.side_details, self.side_sel, self.counter, self.snaps_label,
                  self.snap_gallery, self.save_head, self.save_info, self.save_row,
                  self.thumbs_strip, self.strip_filter, self.photobook):
            w.setVisible(browsing)
        self.update_locate_btn()   # frecce della striscia: solo dopo ⌂ Riprendi (come il pulsante)
        self.update_print_box()
        self.update_photo_arrows()

    def update_print_box(self):
        """Box Stampa: quanto regge la foto in stampa, e il pulsante per la copia migliorata."""
        item = self.current()
        m = self.meta.get(item.id) if item else None
        show = (item is not None and item.kind != "video" and m is not None and m.size is not None
                and self.stack.currentWidget() is not self.setup_page)
        self.print_box.setVisible(show)
        if show:
            level, text = printprep.verdict(*m.size)
            self.print_text.setText(f"<span style='color:{C['text_detail']}; font-weight:600'>{level.capitalize()}</span>  ·  {text}")
        has_copy = show and self.print_copy(item).is_file()
        self.btn_print_cmp.setVisible(has_copy)
        if not has_copy and self.btn_print_cmp.isChecked():
            self.btn_print_cmp.setChecked(False)   # la copia non c'è (o è un'altra foto): torna l'originale

    def print_copy(self, item) -> Path:
        """Dove sta la copia per la stampa di questa foto (l'originale non si tocca mai)."""
        return self.export_dir / "Stampa" / f"{item.main.stem}_stampa.jpg"

    def improve_for_print(self):
        """Migliora per la stampa: chiede conferma sotto il pulsante (Sì / Annulla)."""
        item = self.current()
        src = (item.image or item.raw) if item else None
        if not src or self.print_job is not None:   # già in preparazione: non se ne avvia un altro
            return
        self.print_ask.setText(tr("Creo la copia per la stampa in export/Stampa. L'originale non si tocca."))
        self.print_ask_row.show()

    def print_no(self) -> None:
        self.print_ask_row.hide()

    def print_yes(self) -> None:
        """Sì: scrive la copia in export/Stampa in background; l'originale non si tocca."""
        self.print_ask_row.hide()
        item = self.current()
        src = (item.image or item.raw) if item else None
        if not src or self.print_job is not None:
            return
        out = self.print_copy(item)
        self.print_job = item.id
        self.btn_print_fix.setEnabled(False)
        self.btn_print_fix.setText(tr('Preparo la copia per la stampa…'))
        self.print_busy.setRange(0, 0)   # finché il motore non dice la sua percentuale: animazione
        self.print_busy.show()
        self.status.setText(tr('Preparo la copia per la stampa… può richiedere qualche minuto'), ms=0)
        k = item.id
        progress = lambda f: self.bridge.progress.emit(k, f)   # noqa: E731
        edit = E.clean(self.item_edit(item.id)) if self.editable(item) else {}
        if edit and print_takes_edit():   # la copia per la stampa con le modifiche confermate
            self.submit("print", (item.id, out),
                        lambda: printprep.improve(src, out, progress, edit=edit), queue=self.print_q)
        else:
            self.submit("print", (item.id, out), printprep.improve, src, out, progress,
                        queue=self.print_q)

    def on_print_progress(self, key, f: float) -> None:
        """Avanzamento vero del motore di stampa: barra e percentuale."""
        if self.print_job != key:
            return
        self.print_busy.setRange(0, 1000)
        self.print_busy.setValue(int(f * 1000))
        self.status.setText(tr('Preparo la copia per la stampa… {v0}%', v0=int(f * 100)), ms=0)

    def set_print_compare(self, on: bool, quiet: bool = False) -> None:
        """Confronto con la copia per la stampa: la copia a schermo finché il pulsante è premuto.
        Tolto il confronto si torna alla foto com'è: con le modifiche confermate, se ce ne sono
        (le stesse con cui si fa la copia per la stampa)."""
        item = self.current()
        path = self.print_copy(item) if item else None
        if not on or path is None or not path.is_file():
            if self.edit_base is not None and self.edit_base_owner == (item.id if item else None):
                if self.editable(item) and not E.is_empty(self.view_edit()):
                    self.request_edit_render(sync=True)   # subito la versione modificata
                else:
                    self.invalidate_edit_renders()
                    self.image_view.set_image(self.edit_base, keep_zoom=True)
            edited = item is not None and self.editable(item) and not E.is_empty(self.item_edit(item.id))
            if not quiet:
                self.flash(tr("Modificata") if edited else tr("Originale"))
            return
        img = QImage(str(path))
        if img.isNull():
            self.btn_print_cmp.setChecked(False)
            return
        self.invalidate_edit_renders()   # i calcoli in corso non devono coprire la copia
        self.image_view.set_image(img, keep_zoom=True)   # stessa grandezza a schermo: si vedono i dettagli
        if not quiet:
            self.flash(tr("Copia per la stampa"))

    def update_btn_info(self):
        self.btn_info.setProperty("on", "true" if self.side_wanted else "false")
        self.btn_info.style().unpolish(self.btn_info)
        self.btn_info.style().polish(self.btn_info)

    # ------------------------------------------------------------------ Regola e Ritaglia
    def editable(self, item: Item | None = None) -> bool:
        """Regola e Ritaglia: foto, panorami, Live (la foto della Live) e, nei video, il
        fotogramma fermo (quello che 📷 Prendi foto salva)."""
        item = item or self.current()
        if item is None:
            return False
        if item.kind == "video":
            return self.scene_mode and item is self.current() and self.still_owner == item.id
        return item.kind in ("photo", "pano", "live")

    def edit_key(self, item: Item | None = None) -> str | None:
        """Dove stanno le modifiche: la foto, oppure il singolo fotogramma del video
        (la stessa chiave della foto presa, "video#fN")."""
        item = item or self.current()
        if item is None:
            return None
        return f"{item.id}#f{self.shown_frame}" if item.kind == "video" else item.id

    def item_edit(self, item_id: str | None = None) -> dict:
        if not self.session:
            return {}
        cur = self.current()
        if item_id is None or (cur is not None and item_id == cur.id):
            item_id = self.edit_key()
        return dict(self.session.edits.get(item_id, {})) if item_id else {}

    def store_edit(self, item_id: str, edit: dict) -> None:
        self.session.set_edit(item_id, edit)
        self.update_edit_ui()

    def on_side_tab(self, key: str) -> None:
        item = self.current()
        pending = "ritaglia" if self.crop_dirty() else "regola" if self.tone_dirty() else None
        if pending and key != pending:
            self.side_seg.set_current(pending)
            self.flash(tr('Prima conferma le modifiche con OK oppure Annulla'))
            return
        if key != "ritaglia" and self.crop_draft is not None:   # aperto senza cambiare nulla
            self._end_crop()
        if key != "regola" and self.tone_draft is not None:
            self.close_clean_drafts()
        if key != "info" and item is not None and item.kind == "video" and not self.editable(item):
            info = self.infos.get(item.id)
            if info:   # video in riproduzione: ci si ferma sul fotogramma che si vede
                self.set_frame(self.current_frame() or 0, manual=True)
            if not self.editable(item):
                self.side_seg.set_current(self.side_tab)
                self.flash(tr('Video: fermati sul fotogramma da salvare (pausa o clic sulla striscia), poi Regola o Ritaglia'))
                return
        if key != "info" and not (self.editable(item) and self.stack.currentWidget() is self.image_view
                                  or self.editable(item) and item.kind == "live"):
            self.side_seg.set_current(self.side_tab)
            self.flash(tr('Regola e Ritaglia: per foto, panorami, Live e il fotogramma fermo dei video'))
            return
        if key == "ritaglia" and item.kind == "live" and self.live_view:
            self.show_live_still()
            self.update_scene_controls()
        if key == "ritaglia" and self.edit_base_owner != item.id:
            self.side_seg.set_current(self.side_tab)
            self.flash(tr('Aspetta che la foto sia caricata'))
            return
        self.side_seg.set_current(key)
        if key == "ritaglia" and self.side_tab != "ritaglia":
            self._tab_before_crop = self.side_tab
        self.side_tab = key
        self.side_pages.setCurrentIndex({"info": 0, "regola": 1, "ritaglia": 2}[key])
        if not self.side.isVisible() and self.stack.currentWidget() is not self.setup_page:
            self.toggle_side()
        if key == "ritaglia" and self.crop_draft is None:
            self.start_crop()
        self.update_pick_mode()
        if key == "regola":
            self.update_thumbs()

    def _geometry(self, e: dict) -> dict:
        g = E.clean({k: v for k, v in e.items() if k in E.GEOMETRY_KEYS or k in ("aspect_custom", "aspect_portrait")})
        g.pop("aspect", None)   # scegliere le proporzioni senza spostare il riquadro non cambia la foto
        g.pop("aspect_custom", None)
        g.pop("aspect_portrait", None)
        return g

    def crop_dirty(self) -> bool:
        """Ritaglia aperto e la foto è davvero cambiata (riquadro, rotazione, prospettiva…)."""
        if self.crop_draft is None:
            return False
        d = dict(self.crop_draft)
        d["crop"] = list(self.image_view.crop)
        return self._geometry(d) != self._geometry(self.item_edit())

    def tone_dirty(self) -> bool:
        return self.tone_draft is not None and E.clean(self.tone_draft) != E.clean(self.item_edit())

    def edit_pending(self) -> bool:
        """Serve OK / Annulla solo se qualcosa è cambiato davvero."""
        return self.crop_dirty() or self.tone_dirty()

    def close_clean_drafts(self) -> None:
        """Ritaglia o Regola aperti senza aver cambiato nulla: si chiudono da soli."""
        if self.crop_draft is not None and not self.crop_dirty():
            self._end_crop()
        if self.tone_draft is not None and not self.tone_dirty():
            self.tone_draft = None
            self.regola.set_edit(self.item_edit())
        self.refresh_edit_lock()

    def refresh_edit_lock(self) -> None:
        self.set_crop_lock(self.edit_pending())

    def finish_edit(self) -> None:
        """Fine: conferma quello che è cambiato; se non è cambiato nulla chiude e basta."""
        if self.edit_pending():
            self.confirm_edit()
        else:
            self.close_clean_drafts()
        self.update_edit_ui()

    def confirm_edit(self) -> None:
        if self.crop_draft is not None:
            self.crop_ok()
        elif self.tone_draft is not None:
            self.regola_ok()

    def cancel_edit(self) -> None:
        if self.crop_draft is not None:
            self.crop_cancel()
        elif self.tone_draft is not None:
            self.regola_cancel()

    def regola_ok(self) -> None:
        item = self.current()
        if self.tone_draft is None or not item:
            return
        self.store_edit(self.edit_key(), self.tone_draft)
        self.tone_draft = None
        self.after_edit_confirmed()
        self.regola.set_edit(self.item_edit())
        self.set_crop_lock(False)
        self.request_edit_render()
        self.flash(tr('Modifiche confermate: ✓ Sì esporta la foto modificata'))

    def after_edit_confirmed(self) -> None:
        """Video: se questo fotogramma era già stato salvato con 📷, la foto in export si rifà
        con le modifiche nuove; se no, si ricorda di premere Prendi foto."""
        item = self.current()
        if not item or item.kind != "video":
            return
        key = self.edit_key()
        d = self.session.get(key)
        new = E.clean(self.session.edits.get(key, {}))
        if d is None or d["choice"] != "snap":
            if new:
                self.flash(tr('Modifiche pronte: 📷 Prendi foto (F) salva questo fotogramma modificato'))
            return
        if E.clean(d.get("edit") or {}) == new or not self.revert_effects(key, d):
            return
        d["files"] = []
        d.pop("stamps", None)
        if new:
            d["edit"] = new
        else:
            d.pop("edit", None)
        self.session.save()
        self.queue_export(item, d["frame"], key=key, snapshot=True)
        self.update_counter()
        self.flash(tr('📷 Foto del fotogramma {v0} rifatta con le modifiche', v0=d['frame'] + 1))

    def auto_enhance(self) -> None:
        """Bacchetta magica, come in Foto: Luce e Colore automatici in un clic (di nuovo = via).
        Diventa una modifica da confermare con OK, come le altre."""
        item = self.current()
        if self.crop_dirty():
            self.flash(tr('Prima conferma il ritaglio con OK oppure Annulla'))
            return
        if not self.editable(item):
            self.flash(tr('La bacchetta magica funziona su foto, panorami, Live e fotogrammi fermi dei video'))
            return
        if self.edit_base is None:   # foto (della Live) non ancora caricata: parte appena arriva
            self._wand_when_ready = item.id
            return
        if self.side_tab != "regola":
            self.on_side_tab("regola")
            if self.side_tab != "regola":
                return
        e = self.current_tone_edit()
        new = {k: v for k, v in e.items()
               if k not in E.SECTIONS["light"] + E.SECTIONS["color"] + ("enhanced",)}
        if e.get("enhanced"):
            self.regola.set_edit(new)
            self.on_regola_changed(new)
            self.flash(tr('Miglioramento automatico tolto: Conferma le modifiche'))
            return
        img = E.apply_crop(E.geometry_base(self.edit_proxy().convert("RGB"), e), e)
        new.update(E.auto_light(img))
        new.update(E.auto_color(img))
        new["enhanced"] = True
        new["off"] = [x for x in new.get("off", []) if x not in ("light", "color")]
        self.regola.set_edit(new)
        self.on_regola_changed(new)
        self.flash(tr("✨ Migliorata automaticamente: Conferma per tenerla, Annulla per lasciarla com'era"))

    def set_compare(self, on: bool) -> None:
        """□|□: l'originale a schermo finché il pulsante è premuto."""
        if self.edit_base is None or self.crop_draft is not None:
            return
        if on:
            self.invalidate_edit_renders()   # i calcoli in corso non devono coprire l'originale
            self.image_view.set_image(self.edit_base, keep_zoom=True)
        else:
            self.request_edit_render()
        # come in Foto: si dice sempre cosa si sta guardando
        self.flash(tr("Originale") if on else tr("Modificata"))
        self.btn_compare.setToolTip(tr("Stai guardando l'originale: clic per la versione modificata") if on
                                    else tr("Stai guardando la versione modificata: clic per l'originale"))

    def regola_cancel(self) -> None:
        if self.tone_draft is None:
            return
        self.tone_draft = None
        self.regola.set_edit(self.item_edit())
        self.set_crop_lock(False)
        if self.edit_base is not None:
            self.set_still(self.edit_base, self.edit_base_owner, keep_zoom=True)
        self.flash(tr('Modifiche annullate'))

    def update_pick_mode(self) -> None:
        on = self.side_tab == "regola" and self.regola.redeye_open() and self.editable()
        self.image_view.pick_enabled = on
        self.image_view.viewport().setCursor(Qt.CrossCursor if on else Qt.OpenHandCursor)

    def on_image_picked(self, x: float, y: float) -> None:
        if self.image_view.pick_enabled and self.crop_draft is None and self.editable():
            self.regola.add_redeye(x, y)

    def update_edit_ui(self) -> None:
        """Pulsanti e avvisi che dipendono dalle modifiche della foto corrente."""
        item = self.current()
        ok = self.editable(item) and self.stack.currentWidget() is not self.setup_page
        e = self.item_edit() if ok else {}
        has = not E.is_empty(e)
        crop, tone = self.crop_dirty(), self.tone_dirty()
        if not ok and not (crop or tone) and self.side_tab != "info" and item is not None \
                and item.kind == "video":   # il video riparte: si torna a Info
            self.crop_draft = self.tone_draft = None
            self.image_view.set_crop_mode(False)
            self.side_tab = "info"
            self.side_seg.set_current("info")
            self.side_pages.setCurrentIndex(0)
        self.side_seg.buttons["regola"].setEnabled(ok and not crop)
        self.side_seg.buttons["ritaglia"].setEnabled(ok and not tone)
        self.side_seg.buttons["info"].setEnabled(not (crop or tone))
        self.btn_discard.setEnabled(has or crop or tone)
        self.btn_edit_cancel_top.setVisible(crop or tone)
        self.btn_discard.setVisible(has or crop or tone)   # solo se c'è qualcosa da togliere (o da scartare)
        self.btn_confirm_foot.setVisible(ok and (crop or tone))
        self.side_foot.setVisible(ok and (has or crop or tone))
        changed = ok and (has or self.tone_draft is not None or self.crop_draft is not None)
        self.btn_restore.setVisible(changed)
        self.btn_restore.setEnabled(has or crop or tone)
        self.btn_compare.setVisible(changed and self.crop_draft is None)
        QTimer.singleShot(0, self.balance_top)
        if not self.btn_compare.isVisible() and self.btn_compare.isChecked():
            self.btn_compare.setChecked(False)
        self.btn_wand.setEnabled(ok and not crop)
        self.btn_wand.set_active(ok and bool(self.current_tone_edit().get("enhanced")))
        parts = []
        if E.has_tone(e):
            parts.append("regolata")
        if E.has_geometry(e):
            parts.append("ritagliata" if e.get("crop") else "raddrizzata")
        d = self.session.get(item.id) if (has and self.session and item) else None
        # una sola nota, e solo quando serve davvero: modificata DOPO averla già approvata
        if has and not (crop or tone) and d and d["choice"] == "yes" \
                and E.clean(d.get("edit") or {}) != E.clean(e):
            self.edit_badge.setText(tr("Modificata dopo il Sì: premi di nuovo ✓ per esportare questa versione"))
        else:
            self.edit_badge.setText("")
        self.edit_badge.setVisible(bool(self.edit_badge.text()))
        self.place_zoom()   # Ritaglia aperto o chiuso: lo zoom sparisce o torna

    def reset_edit_view(self) -> None:
        """Nuovo elemento: pannelli aggiornati sulle sue modifiche."""
        item = self.current()
        if self.btn_print_cmp.isChecked():   # la copia per la stampa era della foto precedente
            self.btn_print_cmp.setChecked(False)
        self.print_ask_row.hide()   # la conferma valeva per la foto precedente
        if self.edit_pending():   # non dovrebbe succedere (si cambia foto solo dopo OK / Annulla)
            self.crop_draft = self.tone_draft = None
            self.image_view.set_crop_mode(False)
            self.set_crop_lock(False)
        elif self.crop_draft is not None or self.image_view.crop_mode:
            # Ritaglia aperto senza cambiare nulla e poi un'altra foto: si chiude, non resta acceso
            self.crop_draft = None
            self.image_view.set_crop_mode(False)
            self.set_crop_lock(False)
        self.regola.set_edit(self.item_edit() if self.editable(item) else {})
        if self.btn_compare.isChecked():
            self.btn_compare.blockSignals(True)
            self.btn_compare.setChecked(False)
            self.btn_compare.blockSignals(False)
        if self.side_tab != "info" and not self.editable(item):
            self.side_tab = "info"
            self.side_seg.set_current("info")
            self.side_pages.setCurrentIndex(0)
        elif self.side_tab == "ritaglia":   # Ritaglia si riapre a mano: si torna dove si era
            back = self._tab_before_crop if self._tab_before_crop in ("info", "regola") else "info"
            self.side_tab = back
            self.side_seg.set_current(back)
            self.side_pages.setCurrentIndex({"info": 0, "regola": 1}[back])
        self.update_pick_mode()
        self.update_edit_ui()

    def set_still(self, img: QImage, item_id: str, keep_zoom: bool = False) -> None:
        """Ogni foto mostrata passa da qui: se ha modifiche si vede già modificata."""
        self.still_owner = item_id
        if self.edit_base_owner != item_id or self.edit_base is None \
                or self.edit_base.cacheKey() != img.cacheKey():
            self.edit_base, self.edit_base_owner = img, item_id
            self._edit_proxy = self._edit_tiny = None
        wand, self._wand_when_ready = getattr(self, "_wand_when_ready", None), None   # altra foto: annullata
        if wand == item_id:
            QTimer.singleShot(0, self.auto_enhance)
        item = self.item_by_id(item_id)
        key = self.edit_key(item) if item is not None else None
        if key != getattr(self, "_shown_edit_key", None):   # altro fotogramma del video: le sue modifiche
            self._shown_edit_key = key
            if not self.edit_pending():
                self.regola.set_edit(self.item_edit() if self.editable(item) else {})
        if not self.edit_pending() and (not self.editable(item) or E.is_empty(self.item_edit(item_id))):
            self.invalidate_edit_renders()   # niente da modificare: i calcoli in corso non valgono più
            self.image_view.set_image(img, keep_zoom=keep_zoom)
        else:
            self.request_edit_render(sync=True, keep_zoom=keep_zoom)
        if self.btn_print_cmp.isChecked() and item is not None and item is self.current():
            self.set_print_compare(True, quiet=True)   # confronto aperto: resta la copia a schermo
        if self.side_tab == "regola":
            self.update_thumbs()
        self.update_edit_ui()

    def edit_proxy(self):
        if self._edit_proxy is None and self.edit_base is not None:
            b = self.edit_base
            q = b.scaled(EDIT_PROXY, EDIT_PROXY, Qt.KeepAspectRatio, Qt.SmoothTransformation) \
                if max(b.width(), b.height()) > EDIT_PROXY else b
            self._edit_proxy = qimage_to_pil(q)
        return self._edit_proxy

    def current_tone_edit(self) -> dict:
        """Le regolazioni che si vedono: la bozza di Regola se c'è, se no quelle confermate."""
        return dict(self.tone_draft) if self.tone_draft is not None else self.item_edit(self.edit_base_owner)

    def view_edit(self) -> dict:
        e = self.current_tone_edit()
        if self.crop_draft is not None:
            for k in E.GEOMETRY_KEYS + ("aspect_custom", "aspect_portrait"):
                e.pop(k, None)
            e.update(self.crop_draft)
        return e

    def invalidate_edit_renders(self) -> None:
        """I calcoli di Regola in corso non devono più arrivare a schermo."""
        self.edit_gen += 1
        self._edit_floor = self.edit_gen

    def request_edit_render(self, sync: bool = False, keep_zoom: bool = True) -> None:
        if self.edit_base is None:
            return
        if not sync and self.btn_print_cmp.isChecked():   # si sta modificando: via il confronto
            self.btn_print_cmp.blockSignals(True)
            self.btn_print_cmp.setChecked(False)
            self.btn_print_cmp.blockSignals(False)
        self.edit_gen += 1
        e, crop = self.view_edit(), self.crop_draft is not None
        if sync:   # foto (o fotogramma) appena messa a schermo: niente calcoli vecchi sopra
            self._edit_floor = self.edit_gen
            try:
                res = render_edit_job(self.edit_proxy(), e, crop)
            except Exception as ex:  # noqa: BLE001
                log.error("modifica: %r", ex, exc_info=ex)
                self.image_view.set_image(self.edit_base, keep_zoom=keep_zoom)
                return
            self.image_view.set_image(pil_to_qimage(res), keep_zoom=keep_zoom)
            self.full_edit_timer.start()
            return
        if self._edit_busy:
            self._edit_again = True
            return
        self._edit_busy = True
        self.submit("edit", (self.edit_base_owner, self.edit_gen, False, self.shown_edit_key()), render_edit_job,
                    self.edit_proxy(), e, crop, queue=self.edit_pool)

    def request_full_edit(self) -> None:
        """Ferma la mano sui cursori: la foto intera, nitida anche con lo zoom."""
        b = self.edit_base
        if b is None or self.crop_draft is not None or self._edit_busy or self.btn_print_cmp.isChecked():
            return
        e = self.view_edit()
        if E.is_empty(e) or max(b.width(), b.height()) <= EDIT_PROXY or b.width() * b.height() > EDIT_FULL_MAX:
            return
        self.submit("edit", (self.edit_base_owner, self.edit_gen, True, self.shown_edit_key()),
                    lambda q, ed: E.render(qimage_to_pil(q), ed), b, e, queue=self.edit_pool)

    def shown_edit_key(self) -> str | None:
        """Le modifiche di cosa c'è a schermo: la foto, o il fotogramma del video (video#fN)."""
        item = self.item_by_id(self.edit_base_owner) if self.edit_base_owner else None
        return self.edit_key(item) if item is not None else None

    def on_edit_rendered(self, key, res) -> None:
        owner, gen, full, ekey = key
        if not full:
            self._edit_busy = False
        # vale solo per la stessa foto E lo stesso fotogramma (nei video l'id è uguale per tutti),
        # e mai se nel frattempo a schermo è andato altro (gen sotto il minimo)
        fresh = gen == self.edit_gen if full else gen >= self._edit_floor
        if not isinstance(res, Exception) and owner == self.edit_base_owner == self.still_owner \
                and fresh and ekey == self.shown_edit_key() \
                and self.stack.currentWidget() is self.image_view \
                and not self.btn_compare.isChecked() and not self.btn_print_cmp.isChecked():
            self.image_view.set_image(pil_to_qimage(res), keep_zoom=True)
        if not full:
            if self._edit_again:
                self._edit_again = False
                self.request_edit_render()
            else:
                self.full_edit_timer.start()

    def update_thumbs(self) -> None:
        self.thumbs_timer.start()

    def make_thumbs(self) -> None:
        """Le 5 miniature di Luce, Colore e Bianco e nero (come in Foto): dal più scuro al più chiaro."""
        if self.side_tab != "regola" or self.edit_base is None or not self.editable():
            return
        if self._edit_tiny is None:
            p = self.edit_proxy()
            k = 72 / max(1, p.height)
            self._edit_tiny = p.resize((max(1, round(p.width * k)), 72), Image.BILINEAR)
        e = self.current_tone_edit()
        base = E.apply_crop(E.geometry_base(self._edit_tiny, e), e)
        for sec in ("light", "color", "bw"):
            thumbs = []
            for v in (-1.0, -0.5, 0.0, 0.5, 1.0):
                e2 = dict(e)
                e2[sec] = v
                e2["off"] = [x for x in e.get("off", []) if x != sec]
                if sec == "bw":
                    e2["bw_on"] = True
                    e2["bw_neutrals"] = E.get(e, "bw_neutrals")
                if sec == "light" and v == 0 and not E.section_modified(e2, "light"):
                    e2["exposure"] = 1e-5   # stessa resa delle altre
                thumbs.append(pil_to_qimage(E.render_tone(base, e2)))
            self.regola.set_thumbs(sec, thumbs)

    def on_regola_changed(self, e: dict) -> None:
        item = self.current()
        if not self.editable(item) or self.crop_draft is not None:
            return
        keep = {k: v for k, v in self.item_edit().items()
                if k in E.GEOMETRY_KEYS or k in ("aspect_custom", "aspect_portrait")}
        new = {k: v for k, v in e.items() if k not in keep}
        new.update(keep)
        if self.btn_compare.isChecked():
            self.btn_compare.blockSignals(True)
            self.btn_compare.setChecked(False)
            self.btn_compare.blockSignals(False)
        self.tone_draft = E.clean(new)   # bozza: se cambia qualcosa si conferma con OK o Annulla
        self.refresh_edit_lock()
        self.request_edit_render()
        self.update_thumbs()
        self.update_edit_ui()

    def on_auto(self, sec: str) -> None:
        if self.edit_base is None or not self.editable():
            return
        e = self.current_tone_edit()
        img = E.apply_crop(E.geometry_base(self.edit_proxy().convert("RGB"), e), e)
        if sec == "light":
            vals = E.auto_light(img)
        elif sec == "color":
            vals = E.auto_color(img)
        elif sec == "wb":
            vals = E.auto_wb(img)
        elif sec == "bw":
            vals = {"bw_intensity": 0.2}
        elif sec == "levels":
            vals = E.auto_levels(img)
        elif sec == "definition":
            vals = E.auto_definition(img)
        elif sec == "noise":
            vals = E.auto_noise(self.edit_base_full_pil(e))
        elif sec == "sharpen":
            vals = E.auto_sharpen(self.edit_base_full_pil(e))
        elif sec == "deblur":
            vals = E.auto_deblur(self.edit_base_full_pil(e))
            if not vals:
                self.flash(tr('Sfocatura: la foto è già nitida'))
                return
        else:
            return   # Occhi rossi, Curve, Colore selettivo, Vignettatura: si regolano a mano
        self.regola.apply_auto(sec, vals)

    def edit_base_full_pil(self, e: dict):
        """Rumore e nitidezza si misurano sui pixel veri (al massimo 2400 px), non sull'anteprima."""
        b = self.edit_base
        q = b.scaled(2400, 2400, Qt.KeepAspectRatio, Qt.SmoothTransformation) \
            if max(b.width(), b.height()) > 2400 else b
        return qimage_to_pil(q)

    def reset_regola(self) -> None:
        e = self.current_tone_edit()
        keep = {k: v for k, v in e.items() if k in E.GEOMETRY_KEYS or k in ("aspect_custom", "aspect_portrait")}
        self.regola.set_edit(keep)
        self.on_regola_changed(keep)

    def discard_edits(self) -> None:
        """Annulla le modifiche: regolazioni e ritaglio tolti, torna l'originale."""
        item = self.current()
        if not item or not self.session:
            return
        if self.crop_draft is not None:
            self.crop_cancel()
        if self.tone_draft is not None:
            self.regola_cancel()
        if E.is_empty(self.item_edit()):
            return
        self.store_edit(self.edit_key(), {})
        self.after_edit_confirmed()
        self.regola.set_edit({})
        if self.edit_base is not None and self.edit_base_owner == item.id:
            self.invalidate_edit_renders()
            self.image_view.set_image(self.edit_base)
        self.update_thumbs()
        self.update_edit_ui()
        self.flash(tr("Modifiche annullate: si vede (ed esporta) l'originale"))

    # ---- Ritaglia: la bozza vale solo con OK; finché è aperto non si sceglie né si cambia foto
    def set_crop_lock(self, on: bool) -> None:
        for w in (self.decision_bar, self.nav_pill, self.fav_pill, self.scene_bar, self.thumbs_strip,
                  self.btn_thumb_prev, self.btn_thumb_next, self.strip_filter_btn,
                  self.btn_return, self.zoom_pill):
            w.setEnabled(not on)
        for w in (self.decision_bar, self.scene_bar, self.thumbs_strip, self.btn_thumb_prev, self.btn_thumb_next, self.strip_filter_btn):
            hide_keep_space(w, on)
        self.update_photo_arrows()
        self.update_locate_btn()
        self.btn_locate.setEnabled(not on and not self.locate_is_here())
        self.update_edit_ui()

    def crop_ratio(self) -> float | None:
        f = self.image_view.full
        if self.crop_draft is None or f.isNull():
            return None
        return E.aspect_ratio(self.crop_draft, f.width(), f.height())

    def start_crop(self) -> None:
        e = self.item_edit()
        self.crop_draft = {k: v for k, v in e.items()
                           if k in E.GEOMETRY_KEYS or k in ("aspect_custom", "aspect_portrait")}
        if self.edit_base is not None:
            self.ritaglia._landscape_photo = self.edit_base.width() >= self.edit_base.height()
        self.ritaglia.set_draft(self.crop_draft)
        self.request_edit_render(sync=True, keep_zoom=False)
        self.image_view.set_crop_mode(True, self.crop_draft.get("crop"), self.crop_ratio())

    def on_crop_draft(self, d: dict) -> None:
        if self.crop_draft is None:
            return
        d["crop"] = self.image_view.crop if d else None
        if not d:   # Reimposta
            self.image_view.crop = [0.0, 0.0, 1.0, 1.0]
        self.crop_draft = d
        self.request_edit_render(sync=True, keep_zoom=False)
        ratio = self.crop_ratio()
        f = self.image_view.full
        if ratio:
            d["crop"] = E.fit_aspect(d.get("crop"), ratio, f.width(), f.height())
        self.image_view.set_crop_mode(True, d.get("crop"), ratio)
        self.ritaglia.set_crop(d.get("crop"))
        self.refresh_edit_lock()

    def on_crop_aspect(self, d: dict) -> None:
        if self.crop_draft is None:
            return
        d["crop"] = self.image_view.crop
        self.crop_draft = d
        f = self.image_view.full
        ratio = self.crop_ratio()
        if ratio:   # il riquadro più grande con quelle proporzioni, come in Foto
            d["crop"] = E.fit_aspect(None, ratio, f.width(), f.height())
        self.image_view.set_crop_mode(True, d["crop"], ratio)
        self.ritaglia.set_crop(d["crop"])
        self.refresh_edit_lock()

    def on_view_crop(self, crop: list) -> None:
        if self.crop_draft is not None:
            self.crop_draft["crop"] = crop
            self.ritaglia.set_crop(crop)
            self.refresh_edit_lock()

    def crop_auto(self) -> None:
        if self.crop_draft is None or self.edit_base is None:
            return
        # come ShiftN / darktable: prima le linee che convergono (Verticale), poi l'orizzonte
        d = dict(self.crop_draft)
        for k in ("straighten", "vertical", "horizontal"):
            d.pop(k, None)
        src = self.edit_proxy().convert("RGB")
        d.update(E.auto_perspective(E.geometry_base(src, d)))
        d["straighten"] = E.auto_straighten(E.geometry_base(src, d))
        self.ritaglia.set_draft(d)
        self.on_crop_draft(dict(self.ritaglia.draft))
        a, v = d["straighten"], E.get(d, "vertical")
        parts = ([tr('raddrizzata di {a:+.1f}°', a=a).replace(".", ",")] if a else []) + \
                ([f"verticali corrette ({round(v * 30):+d}°)"] if v else [])
        self.flash((tr('Automatico: ') + ", ".join(parts)) if parts else tr('Automatico: è già dritta'))

    def _end_crop(self) -> None:
        self.crop_draft = None
        self.image_view.set_crop_mode(False)
        self.set_crop_lock(False)
        back = self._tab_before_crop if self._tab_before_crop != "ritaglia" else "info"
        self.side_tab = back
        self.side_seg.set_current(back)
        self.side_pages.setCurrentIndex({"info": 0, "regola": 1}[back])
        self.update_pick_mode()
        if self.edit_base is not None:
            self.set_still(self.edit_base, self.edit_base_owner)

    def crop_ok(self) -> None:
        item = self.current()
        if self.crop_draft is None or not item:
            return
        d = dict(self.crop_draft)
        d["crop"] = list(self.image_view.crop)
        e = {k: v for k, v in self.item_edit().items()
             if not (k in E.GEOMETRY_KEYS or k in ("aspect_custom", "aspect_portrait"))}
        e.update(d)
        self.store_edit(self.edit_key(), e)
        self.after_edit_confirmed()
        self.regola.set_edit(self.item_edit())
        self._end_crop()
        self.flash(tr('Ritaglio confermato: ✓ Sì esporta la foto ritagliata'))

    def crop_cancel(self) -> None:
        if self.crop_draft is None:
            return
        self._end_crop()
        self.flash(tr('Ritaglio annullato'))

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
        if getattr(self, "btn_help", None) is not None:
            # finestra stretta: il nome del file resta leggibile; l'aiuto resta in ⚙ e coi tasti ? / H
            self.btn_help.setVisible(self.width() >= 1180)
        if getattr(self, "btn_home", None) is not None:   # finestra stretta: il nome del file ha la precedenza (tasto Home)
            self.btn_home.setVisible(self.width() >= 1180)
        if getattr(self, "photo_prev", None) is not None:
            self.place_photo_arrows()
        self.balance_top()
        QTimer.singleShot(0, self.balance_top)   # di nuovo quando le misure si sono assestate

    def balance_top(self) -> None:
        """Barra in alto: colonne laterali larghe uguali, così nome e data stanno davvero al centro
        della foto (finché c'è posto: in una finestra stretta vince la leggibilità del nome)."""
        if getattr(self, "top_grid", None) is None:
            return
        total = self.top_grid.geometry().width() or (self.width() - 28)
        name = self.heading.sizeHint().width()
        extras = sum(w.sizeHint().width() + 8 for w in (self.badge, self.chosen_tag) if not w.isHidden())
        # al centro esatto solo se il nome resta leggibile (almeno ~160 px, oltre alle etichette)
        thr = extras + min(name, 160) + 16
        # finestra stretta: "Ripristina originale" diventa solo ↺ (stessa funzione, testo nel suggerimento)
        for compact in (False, True):
            self.btn_restore.setText("↺" if compact else tr("Ripristina originale"))
            self.btn_restore.setProperty("compact", "true" if compact else "false")
            self.btn_restore.style().unpolish(self.btn_restore)
            self.btn_restore.style().polish(self.btn_restore)
            self.btn_restore.updateGeometry()
            self.top_left.invalidate()
            lw, rw = self.top_left.sizeHint().width(), self.top_right.sizeHint().width()
            centered = total - 2 * max(lw, rw) - 2 * 8    # spazio se il titolo è al centro esatto
            if centered >= thr or not self.btn_restore.isVisible():
                break
        g = self.top_grid
        # le colonne laterali non si restringono sotto i propri pulsanti: il titolo non le copre
        g.setColumnMinimumWidth(0, lw)
        g.setColumnMinimumWidth(2, rw)
        g.removeWidget(self.title_box)
        if centered >= thr:
            # c'è posto: centrato sulla finestra, come le barre di macOS
            g.addWidget(self.title_box, 0, 0, 1, 3, Qt.AlignHCenter | Qt.AlignVCenter)
            self.title_box.setMaximumWidth(max(0, centered))
        else:
            # finestra stretta: tra i due gruppi di pulsanti, un po' fuori centro ma leggibile
            g.addWidget(self.title_box, 0, 1, Qt.AlignHCenter | Qt.AlignVCenter)
            self.title_box.setMaximumWidth(max(0, total - lw - rw - 2 * 8))

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "choice_btns", None):
            self.layout_choices()

    def eventFilter(self, obj, e):
        if obj is getattr(self, "video_widget", None) and e.type() == QEvent.MouseButtonRelease \
                and e.button() == Qt.LeftButton:
            self.on_media_click()
        if e.type() == QEvent.EnabledChange and obj in getattr(self, "cap_of", {}):
            self.cap_of[obj].setEnabled(obj.isEnabled())
        if obj is self.stack and e.type() in (QEvent.Enter, QEvent.Leave):
            self._over_photo = e.type() == QEvent.Enter
            self.place_zoom()
        if obj is self.stack and e.type() == QEvent.Resize:
            self.warn.place()
            self.status.place()
            self.place_stamp()
            self.place_snap_bar()
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
        title = QLabel(tr('Nuova selezione') + f"   <span style='font-size:13px; color:{C['text_2']}; font-weight:400'>"
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

        self.src_label, _ = step(
            "①", tr('Cartella da guardare'),
            tr('La cartella copiata dalla scheda SD (per esempio DCIM). Vengono lette anche tutte le sottocartelle.'),
            tr('Scegli cartella…'), self.pick_source)
        self.dst_label, self.btn_pick_dst = step(
            "②", tr('Cartella export: dove copiare quelle approvate'),
            tr('Le foto approvate vengono copiate qui, i video nella sottocartella “Video”. Gli originali non vengono mai spostati né modificati.'),
            tr('Scegli cartella…'), self.pick_destination)
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
        self.btn_start = QPushButton(tr('Inizia  ▶'))
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
        self.src_label.setText(str(self.pick_root) if self.pick_root else tr('— nessuna cartella scelta —'))
        if self.pick_export:
            self.dst_label.setText(str(self.pick_export))
        elif self.pick_root:
            self.dst_label.setText(f"{self.pick_root / 'export'}   " + tr('(proposta)'))
        else:
            self.dst_label.setText(tr('— prima scegli la cartella da guardare —'))
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
            tr('💽 Cartella su disco (non su iCloud): nessun download, si parte subito.') if local else
            tr('☁️ Questa cartella ha file su iCloud: ogni originale verrà scaricato quando lo apri '
               '(qualità sempre massima, ma con attesa). Per andare veloci usa una cartella su disco.')
            if on_cloud else "")
        self.btn_start.setEnabled(self.pick_root is not None)
        last = self.settings_store.value("last_root", "")
        last_exp = self.settings_store.value("last_export", "")
        self.btn_resume.setVisible(bool(last))
        if last:
            self.btn_resume.setText(tr("↻  Riprendi l'ultima sessione:  {v0}  →  {v1}", v0=Path(last).name,
                                       v1=Path(last_exp).name if last_exp else 'export'))
            self.btn_resume.setToolTip(tr('Da: {last}\nExport: {last_exp}', last=last, last_exp=last_exp))

    def pick_source(self):
        start = str(self.pick_root or self.settings_store.value("last_root", "") or Path.home())
        d = QFileDialog.getExistingDirectory(self, tr('①  Scegli la cartella con foto e video da guardare'),
                                             start)
        if d:
            self.pick_root = Path(d)
            self.pick_export = None
            self.refresh_setup()
            self.ask_about_saved_work(self.pick_root)

    def ask_about_saved_work(self, root: Path):
        """Cartella già lavorata: mostra lo stato e chiede se riprendere."""
        last_root = self.settings_store.value("last_root", "")
        last_exp = self.settings_store.value("last_export", "")
        hint = Path(last_exp) if last_exp and last_root == str(root) else None
        info = exporter.Session.peek(root, export=hint)   # anche un salvataggio rimasto solo in export
        if not info:
            return
        c = info["counts"]
        fw = exporter.fmt_when
        total = info["total"] or "?"
        detail = (f"Decise: {info['decided']} su {total}\n"
                  f"✓ {c['yes']} approvate   ✗ {c['no']} scartate   ↪ {c['skip']} saltate"
                  + (f"   🗑 {c['trash']} in “cancellare”" if c.get("trash") else "")
                  + (tr('   📷 {v0} foto da video', v0=c['snap']) if c.get("snap") else "") + tr('\n\nIniziato il {v0}\nUltima modifica il {v1}\nExport: {v2}', v0=fw(info['created']), v1=fw(info['updated']), v2=info['export'])
                  + ("" if info.get("export_ok", True) else
                     tr("\n(questa cartella export non c'è su questo computer: riprendendo ti chiedo dove copiare)")))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        if info["completed"]:
            box.setWindowTitle(tr('Lavoro completato'))
            box.setText(tr('<b>Questa cartella è già stata completata</b> (chiuso il {v0}).<br>Vuoi riaprirla?', v0=fw(info['closed'] or info['updated'])))
            resume = box.addButton(tr('Riapri'), QMessageBox.AcceptRole)
        else:
            box.setWindowTitle(tr('Lavoro non completato'))
            when = fw(info["closed"] or info["updated"])
            box.setText(tr("<b>In questa cartella c'è un lavoro a metà</b> (interrotto il {when}).<br>Vuoi riprendere da dove eri?", when=when))
            resume = box.addButton(tr('Riprendi da dove eri'), QMessageBox.AcceptRole)
        box.setInformativeText(detail)
        restart = box.addButton(tr('Ricomincia da capo'), QMessageBox.DestructiveRole)
        box.addButton(tr('Annulla'), QMessageBox.RejectRole)
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
                    tr("Le scelte salvate verranno riprese. La cartella export di allora ({v0}) non c'è su questo computer: scegli dove copiare le prossime con ②, poi Inizia.", v0=info['export']))
                self.setup_note.setVisible(True)
                return
            self.pick_export = Path(info["export"])
            self.start_from_setup()
        elif clicked is restart:
            sure = QMessageBox.question(
                self, tr('Ricomincia da capo'),
                tr('Le scelte salvate verranno messe da parte (il file viene rinominato, non cancellato).\nLe foto già copiate in export restano dove sono.\n\nContinuare?'))
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
            self, tr('②  Scegli (o crea con “Nuova cartella”) dove copiare le approvate'), str(start))
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
            "C": self.toggle_scene, "Left": self.go_back, "Right": self.go_forward,
            "Shift+Up": lambda: self.step(-10), "Shift+Down": lambda: self.step(10),
            "P": self.pick_sharpest, "R": self.reset_frame, "Space": self.play_pause,
            "?": self.show_help, "H": self.show_help, "V": self.replay, "L": self.toggle_live, "F": self.take_photo,
            "Up": lambda: self.nav_frame(-1), "B": self.go_back, "Home": self.go_home,
            "Down": lambda: self.nav_frame(1), ".": self.toggle_favorite,
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

        def unless_cropping(k, fn):
            # Ritaglia aperto: Invio = OK, il resto aspetta (si conferma o si annulla prima)
            def run():
                if not self.edit_pending() or k in ("?", "H", "I"):
                    fn()
                elif k in ("Return", "Enter"):
                    self.confirm_edit()
                else:
                    self.flash(tr('Prima conferma le modifiche con OK oppure Annulla'))
            return run

        QShortcut(QKeySequence("Escape"), self, activated=self.cancel_edit)
        for k, fn in keys.items():
            fn = unless_cropping(k, fn)
            if k in ("Return", "Enter", "Space"):
                fn = press_focused_or(fn)
            sc = QShortcut(QKeySequence(k), self, activated=fn)
            sc.setAutoRepeat(k in ("Up", "Down", "Shift+Up", "Shift+Down"))   # fotogramma per fotogramma

    def save_prefs(self):
        self.settings_store.setValue("fmt", self.current_settings().fmt)
        tz = self.tz.currentData()
        self.settings_store.setValue("tz", "" if tz is None else tz)

    def current_settings(self, with_video: bool = False) -> exporter.Settings:
        return exporter.Settings(fmt="png16" if self.fmt.currentIndex() == 1 else "jpeg",
                                 copy_video=with_video,
                                 tz_override_hours=self.tz.currentData())

    # ------------------------------------------------------------------ lavori in background
    # risultati che valgono solo per la cartella aperta quando sono stati chiesti
    _SCAN_BOUND = ("analyze", "meta", "thumb", "strip", "ready", "proxy")

    def submit(self, kind: str, key, fn, *args, queue=None) -> Future:
        fut = (queue or self.bg).submit(fn, *args)
        gen = self._scan_gen

        def finished(f: Future):
            if f.cancelled():   # tolto dalla coda prima di partire: nessun risultato
                return
            try:
                res = f.result()
            except Exception as e:  # noqa: BLE001 - mostrato all'utente
                res = e
            if gen != self._scan_gen:   # chiesto per la cartella aperta prima
                if kind in self._SCAN_BOUND:
                    return
                if kind == "preview":
                    res = StaleResult()   # libera la coda delle anteprime senza mostrarla
            self.bridge.done.emit(kind, key, res)
        fut.add_done_callback(finished)
        return fut

    def on_done(self, kind: str, key, res):
        if kind == "edit":
            if isinstance(res, Exception):
                log.error("modifica %s: %r", key, res, exc_info=res)
            self.on_edit_rendered(key, res)
            return
        # schermata iniziale aperta: i risultati si conservano ma non cambiano cosa si vede
        cur = self.current() if self.stack.currentWidget() is not self.setup_page else None
        if isinstance(res, Exception) and not isinstance(res, StaleResult):
            log.error("%s %s: %r", kind, key, res, exc_info=res)
        elif kind in ("scan", "ready", "export"):
            log.info("%s %s: %s", kind, key if kind != "scan" else self.root,
                     f"{len(res)} elementi" if kind == "scan" else res)
        if kind == "scan":
            self.on_scanned(res)
        elif kind == "ready":
            # "now" (l'elemento che guardi) e "pre" (anticipo) sono lavori distinti: un anticipo
            # non riuscito non tocca l'attesa di quello corrente e non mostra errori
            item_id, which, token = key
            jkey = ("ready-now" if which == "now" else "ready-pre", item_id)
            job = self._ready_jobs.get(jkey)
            if job is not None and job[2] == token:
                del self._ready_jobs[jkey]
                self.pending.discard(jkey)
            elif not isinstance(res, Exception):
                pass   # lavoro lasciato ma finito bene: il file c'è, vale comunque
            else:
                return   # lavoro lasciato (o sostituito): il suo esito non conta
            if isinstance(res, Exception):
                if which == "now" and cur and cur.id == item_id \
                        and not isinstance(res, StaleResult):
                    self.show_message(tr('Download da iCloud non riuscito:\n{res}', res=res))
                return  # anticipo non riuscito: si riprova quando l'elemento viene aperto
            was_ready = item_id in self.ready
            self.ready.add(item_id)
            it = self.item_by_id(item_id)
            if it is not None and refresh_capture_time(it) and cur and cur.id == item_id and was_ready:
                self.update_item_labels()   # data vera dall'EXIF, ora che il file è scaricato
            if cur and cur.id == item_id and not was_ready:
                self.show_item()
        elif kind == "analyze":
            self.pending.discard(("analyze", key))
            if isinstance(res, Exception):
                self.status.setText(tr('Analisi video non riuscita: {res}', res=res))
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
        elif kind == "proxy":
            self.on_proxy(key, res)
        elif kind == "meta":
            self.pending.discard(("meta", key))
            self.meta[key] = res if not isinstance(res, Exception) else metadata.Meta()
            if cur and (cur.id == key or key in self.burst_ids):   # anche un vicino: la raffica
                self.update_item_labels()
        elif kind == "thumb":
            ok = not isinstance(res, Exception) and not res.isNull()
            self.thumb_q.arrived(key, ok)
            if ok:
                self.next_thumbs[key] = res
                if key in self._strip_idx:   # solo lei nella striscia, senza ricostruirla
                    self.thumbs_strip.set_thumb(self._strip_idx[key], res)
            elif not self.thumb_q.gave_up(key):   # riprova tra poco (file ancora a metà, iCloud…)
                QTimer.singleShot(int(ThumbQueue.RETRY_S * 1000) + 50, self.thumbs_strip.ask_shown)
        elif kind == "rename":
            self.on_renamed(res)
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
        elif kind == "print":
            item_id, out = key
            self.print_job = None
            self.btn_print_fix.setEnabled(True)
            self.btn_print_fix.setText(tr('Migliora per la stampa'))
            self.print_busy.hide()
            if isinstance(res, InterruptedError):
                pass   # interrotta dall'uscita: niente da dire
            elif isinstance(res, Exception):
                self.flash(tr('Non riesco a preparare questa foto per la stampa'))
            else:
                self.flash(tr('Copia per la stampa salvata: {v0}  ({v1})', v0=out.name, v1=res))
                if self.btn_print_cmp.isChecked():   # confronto aperto: mostra la copia appena fatta
                    self.set_print_compare(True)
            self.update_print_box()
        elif kind == "sharpest":
            self._sharp_busy = False
            self.btn_sharp.setEnabled(True)
            item_id, start = key
            # vale solo se sei ancora sul fotogramma da cui hai chiesto: se intanto ti sei
            # spostato (→, striscia, altro elemento) il risultato non ti riporta indietro
            if not cur or cur.id != item_id or self.current_frame() != start:
                return
            if isinstance(res, Exception):
                self.status.setText(tr('Non riesco a cercare il fotogramma più nitido'), ms=3500)
                self.update_scene_controls()   # l'etichetta non resta su "cerco…"
            elif res == start:
                self.update_scene_controls()
                self.flash(tr('Questo è già il fotogramma più nitido qui vicino'))
            else:
                self.set_frame(res, manual=True)
        elif kind == "export":
            item_id, _, token = key
            # l'esito vale solo per la decisione che ha avviato questo export (non annullata,
            # non rifatta, stessa cartella); un errore non cancella la scelta
            outcome = self.session.record_export(item_id, token, res) if self.session else "stale"
            if outcome == "failed":
                self.status.setText(tr('Export non riuscito per {v0}: {res} (la scelta resta: si riprova alla prossima apertura)', v0=Path(item_id).name, res=res))
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
            self.show_setup(tr("La cartella dell'ultima sessione non è raggiungibile (disco scollegato?)."))

    def show_help(self):
        # finestra che si scorre: il testo è lungo e non deve uscire dallo schermo
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('Come funziona') + f" — {APP_TITLE}")
        v = QVBoxLayout(dlg)
        text = QTextBrowser()
        text.setHtml(help_html(HELP_TEXT))
        text.setStyleSheet(f"QTextBrowser {{ background: {C['bg_panel']}; border: 1px solid {C['line_divider']};"
                           " border-radius: 10px; padding: 10px; font-size: 13px; }")
        v.addWidget(text, 1)
        row = QHBoxLayout()
        logs = QPushButton(tr('Mostra il file di log'))
        logs.clicked.connect(self.reveal_log)
        close = QPushButton(tr('Chiudi'))
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
        d = QFileDialog.getExistingDirectory(self, tr('Cartella dove copiare le scelte'),
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
        self.btn_export.setText(tr('Export: {v0}', v0=self.export_dir.name))
        self.btn_export.setToolTip(tr('Le foto approvate vengono copiate in:\n{v0}', v0=self.export_dir))
        self.show_message(tr('Lettura della cartella…'))
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
            self.show_setup(tr('Errore nella lettura della cartella: {res}', res=res))
            return
        self.items = res
        # un'altra cartella (o la stessa riletta): gli id sono percorsi relativi e si ripetono
        # tra schede diverse (DCIM/100MEDIA/DJI_0001.MP4), quindi niente dati dell'apertura prima
        self._scan_gen += 1
        for k in list(self._ready_jobs):   # download chiesti per la cartella di prima
            self.drop_ready_job(k)
        for cache in (self.infos, self.camera_frames, self.meta, self.thumbs, self.next_thumbs,
                      self.exact_cache, self.proxy_frames, self.pending, self.thumb_q):
            cache.clear()
        self.export_q.submit(self.copy_paths.clear)   # copy_paths: solo dalla coda export
        # copie finite: l'esito è già nel salvataggio; un id uguale nella cartella nuova non è lo stesso
        self.export_futures = {k: f for k, f in self.export_futures.items() if not f.done()}
        self.return_idx = None
        self.btn_return.setVisible(False)
        if self.session:
            self.session.close()
            self.session = None
        try:
            self.session = exporter.Session(self.root, self.export_dir, ids=[it.id for it in res])
        except OSError as e:  # salvataggio presente ma illeggibile: non si salva sopra
            self.show_setup(tr('Impossibile leggere il lavoro salvato in questa cartella: {e}', e=e))
            return
        try:
            self.session.save()
        except OSError as e:   # né nella cartella né in export: meglio non iniziare senza salvare
            self.show_setup(tr('Non riesco a salvare il lavoro ({v0}). Scegli un\'altra cartella export.', v0=e))
            self.session = None
            return
        if self.session.saved_elsewhere:
            QMessageBox.information(
                self, APP_TITLE, tr('La cartella non è scrivibile: il lavoro si salva in\n{v0}',
                                    v0=self.session.saved_elsewhere))
        if self.session.corrupt_backup:
            QMessageBox.warning(
                self, APP_TITLE,
                tr("Il lavoro salvato in questa cartella era danneggiato e non si è potuto leggere.\n"
                   "È stato conservato come:\n{v0}\n\n"
                   "Si riparte senza le scelte precedenti. I file in “cancellare” sono ancora lì.",
                   v0=self.session.corrupt_backup))
        self.history.clear()
        self.export_q.submit(exporter.clean_partial, self.export_dir)   # dopo gli export in corso
        self.ready.clear()
        self.review_skipped = False
        if not self.items:
            self.show_setup(tr('Nessuna foto o video trovati in questa cartella.'))
            return
        by_id = self._by_id = {it.id: it for it in self.items}
        # copie mai finite (app chiusa o export fallito): si rifanno. Non si cancella nulla.
        pending = self.session.pending_exports(by_id)
        export_warning = ""
        if pending and not exporter.export_reachable(self.export_dir):
            export_warning = (tr('⚠ Cartella export non raggiungibile ({v0}): {v1} copie in sospeso verranno rifatte alla prossima apertura', v0=self.export_dir, v1=len(pending)))
            log.warning(export_warning)
            pending = []
        for key in pending:
            d = self.session.decisions[key]
            self.queue_export(by_id[key.split("#")[0]], d.get("frame"), key=key,
                              snapshot=d["choice"] == "snap",
                              with_video=d.get("with_video", False))
        if not export_warning:
            self.tidy_exports()   # copie delle versioni di prima: in Foto / Video, con la data
        self.idx = self.next_index(-1)
        # tornando dalla home: si riparte dalla foto in cui eri, una volta sola
        home_root = self.settings_store.value("home_root", "")
        home_id = self.settings_store.value("home_id", "")
        self.settings_store.remove("home_root")
        self.settings_store.remove("home_id")
        self.came_from_home = False
        if home_root == str(self.root) and home_id:
            pos = next((i for i, it in enumerate(self.items) if it.id == home_id), None)
            if pos is not None:
                self.idx = pos
                self.came_from_home = True   # "Torna all'analisi" e frecce compaiono solo da qui
        done = sum(1 for it in self.items if self.session.get(it.id) is not None)
        if export_warning:
            self.status.setStyleSheet(f"color:{C['text_warn']};")
            self.status.setText(export_warning, ms=0)   # importante: resta finché non si cambia elemento
        elif done:
            self.status.setStyleSheet(f"color:{C['text_ok']};")
            self.status.setText(tr('Ripreso da dove eri: {done} già decise', done=done))
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
        """Filtro "solo foto": i video normali si nascondono (le Live sono foto).
        Filtro "solo video": si vedono solo i video normali (Live, foto e panorami si nascondono)."""
        if self.media_filter == "photos":
            return item.kind != "video"
        if self.media_filter == "videos":
            return item.kind == "video"
        return True

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
        self.snap_key = None   # la foto presa resta solo su quel video
        self.snap_bar.hide()
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
        self.reset_edit_view()
        self.update_counter()
        self.update_locate_btn()
        self.btn_locate.setEnabled(not self.locate_is_here())
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
                    self.show_message(tr('Anteprima non disponibile per {v0}\nSÌ copia comunque il DNG originale in export.', v0=item.main.name))
                else:
                    self.show_message(tr('Impossibile aprire {v0}', v0=item.main.name))
                return
            self.set_still(img, item.id)
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
            if cloud.is_local(item.video):
                orig = frames.probe(item.video)   # una volta sola
                dims = (orig.width, orig.height)
            else:
                dims = frames.spotlight_dims(item.video)
            info.original_dims = dims
        return info, cam

    # attesa prima di avviare i download dell'elemento corrente: scorrendo veloce non si
    # scaricano gli elementi solo sfiorati (l'anticipo dei successivi li prende comunque)
    READY_DELAY_S = 0.15

    def request_ready(self, item: Item, now: bool = True):
        """Scarica i file dell'elemento. now=True: è quello che stai guardando, ha la precedenza
        (thread suoi, mai in coda dietro agli altri); now=False: anticipo dei successivi,
        max 2 download alla volta."""
        if now:   # gli elementi lasciati non aspettano più: la loro attesa finisce
            for k in [k for k in self._ready_jobs if k[0] == "ready-now" and k[1] != item.id]:
                self.drop_ready_job(k)
        key = ("ready-now" if now else "ready-pre", item.id)
        job = self._ready_jobs.get(key)
        if key in self.pending and job is not None and not job[1].is_set():
            return
        self.pending.add(key)
        files = [p for p in item.needed_files() if not cloud.is_local(p)]
        abandon = threading.Event()
        token = uuid.uuid4().hex
        # registrato PRIMA di partire: un esito immediato (callback nello stesso thread) lo trova
        job_entry = [None, abandon, token]
        self._ready_jobs[key] = job_entry
        if now:
            fut = self.submit("ready", (item.id, "now", token), wait_downloads, files, abandon,
                              self.READY_DELAY_S, queue=self.waiters)
        else:
            def job(files=files, abandon=abandon):
                for p in files:  # uno dopo l'altro: non toglie banda all'elemento corrente
                    if abandon.is_set():
                        raise AbandonedWait()
                    if not cloud.download(p):
                        raise RuntimeError(tr('{v0} non disponibile', v0=p.name))
                return True
            fut = self.submit("ready", (item.id, "pre", token), job, queue=self.pre)
        job_entry[0] = fut

    def drop_ready_job(self, key: tuple[str, str]) -> None:
        """Lascia un download: tolto dalla coda se non è partito, altrimenti finisce appena può."""
        job = self._ready_jobs.pop(key, None)
        self.pending.discard(key)
        if job is not None:
            job[1].set()
            if job[0] is not None:
                job[0].cancel()

    def prefetch(self):
        i, n = self.idx, 0
        window: list[Item] = []
        while n < PREFETCH:
            i = self.next_index(i)
            if i >= len(self.items):
                break
            window.append(self.items[i])
            n += 1
        ids = {it.id for it in window}
        # anticipi non più tra i prossimi PREFETCH (sei andato indietro, o saltato avanti)
        for k in [k for k in self._ready_jobs if k[0] == "ready-pre" and k[1] not in ids]:
            self.drop_ready_job(k)
        for it in window:
            if it.id not in self.ready and not all(cloud.is_local(p) for p in it.needed_files()):
                self.request_ready(it, now=False)

    def play(self, item: Item):
        self.ensure_player(item)  # sempre l'originale
        live = item.kind == "live"
        self.player.setLoops(QMediaPlayer.Infinite if live and self.live_mode == "loop" else 1)
        self.audio.setMuted(self.btn_volume.isChecked())
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
        if self.edit_pending():   # prima OK o Annulla: si salva la versione confermata
            self.flash(tr('Prima conferma le modifiche con OK oppure Annulla'))
            return
        self.close_clean_drafts()
        item = self.current()
        if not item or not item.is_clip or self.stack.currentWidget() is self.msg_page:
            return
        info = self.infos.get(item.id)
        if not info:
            self.status.setText(tr('Attendi: sto analizzando il video…'))
            return
        n = self.current_frame()
        if item.kind == "live":
            if self.live_view:  # durante il video: questo fotogramma diventa la foto
                self.set_frame(n, manual=True)
                self.flash(tr('📸 Foto della Live: fotogramma {v0}  (SÌ per salvarla)', v0=n + 1))
            return
        key = f"{item.id}#f{n}"
        if not self.scene_mode:
            self.set_frame(n, manual=True)  # fermo sul fotogramma salvato, esatto
        if self.session.get(key):
            self.flash(tr('📷 Fotogramma {v0} già salvato', v0=n + 1))
            return
        self.history.append((self.idx, key, None))
        try:
            self.session.set(key, "snap", [], n)
            edit = E.clean(self.session.edits.get(key, {}))
            if edit:   # Regola / Ritaglia su questo fotogramma: si salva la foto modificata
                self.session.decisions[key]["edit"] = edit
                self.session.save()
            self.queue_export(item, n, key=key, snapshot=True)
        except OSError as e:   # salvataggio non riuscito: la foto non risulta presa
            self.history.pop()
            self.session.decisions.pop(key, None)
            log.error("foto %s non salvata: %r", key, e, exc_info=e)
            self.status.setStyleSheet("")
            self.status.setText(tr('Scelta non salvata: {e}', e=e), ms=0)
            self.update_scene_controls()
            return
        self.flash(tr('📷 Foto salvata: fotogramma {v0}  (Z per annullare)', v0=n + 1))
        self.set_buttons_enabled(True)
        self.update_scene_controls()
        self.btn_undo.setEnabled(True)
        self.update_counter()

    def update_snaps_label(self):
        item = self.current()
        k = len(self.snaps_of(item)) if item and item.is_clip and self.session else 0
        if k:
            self.snaps_label.setText((tr('📷  1 foto salvata da questo video') if k == 1 else tr('📷  {k} foto salvate da questo video', k=k)))
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

    def open_snap(self, key: str):
        """Doppio clic su una foto presa: la mostra intera, con la stampabilità e le correzioni."""
        item = self.current()
        d = self.session.get(key) if self.session else None
        if not item or not d:
            return
        files = [f for f in d.get("files", []) if Path(f).suffix.lower() in (".jpg", ".png")]
        img = QImage(files[0]) if files else QImage()
        if img.isNull():
            self.flash(tr('Foto non ancora salvata: riprova tra un attimo'))
            return
        self.snap_key = key
        self.image_view.set_image(img)
        self.stack.setCurrentWidget(self.image_view)
        m = metadata.read_image(Path(files[0]))
        esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        rows = []
        for k, v in m.rows:
            hot = k == tr('Stampabilità')   # il dato che si cerca: in verde
            vs = f"<span style='color:{C['text_ok']}; font-weight:700'>{esc(v)}</span>" if hot else esc(v)
            rows.append(f"<tr><td width='78' style='color:{C['text_2']}; padding:3px 10px 3px 0; vertical-align:top'>"
                        f"{esc(k)}</td><td style='color:{C['text']}; padding:3px 0'>{vs}</td></tr>")
        self.side_info.setText(tr('FOTO PRESA · FOTOGRAMMA {v0}', v0=d["frame"] + 1))
        self.side_info.show()
        self.side_details.setText("<table cellspacing='0'>" + "".join(rows) + "</table>")
        self.side_seg.set_current("info")
        self.side_tab = "info"
        self.side_pages.setCurrentIndex(0)
        if not self.side.isVisible():
            self.toggle_side()
        self.snap_fix.show()
        self.snap_save.hide()
        self.snap_bar.show()
        self.place_snap_bar()

    def place_snap_bar(self):
        """Barra in alto al centro della foto, sopra la scena."""
        if not self.snap_bar.isVisible():
            return
        self.snap_bar.adjustSize()
        w = self.snap_bar.sizeHint().width()
        self.snap_bar.move((self.stack.width() - w) // 2, 12)

    def fix_snap(self):
        """Correggi: il video si ferma su quel fotogramma e si apre Regola, come per una foto."""
        d = self.session.get(self.snap_key) if self.session and self.snap_key else None
        if not d:
            return
        self.set_frame(d["frame"], manual=True)
        self.side_seg.set_current("regola")
        self.side_tab = "regola"
        self.side_pages.setCurrentIndex(1)
        self.snap_save.show()
        self.flash(tr('Modifica il fotogramma, poi premi "Aggiorna foto"'))

    def save_snap_fix(self):
        """Aggiorna foto: sostituisce la foto presa con quella corretta, poi torna al video."""
        if self.edit_pending():
            self.flash(tr('Prima conferma le modifiche con OK oppure Annulla'))
            return
        key = self.snap_key
        d = self.session.get(key) if self.session and key else None
        if not d:
            return
        self.remove_snap(key)
        if self.session.get(key):   # non si è potuta togliere: resta com'è
            return
        self.take_photo()
        self.close_snap()

    def close_snap(self):
        """Chiudi: torna al video dal fotogramma della foto."""
        if self.edit_pending():
            self.flash(tr('Prima conferma le modifiche con OK oppure Annulla'))
            return
        d = self.session.get(self.snap_key) if self.session and self.snap_key else None
        self.snap_key = None
        self.snap_bar.hide()
        item = self.current()
        if d and item and item.is_clip:
            self.set_frame(d["frame"], manual=True)
            self.toggle_scene()

    def remove_snap(self, key: str):
        """✕ su una foto presa: toglie la copia da export (l'originale non si tocca mai)."""
        d = self.session.get(key) if self.session else None
        if not d or d["choice"] != "snap" or not self.revert_effects(key, d):
            return
        self.session.clear(key)
        self.flash(tr('Foto tolta: fotogramma {v0} (F per riprenderla)', v0=d['frame'] + 1))
        self.set_buttons_enabled(True)
        self.update_scene_controls()
        self.update_counter()

    def update_save_info(self):
        """Pannello a destra: i progressi sono salvati? quando? dove? e dove vanno le foto."""
        ses = self.session
        if not ses:
            self.save_info.setText("")
            return
        saved = ses.path.exists()
        when = ses.updated[11:19] if saved and len(ses.updated) >= 19 else ""
        day = ses.updated[:10] if saved else ""
        from datetime import date
        if saved and day != date.today().isoformat():
            when = f"{day[8:10]}/{day[5:7]} {when}"
        state = (tr("<span style='color:{c}'>✓ Salvato alle {when}</span>", c=C["text_ok"], when=when) if saved else
                 tr("<span style='color:{c}'>Non ancora salvato</span>", c=C["text_warn"]))
        where = self.short_folder(str(ses.path.parent))
        self.save_info.setText(state)
        self.save_info.setToolTip(tr('Si salva da solo a ogni scelta: puoi chiudere quando vuoi e riprendere da qui.\nProgressi: {v1}/{v2}\nFoto scelte: {v3}', v1=where, v2=ses.path.name, v3=self.short_path(self.export_dir)))

    def file_status(self, item: Item, d: dict | None) -> tuple[str, str, list[tuple[str, str]]]:
        """Cosa è successo AI FILE di questo elemento: copiato in export, spostato in “cancellare”,
        o niente. (colore, testo, link "Apri …") per il pannello Info: niente percorsi lunghi."""
        grey = C["text_2"]
        if not d:
            return grey, tr('da decidere · niente copiato né spostato'), []
        choice = d["choice"]
        if choice == "no":
            return CHOICE_COLOR["no"], tr("✗ scartata · niente copiato, l'originale resta al suo posto"), []
        if choice == "skip":
            return CHOICE_COLOR["skip"], tr('↪ saltata · niente copiato né spostato'), []
        if choice == "trash":
            moved = [dst for _, dst in d.get("moved", [])]
            return (CHOICE_COLOR["trash"], tr('🗑 originale SPOSTATO in “cancellare” (Z lo rimette a posto)'),
                    infopanel.open_links(moved))
        if choice == "yes" and d.get("noexport"):
            return CHOICE_COLOR["yes"], tr('✓ approvata · video non copiato (tenute solo le foto prese)'), []
        if d.get("export_failed"):
            return (C["text_warn"], tr('⚠ copia non riuscita: {v0}\n(si riprova alla prossima apertura)', v0=d['export_failed']), [])
        files = d.get("files") or []
        if not files:
            return C["text_warn"], tr('⏳ copia in export in corso…'), []
        return (CHOICE_COLOR["yes"], tr("✓ approvata · COPIATA in export (l'originale resta al suo posto)"),
                infopanel.open_links(files))

    def short_path(self, path) -> str:
        """Percorso leggibile: dentro la cartella aperta come "dji pocket/export", altrove con ~."""
        short = self.short_folder(str(path))
        if short != str(path):
            return short
        home = str(Path.home())
        return "~" + str(path)[len(home):] if str(path).startswith(home) else str(path)

    def tidy_exports(self) -> None:
        """Le copie fatte dalle versioni di prima (foto sciolte in export, senza data nel nome o col
        numero 0001_) si mettono in ordine come le nuove: export/Foto, export/Video, nome con data e
        ora di scatto. Da sola, all'apertura; in coda export, dopo le copie da rifare. Originali intatti."""
        if not self.session or not self.items or not exporter.export_reachable(self.export_dir):
            return
        by_id = self._by_id
        entries, favorites = [], set(self.session.favorites)
        for key, d in self.session.decisions.items():
            it = by_id.get(key.split("#")[0])
            if it is not None and d.get("choice") in ("yes", "snap") and d.get("files"):
                entries.append((key, it.taken, list(d["files"])))
        if not entries:
            return
        export_dir = self.export_dir

        def job(entries=entries):
            # nella coda export: dopo le copie e gli spostamenti già chiesti, percorsi di ADESSO
            fresh = []
            for key, taken, files in entries:
                files = self.copy_paths.get(key) or files
                fresh.append((key, exporter.album_time(files, taken), files))
            errors: list[str] = []
            moved = exporter.rename_by_date(fresh, export_dir, errors, favorites)
            for key, pairs in moved.items():
                if key in self.copy_paths:
                    m = dict(pairs)
                    self.copy_paths[key] = [m.get(f, f) for f in self.copy_paths[key]]
            return moved, errors
        self._rename_busy = True
        self.submit("rename", None, job, queue=self.export_q)

    def on_renamed(self, res) -> None:
        self._rename_busy = False
        if isinstance(res, Exception):
            log.error("riordino export: %r", res, exc_info=res)
            return
        moved, errors = res
        for item_id, pairs in moved.items():   # anche se qualcosa non è riuscito: i file rinominati
            d = self.session.get(item_id) if self.session else None
            if d:
                self.session.relocated(item_id, d.get("export_id"), pairs)
        n = sum(len(p) for p in moved.values())
        if n:
            log.info("export riordinato: %d copie in Foto / Video con la data nel nome", n)
            self.flash(tr('Export in ordine: {v0} copie spostate in Foto / Video con la data nel nome', v0=n))
        if errors:
            log.warning("export: copie non riordinate: %s", errors)
            self.status.setStyleSheet(f"color:{C['text_warn']};")
            self.status.setText(tr('{v0} copie in export non si sono potute rinominare: restano com\'erano', v0=len(errors)), ms=0)

    def save_now(self):
        if not self.session:
            return
        try:
            self.session.save()
        except OSError as e:
            self.status.setStyleSheet(f"color:{C['text_warn']};")
            self.status.setText(tr('Salvataggio non riuscito: {e}', e=e))
            return
        self.flash(tr('💾 Progressi salvati'))
        self.update_save_info()

    def reveal_session(self):
        if not self.session or not self.session.path.exists():
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(self.session.path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session.path.parent)))

    def flash(self, text: str):
        self.status.setStyleSheet(f"color:{C['text_ok']};")
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
        self.audio.setMuted(self.btn_volume.isChecked())
        self.player.setPosition(0)
        self.player.play()
        self.update_scene_controls()

    def on_play_state(self, state):
        playing = state == QMediaPlayer.PlayingState
        self.btn_play.setText("⏸" if playing else "▶")
        self.btn_play.setToolTip(tr('Pausa (barra spaziatrice)') if playing else tr('Play (barra spaziatrice)'))

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
        self.msg_btn2.setText(tr('↪  Salta questo  (S)'))
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
        eta = f"circa {left} s rimanenti" if left else tr('quasi finito…')
        if secs and secs % 30 == 0:
            log.info("ancora in attesa di iCloud (%d s) per %s", secs, item.id)
        self.message.setText(
            tr('☁️  Scarico da iCloud{dots}\n\n{names}\n\n{bar}  ≈ {pct}%\n⏱  {secs} s  ·  {eta}   (stima su {speed:.1f} MB/s)\nmacOS non dice la percentuale vera: la stima usa la velocità dei download già fatti.\nI prossimi {PREFETCH} elementi si stanno già scaricando in automatico.\n\nIntanto puoi premere  S = salta,  N = no,  X = sposta in “cancellare”.', dots=dots, names=names, bar=bar, pct=pct, secs=secs, eta=eta, speed=speed, PREFETCH=PREFETCH))

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
            self.image_view.set_loading(tr('Carico la foto in 4K…'))  # niente anteprime a bassa risoluzione
            return
        self.show_frame(self.live_photo_frame(item), scrub=False)

    LIVE_MODES = {"live": "Live", "loop": "Ripeti", "off": "Disattiva"}

    def refresh_live_mode(self) -> None:
        names = {k: tr(v) for k, v in self.LIVE_MODES.items()}   # Ripeti, Disattiva: in EN
        self.btn_live_mode.setText(names[self.live_mode] + "  ⇕")
        for k, b in self._live_mode_btns.items():
            b.setText(("✓   " if k == self.live_mode else "      ") + names[k])

    def show_live_menu(self) -> None:
        self.refresh_live_mode()
        self._live_pop.adjustSize()
        pos = self.btn_live_mode.mapToGlobal(QPoint(0, -self._live_pop.sizeHint().height() - 6))
        self._live_pop.move(pos)
        self._live_pop.show()

    def set_live_mode(self, key: str) -> None:
        """Live (una volta e torna alla foto), Ripeti (in loop), Disattiva (il clic non la avvia)."""
        self._live_pop.hide()
        self.live_mode = key
        self.settings_store.setValue("live_mode", key)
        self.refresh_live_mode()
        self.player.setLoops(QMediaPlayer.Infinite if key == "loop" else 1)
        if key == "off" and self.live_view:
            self.show_live_still()
            self.update_scene_controls()

    def on_volume(self, muted: bool) -> None:
        self.audio.setMuted(muted)
        self.settings_store.setValue("muted", "1" if muted else "0")

    def on_media_click(self) -> None:
        """Clic sulla foto della Live o sul video: parte; di nuovo clic: si ferma (come in Foto)."""
        item = self.current()
        if not item or not item.is_clip or self.edit_pending() or self.crop_draft is not None \
                or self.image_view.pick_enabled or self.stack.currentWidget() is self.msg_page:
            return
        if item.kind == "live":
            if self.live_mode == "off" and not self.live_view:
                self.flash(tr("Live disattivata: scegli Live nel menu della barra per farla partire col clic"))
                return
            self.toggle_live()
        else:
            self.play_pause()

    def on_media_status(self, status) -> None:
        """Live in modalità "Live": finita una volta, si torna alla foto (come in Foto)."""
        item = self.current()
        if status == QMediaPlayer.EndOfMedia and item is not None and item.kind == "live" \
                and self.live_view and self.live_mode != "loop":
            self.show_live_still()
            self.update_scene_controls()

    def toggle_live(self):
        item = self.current()
        if not item or item.kind != "live" or self.stack.currentWidget() is self.msg_page:
            return
        if self.live_view:
            self.show_live_still()
        else:
            self.live_view = True
            self.play(item)
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
        """Data/ora dello scatto (dal nome del file DJI) in alto a sinistra; nei video avanza
        e, fermo su un fotogramma, mostra l'ora di quel fotogramma."""
        item = self.current()
        page = self.stack.currentWidget()
        if not item or page not in (self.image_view, self.video_widget):
            self.stamp.hide()
            self.place_zoom()
            return
        from datetime import timedelta
        self.stamp.setText("·  " + fmt_datetime(item.taken + timedelta(seconds=offset_s)))
        self.stamp.show()
        self.place_stamp()

    def place_stamp(self):
        """La data è nella barra in alto: sulla foto restano solo zoom e avvisi."""
        if hasattr(self, "stamp") and not self.stamp.isHidden():
            self.place_zoom()
            self.warn.place()

    def place_zoom(self):
        """Zoom in alto a sinistra sulla foto (foto e panorami), come i comandi di Foto: solo col
        mouse sopra la foto o a foto ingrandita, mai in Ritaglia (coprirebbe la maniglia)."""
        if not hasattr(self, "stamp"):
            return
        item = self.current()
        show = (self.stack.currentWidget() is self.image_view and not self.stamp.isHidden()
                and item is not None and item.kind != "video" and not self.image_view.crop_mode
                and (getattr(self, "_over_photo", False) or self.zoom_slider.value() > 0))
        self.zoom_pill.setVisible(show)
        if show:
            self.zoom_pill.adjustSize()
            self.zoom_pill.move(14, 12)
            self.zoom_pill.raise_()

    def place_photo_arrows(self):
        """Frecce ai lati della foto, a metà altezza."""
        area = self.stack.rect()
        y = max(0, (area.height() - 44) // 2)
        self.photo_prev.move(14, y)
        self.photo_next.move(max(14, area.width() - 44 - 14), y)
        self.photo_prev.raise_()
        self.photo_next.raise_()

    def update_photo_arrows(self):
        """Visibili solo mentre si sfoglia foto o video (non in home, non durante una modifica)."""
        browsing = (self.stack.currentWidget() in (self.image_view, self.video_widget)
                    and self.current() is not None and not self.edit_pending())
        self.photo_prev.setVisible(browsing)
        self.photo_next.setVisible(browsing)
        self.place_photo_arrows()

    def update_item_labels(self):
        item = self.current()
        self.update_print_box()
        self.update_photo_arrows()
        if not item:
            return
        color = KIND_COLOR[item.kind]
        self.badge.setText(KIND_LABEL[item.kind])
        self.badge.setStyleSheet(f"background:{color}; color:#111; border-radius:8px;"
                                 "font-size:10px; font-weight:800; padding:2px 7px;")
        self.heading.setText(item.main.name)
        QTimer.singleShot(0, self.balance_top)   # nome nuovo: il titolo si ricentra
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
                parts.append(tr('anteprima 720p · originale scaricato al SÌ'))
            hint = frames.print_hint(w_, h_)
            if hint in ("30×45", "20×30"):
                parts.append(f"stampa fino a {hint}")
            else:
                warn.append(f"⚠ bassa risoluzione: stampa max {hint}")
            if info.is_flat_profile:
                warn.append(tr('⚠ profilo colore piatto (D-Log/HLG)'))
        elif info and info.source:
            parts.append(tr('anteprima 720p · originale scaricato al SÌ'))
        if item.is_clip and item.duration:
            parts.append(f"{item.duration:.1f} s")
        d = self.session.get(item.id) if self.session else None
        self.show_chosen(d)
        pos, total = self.position()
        # la data sta già in sovraimpressione a sinistra sulla foto: qui solo a che punto sei
        self.title.setText(tr('{pos} di {total}', pos=pos, total=total) if total else "")
        self.title.setToolTip(parts[0])
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
        color, status, links = self.file_status(item, d)   # copiata, spostata o lasciata lì
        links = [(label, QUrl.fromLocalFile(f).toString()) for label, f in links]
        self.side_info.hide()   # il titolo serve solo per le foto prese da un video
        tz = dict(m.rows).get(tr('Fuso orario'), "") if m else ""
        self.side_details.setText(infopanel.details_html(item.taken, KIND_LABEL[item.kind], color, status, links, tz))
        card = infopanel.card_html(m, extra, self.burst_html)
        self.info_card_text.setText(card)
        self.info_card.setVisible(bool(card))
        favorite = bool(self.session and item.id in self.session.favorites)
        more = infopanel.more_html(m, extra, warn, self.short_folder, favorite)
        self.side_more.setText(more)
        self.side_more.setVisible(bool(more))

    def burst_html(self) -> str:
        """Raffica attorno alla foto: si leggono anche i vicini, solo le foto già sul disco."""
        near = [self.items[i] for i in similar.neighbors(self.items, self.idx)]
        self.burst_ids = {it.id for it in near}
        for it in near:
            if it.id not in self.meta and ("meta", it.id) not in self.pending and not it.is_clip \
                    and all(cloud.is_local(p) for p in it.needed_files()):
                self.pending.add(("meta", it.id))
                self.submit("meta", it.id, metadata.read, it, None)
        return similar.info_html(self.items, self.idx, lambda it: getattr(self.meta.get(it.id), "quality", None))

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
            self.chosen_tag.setText(tr('GIÀ SCELTO  {v0}', v0=CHOICE_NAME[choice]))
            self.chosen_tag.setStyleSheet(f"background:{CHOICE_COLOR[choice]};")
            self.chosen_tag.show()
            QTimer.singleShot(0, self.balance_top)
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
        self.photobook.refresh(self.session if self.media_filter != "videos" else None, self.items, self.idx)
        self.update_save_info()
        self.refresh_stamp()
        if not self.session or not self.items:
            self.counter.setText("")
            self.done_label.setText("")
            self.progress.setVisible(False)
            return
        c = self.session.counts()
        vis = [i for i, it in enumerate(self.items) if self.visible(it)]
        done = sum(1 for i in vis if self.session.get(self.items[i].id) is not None)
        self.done_label.setText(
            tr("<span style='font-size:13px; font-weight:600; color:{c};'>{done} di {v1} già fatte</span>", c=C["text"], done=done, v1=len(vis))
            + (f"<span style='font-size:12px; color:{C['text_2']};'>  ·  ne mancano {len(vis) - done}</span>"
               if done < len(vis) else f"<span style='font-size:12px; color:{C['yes']};'>  ·  tutte decise</span>"))
        self.progress.setVisible(True)
        self.progress.setRange(0, max(1, len(vis)))
        self.progress.setValue(done)
        pos = sum(1 for i in vis if i <= self.idx)
        hidden = len(self.items) - len(vis)
        busy = sum(1 for f in self.export_futures.values() if not f.done())
        extra = tr('   ⏳ export {busy}', busy=busy) if busy else ""
        if hidden:
            extra += tr('   ({hidden} nascosti dal filtro)', hidden=hidden)
        self.update_fav_button()
        self.update_next_preview()
        # una riga sola, senza simboli: il numero dell'elemento è già in alto
        self.counter.setText(tr('{v2} approvate · {v3} scartate · {v4} saltate', v2=c['yes'], v3=c['no'], v4=c['skip'])
                             + (tr(' · {v0} in “cancellare”', v0=c['trash']) if c.get("trash") else "")
                             + (tr(' · {v0} dai video', v0=c['snap']) if c.get("snap") else "")
                             + (f"\n{extra.strip()}" if extra else ""))
        self.counter.setToolTip(tr('Elemento {pos} di {v1}', pos=pos, v1=len(vis)))

    def show_message(self, text: str, end: bool = False):
        self.player.stop()
        self.message.setText(text)
        self.stack.setCurrentWidget(self.msg_page)
        self.scene_bar.setVisible(False)
        for b in (self.msg_btn1, self.msg_btn2, self.msg_btn3):
            b.setVisible(False)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    b.clicked.disconnect()
                except (RuntimeError, TypeError):
                    pass
        if end:
            self.msg_btn1.setText(tr('Mostra la cartella export'))
            self.msg_btn1.clicked.connect(self.open_export)
            self.msg_btn1.setVisible(True)
            self.msg_btn3.clicked.connect(self.choose_root)
            self.msg_btn3.setVisible(True)
            if self.session and self.session.counts()["skip"]:
                self.msg_btn2.setText(tr('↪  Rivedi le saltate'))
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
        rest = tr('manca 1 elemento') if left == 1 else tr('mancano {n} elementi', n=left)
        head = tr('Sei in fondo, ma {rest} da decidere più indietro.', rest=rest) if left else tr('Finito!')
        self.show_message(f"{head}\n\n✓ {c['yes']} approvate    ✗ {c['no']} scartate    "
                          f"↪ {c['skip']} saltate"
                          + (tr('\n\n🎬 {hidden} nascosti dal filtro attivo', hidden=hidden) if hidden else "")
                          + tr('\n\n← = torna indietro a rivedere'), end=True)
        if left:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    self.msg_btn2.clicked.disconnect()   # al posto di "Rivedi le saltate"
                except (RuntimeError, TypeError):
                    pass
            self.msg_btn2.setText(tr('→  Vai al primo da decidere'))
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
        yes, both = ((tr('Tieni le foto (Y)'), tr('Foto + video (⇧Y)')) if snaps
                     else (tr('Salva video (Y)'), tr('Sì + video (⇧Y)')) if item is not None and item.kind == "video"
                     else (tr('Sì (Y)'), tr('Sì + video (⇧Y)')))
        self.choice_caps["yes"].setText(yes)
        self.choice_caps["yesvideo"].setText(both)
        for name, cap in (("yes", yes), ("yesvideo", both)):
            getattr(self, "btn_yes" if name == "yes" else "btn_yes_video").setAccessibleName(
                cap.replace(" (", tr(', tasto ')).rstrip(")"))

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
        self.update_edit_ui()   # Regola / Ritaglia: nei video solo sul fotogramma fermo
        item = self.current()
        info = self.infos.get(item.id) if item else None
        clip = bool(item) and item.is_clip
        live = clip and item.kind == "live"
        for w in (self.btn_play, self.btn_prev, self.strip, self.btn_next, self.time_label,
                  self.strip_box, self.btn_volume):
            w.setVisible(clip)
        self.btn_live_mode.setVisible(live)
        self.btn_live.setVisible(live)
        self.btn_live.setText(tr('🖼  Torna alla foto (L)') if self.live_view else tr('▶  Vedi Live (L)'))
        self.btn_replay.setVisible(clip and not live)
        self.btn_snap.setVisible(clip and not live)
        self.btn_sharp.setVisible(clip and info is not None and (live or self.scene_mode))
        self.btn_reset.setVisible(live and self.frame is not None)
        if not clip:
            return
        self.update_strip()
        if info is None:
            self.frame_label.setText(tr('analisi del video…'))
            return
        if live:
            n = self.live_photo_frame(item)
            who = tr('scelta da te') if self.frame is not None else tr('della fotocamera')
            self.frame_label.setText(tr('Foto {v0} / {v1} · {who}', v0=n + 1, v1=info.frames, who=who))
            self.frame_label.setToolTip(
                tr("trascina sulla striscia per sceglierne un'altra") if self.live_view else
                tr('trascina sulla striscia o usa ↑ ↓ per cambiarla  ·  SÌ salva questa'))
            self.update_time_label(n, info)
            return
        if self.scene_mode:
            saved = bool(self.session) and f"{item.id}#f{self.shown_frame}" in self.session.decisions
            self.frame_label.setText(
                tr('Fotogramma {v0} / {v1}', v0=self.shown_frame + 1, v1=info.frames)
                + "  ·  " + (tr('✓ già salvato') if saved else tr('F = salva come foto')))
            self.frame_label.setToolTip(tr('📷 F = salva questo fotogramma come foto'))
            self.update_time_label(self.shown_frame, info)
        else:
            k = len(self.snaps_of(item))
            self.frame_label.setText(tr('📷 {k} foto prese', k=k) if k else tr('Clic sulla striscia per fermarti'))
            self.frame_label.setToolTip(
                tr('📷 {k} foto prese (segni verdi)  ·  SÌ = tieni solo le foto  ·  ＋ SÌ e video = anche il video', k=k)
                if k else tr('Clic sulla striscia per fermarti su un fotogramma  ·  SÌ = copia il video in export/Video'))

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
            # i fotogrammi dell'anteprima si preparano subito: il primo clic è già immediato
            self.ensure_proxy(item, info, self.live_photo_frame(item) if item.kind == "live" else 0)
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
        quick = None if img is not None or self.image_view.zoomed else self.proxy_image(item, n)
        self.ensure_proxy(item, info, n)
        if img is not None or quick is not None:
            # quello esatto se c'è, se no subito quello dell'anteprima (poi arriva l'esatto)
            self.set_still(img if img is not None else quick, item.id, keep_zoom=True)
            self.stack.setCurrentWidget(self.image_view)
            if img is None:
                self.preview_timer.start()
        elif scrub and not self.image_view.zoomed and not same_item_on_screen:
            self.ensure_player(item)
            self.player.pause()
            self.player.setPosition(self.frame_ms(info, n))
            self.stack.setCurrentWidget(self.video_widget)
            self.preview_timer.start()
        else:
            if not scrub and not same_item_on_screen:
                self.image_view.set_loading(tr('Carico la foto in 4K…'))  # niente anteprime sfocate
            self.stack.setCurrentWidget(self.image_view)
            self.preview_timer.start()
        self.update_scene_controls()
        self.refresh_stamp()

    def proxy_image(self, item: Item, n: int) -> QImage | None:
        win = self.proxy_frames.get(item.id)
        if not win or not 0 <= n - win[0] < len(win[1]):
            return None
        img = QImage.fromData(win[1][n - win[0]], "JPEG")
        return None if img.isNull() else img

    def ensure_proxy(self, item: Item, info: frames.VideoInfo, n: int) -> None:
        """Prepara i fotogrammi dell'anteprima .LRF attorno a n (una Live intera, ±1,5 s di un video)."""
        if not item.proxy or not cloud.is_local(item.proxy) or ("proxy", item.id) in self.pending:
            return
        win = self.proxy_frames.get(item.id)
        if win:   # già pronti qui intorno (con un margine, così le frecce restano immediate)
            start, end = win[0], win[0] + len(win[1])
            if (start == 0 or n >= start + 10) and (end >= info.frames or n < end - 10):
                return
        count = min(info.frames, self.PROXY_SPAN)
        start = max(0, min(info.frames - count, n - count // 2))
        self.pending.add(("proxy", item.id))
        self.submit("proxy", (item.id, start), self.load_proxy, item.proxy, info, start, count,
                    queue=self.frames_q)

    PROXY_SPAN = 92   # fotogrammi letti in una volta: una Live intera (3 s)

    @staticmethod
    def load_proxy(proxy: Path, info: frames.VideoInfo, start: int, count: int) -> list[bytes] | None:
        pi = frames.probe(proxy)
        if pi.frames != info.frames or pi.fps != info.fps:
            return None   # anteprima con fotogrammi diversi: non si usa, si aspetta l'esatto
        return frames.proxy_window(proxy, pi, start, count)

    def on_proxy(self, key, res) -> None:
        item_id, start = key
        self.pending.discard(("proxy", item_id))
        if isinstance(res, Exception) or not res:
            return
        self.proxy_frames[item_id] = (start, res)
        cur = self.current() if self.stack.currentWidget() is not self.setup_page else None
        if not cur or cur.id != item_id or not (self.scene_mode or self.showing_still(cur)) \
                or (item_id, self.shown_frame) in self.exact_cache or self.image_view.zoomed:
            return
        quick = self.proxy_image(cur, self.shown_frame)
        if quick is not None and self.stack.currentWidget() in (self.image_view, self.video_widget):
            self.set_still(quick, item_id, keep_zoom=True)
            self.stack.setCurrentWidget(self.image_view)

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
        self.submit("preview", key, frames.frame_rgb, info.source or item.video, info, self.shown_frame,
                    queue=self.frames_q)

    def on_preview(self, key, res):
        self._preview_busy = False
        cur = self.current() if self.stack.currentWidget() is not self.setup_page else None
        if not isinstance(res, Exception):
            img = pil_to_qimage(res)
            self.exact_cache[key] = img   # 4K = ~25 MB l'una, al massimo 4
            item_id, n = key
            if cur and cur.id == item_id and n == self.shown_frame \
                    and (self.scene_mode or self.showing_still(cur)):
                self.set_still(img, item_id, keep_zoom=True)
                self.stack.setCurrentWidget(self.image_view)
        if self._preview_again:
            self._preview_again = False
            self.request_preview()

    def nav_unless_editing(self, fn) -> None:
        """Frecce sulla foto: come i tasti, con modifiche in sospeso si conferma o annulla prima."""
        if self.edit_pending():
            self.flash(tr('Prima conferma le modifiche con OK oppure Annulla'))
            return
        fn()

    def nav_frame(self, delta: int):
        """Su / Giù: fotogramma prima / dopo nei video; sulle foto, foto precedente / successiva."""
        item = self.current()
        if item is not None and item.is_clip:
            if self.current_frame() is not None:
                self.step(delta)   # analisi non ancora finita: si aspetta, non si cambia elemento
        else:
            (self.go_back if delta < 0 else self.go_forward)()

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
        self.time_label.setText(f"{int(t // 60)}:{t % 60:05.2f}")   # breve; la durata è nel suggerimento
        self.time_label.setToolTip(tr("Durata: {d}", d=f"{int(total // 60)}:{total % 60:05.2f}"))

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
        if not info or n is None or self._sharp_busy:   # già in corso: premere di nuovo non ne accoda altre
            return
        self._sharp_busy = True
        self.btn_sharp.setEnabled(False)
        self.frame_label.setText(tr('cerco il fotogramma più nitido…'))
        self.submit("sharpest", (item.id, n), frames.sharpest_near, info.source or item.video, info, n)

    # ------------------------------------------------------------------ filtro, indietro, preferite
    def on_filter_changed(self):
        self.media_filter = MEDIA_FILTERS[self.view_filter.currentIndex()]
        self.settings_store.setValue("filter", self.media_filter)
        if not self.session or not self.items:
            return
        cur = self.current()
        if cur is None or not self.visible(cur):
            i = self.next_index(self.idx)
            self.idx = i if i < len(self.items) else self.next_index(-1)
        self.show_item()

    def go_home(self):
        """Home: torna alla scelta della cartella. Con modifiche aperte non si esce."""
        if self.edit_pending():
            self.flash(tr('Prima conferma o annulla le modifiche'))
            return
        # ricordo la foto a cui sei arrivato: "Riprendi" la riapre lì, non alla prima da decidere
        item = self.current()
        if self.session and item and self.stack.currentWidget() is not self.setup_page:
            self.settings_store.setValue("home_root", str(self.root))
            self.settings_store.setValue("home_id", item.id)
        self.show_setup()

    def go_back(self):
        if not self.session or not self.items or self.stack.currentWidget() is self.setup_page:
            return
        i = min(self.idx, len(self.items)) - 1
        while i >= 0 and not self.in_strip(i):
            i -= 1
        if i < 0:
            self.flash(tr('Sei al primo elemento'))
            return
        self.go_to(i)

    def locate_is_here(self) -> bool:
        """True se la foto selezionata è già la prima ancora da decidere: “Torna all'analisi” non serve."""
        i = self.next_index(-1)
        return bool(self.items) and i < len(self.items) and i == self.idx

    def update_locate_btn(self):
        """"Torna all'analisi" e le frecce della striscia: solo se si torna dalla home, finché serve."""
        show = self.came_from_home and bool(self.items) and not self.locate_is_here()
        self.btn_locate.setVisible(show)
        browsing = self.stack.currentWidget() is not self.setup_page
        arrows = browsing and self.came_from_home and bool(self.items)
        for b in (self.btn_thumb_prev, self.btn_thumb_next):
            b.setVisible(arrows)

    def locate_thumb(self):
        """Torna alla prima foto ancora da decidere (la prossima da giudicare)."""
        if not self.session or not self.items:
            return
        self.came_from_home = False   # fatto: il pulsante e le frecce tornano nascosti
        self.update_locate_btn()
        i = self.next_index(-1)
        if i >= len(self.items):
            # Tutte decise: resta dove sei, ma riporta la striscia al centro
            self.thumbs_strip.recenter()
            return
        if i == self.idx:
            self.thumbs_strip.recenter()   # già lì: solo la striscia torna centrata
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
        while i < len(self.items) and not self.in_strip(i):
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
            # già approvata: le foto si spostano tra export/Foto ed export/Foto/Preferite (mai sovrascritte)
            export_dir = self.export_dir
            fut = self.export_futures.get(item.id)

            def job(fut=fut, files=list(d["files"]), item_id=item.id):
                files = self.copy_paths.get(item_id) or files
                if not files and fut is not None:
                    try:
                        files = [str(p) for p in fut.result()]
                    except Exception:  # noqa: BLE001 - export fallito: niente da spostare
                        return []
                pairs = exporter.refile_favorite(files, export_dir, on)
                moved = {a: b for a, b in pairs}
                self.copy_paths[item_id] = [moved.get(f, f) for f in files]
                return pairs
            self.submit("relocate", (item.id, d.get("export_id")), job, queue=self.export_q)
        self.flash(tr('♥ Preferita: le copie vanno in export/Foto/Preferite') if on else tr('Preferita tolta'))
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
        self.go_to(i)

    def go_to(self, i: int):
        """Vai all'elemento i; andando indietro (← o miniatura) si ricorda da dove si è partiti."""
        if i < self.idx and self.return_idx is None:
            self.return_idx = self.idx   # la foto da cui si è tornati indietro
            self.btn_return.setVisible(True)
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
        """Evidenzia la voce selezionata nel popup del filtro: segno ✓ e testo in evidenza,
        le altre voci restano piatte e si accendono al passaggio del mouse."""
        base = ("QPushButton { border: none; border-radius: 8px; text-align: left; "
                "padding: 8px 12px; font-size: 13px; }")
        for fb, key, label in self._strip_filter_btns:
            on = key == self._strip_filter_key
            fb.setText(("✓   " if on else "      ") + label)
            if on:
                fb.setStyleSheet(base + f"QPushButton {{ background: {C['bg_hover']}; color: {C['filter_on']}; font-weight: 600; }}")
            else:
                fb.setStyleSheet(base + f"QPushButton {{ background: transparent; color: {C['text']}; }}"
                                 f"QPushButton:hover {{ background: {C['bg_pressed']}; }}")

    def on_strip_filter(self):
        self.settings_store.setValue("strip_filter", self._strip_filter_key)
        self.update_thumb_strip()

    def in_strip(self, i: int) -> bool:
        """Visibile e dentro il filtro della striscia (quella attuale resta sempre): anche ← → passano solo da qui."""
        it = self.items[i]
        return self.visible(it) and (i == self.idx or stripfilter.keeps(
            self.strip_filter.currentData(), self.session.get(it.id) if self.session else None))

    def index_after_choice(self) -> int:
        """Dopo una scelta: con un filtro nella striscia la successiva dentro il filtro, altrimenti
        (o finite quelle del filtro) la prossima da decidere."""
        if self._strip_filter_key != "all":
            j = next((k for k in range(self.idx + 1, len(self.items)) if self.in_strip(k)), None)
            if j is not None:
                return j
        return self.next_index(self.idx)

    def update_thumb_strip(self):
        """Miniature degli elementi prima e dopo quello attuale (solo quelli visibili col filtro)."""
        if not self.session or not self.items:
            self.thumbs_strip.set_entries([], None)
            return
        vis = [i for i in range(len(self.items)) if self.in_strip(i)]
        here = next((k for k, i in enumerate(vis) if i >= self.idx), len(vis))
        span = 150   # si scorre lontano: le miniature si chiedono solo per quelle in vista (wanted)
        chosen = vis[max(0, here - span): here + span + 1]
        self._strip_idx = {self.items[i].id: i for i in chosen}
        entries = []
        for i in chosen:
            it = self.items[i]
            d = self.session.get(it.id)
            entries.append((i, self.next_thumbs.get(it.id), d["choice"] if d else None, it.is_clip, it.main.name))
        cur = self.current()
        self.thumbs_strip.outside = bool(cur) and not stripfilter.keeps(self._strip_filter_key, self.session.get(cur.id))
        self.thumbs_strip.frame_color = STRIP_FRAME_COLORS.get(self._strip_filter_key, C["selected"])
        self.thumbs_strip.set_entries(entries, self.idx if self.idx < len(self.items) else None)

    def request_strip_thumbs(self, idxs: list[int]):
        """Miniature in vista nella striscia (dal centro): si chiedono quelle che mancano."""
        its = [self.items[i] for i in idxs if 0 <= i < len(self.items)]
        need = {it.id: it for it in its if it.id not in self.next_thumbs
                and all(cloud.is_local(p) for p in it.needed_files())}
        self.thumb_q.sync(list(need), lambda k: self.submit("thumb", k, thumbcache.cached_thumb, need[k],
                                                            queue=self.thumb_q.pool))

    def update_next_preview(self):
        """In basso: miniature prima e dopo (prima era un riquadro con il solo successivo)."""
        self.update_thumb_strip()

    make_thumb = staticmethod(thumbcache.make_thumb)

    # ------------------------------------------------------------------ decisioni
    def decide(self, choice: str, with_video: bool = False):
        if self.edit_pending():   # Regola o Ritaglia cambiati: prima OK o Annulla
            self.flash(tr('Prima conferma le modifiche con OK oppure Annulla'))
            return
        self.close_clean_drafts()   # aperti senza cambiare nulla: si chiudono e si va avanti
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
                                    and prev.get("with_video", False) == with_video
                                    and E.clean(prev.get("edit") or {}) == E.clean(
                                        self.item_edit(item.id)
                                        if self.editable(item) and item.kind != "video" else {})))
            if same:  # niente da cambiare: si va avanti
                self.idx = self.index_after_choice()
                self.show_item()
                self.flash(tr('Scelta confermata: {v0}', v0=CHOICE_NAME.get(choice, choice)))
                return
            if not self.revert_effects(item.id, prev):
                return
            item = self.items[self.idx]  # di nuovo al suo posto
        self.history.append((self.idx, item.id, prev))
        changed = f"{CHOICE_NAME.get(prev['choice'], prev['choice'])}  →  {CHOICE_NAME.get(choice, choice)}" \
            if prev is not None else ""
        moved: list[list[str]] = []
        try:
            self._apply_decision(item, choice, with_video, snaps, moved)
        except OSError as e:   # salvataggio non riuscito (disco pieno, scollegato…)
            self.decision_not_saved(item, prev, moved, e)
            return
        self.idx = self.index_after_choice()
        self.show_item()
        if changed:  # tornati indietro e cambiata idea: si dice chiaramente cosa è successo
            self.flash(tr('Scelta cambiata: {v0}   (Z annulla)', v0=changed))

    def _apply_decision(self, item: Item, choice: str, with_video: bool, snaps: list,
                        moved: list[list[str]]) -> None:
        """Effetti e salvataggio della scelta. OSError = salvataggio non riuscito (vedi decide)."""
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
            edit = E.clean(self.item_edit(item.id)) if self.editable(item) else {}
            if edit:   # Regola / Ritaglia: si esporta la foto modificata
                self.session.decisions[item.id]["edit"] = edit
                self.session.save()
            self.queue_export(item, frame, with_video=with_video)
        elif choice == "trash":
            self.player.stop()
            self.player.setSource(QUrl())  # rilascia il file prima di spostarlo
            self._player_item = None
            try:
                moved.extend(exporter.move_to_trash(item, self.root))  # tutto o niente
            except (OSError, ValueError) as e:
                raise _MoveFailed(e) from e
            self.session.set(item.id, "trash", moved=moved)
        else:
            self.session.set(item.id, choice)

    def decision_not_saved(self, item: Item, prev: dict | None, moved: list[list[str]],
                           e: Exception) -> None:
        """La scelta non si è potuta salvare (o gli originali non si sono spostati): tutto come
        prima della scelta, nessun file spostato senza che il salvataggio lo sappia."""
        self.history.pop()
        if self.session:
            # gli effetti della scelta di prima sono già stati tolti (revert_effects): l'elemento
            # torna da decidere, come i suoi file
            self.session.decisions.pop(item.id, None)
        if moved:
            try:
                exporter.restore_from_trash(moved)
            except OSError as e2:
                log.error("ripristino dopo salvataggio non riuscito %s: %r", item.id, e2)
        self.status.setStyleSheet("")
        if isinstance(e, _MoveFailed):
            self.status.setText(tr('Spostamento non riuscito: {e}', e=e.__cause__ or e))
        else:
            log.error("scelta su %s non salvata: %r", item.id, e, exc_info=e)
            self.status.setText(tr('Scelta non salvata: {e}', e=e), ms=0)
        self.show_item(keep_status=True)

    def queue_export(self, item: Item, frame: int | None, key: str | None = None,
                     snapshot: bool = False, with_video: bool = False):
        key = key or item.id
        token = uuid.uuid4().hex  # lega l'esito a questa decisione (vedi on_done)
        self.session.mark_export(key, token)
        favorite = key == item.id and item.id in self.session.favorites
        self.export_q.submit(self.copy_paths.pop, key, None)   # copia nuova: posizioni vecchie non valgono
        edit = (self.session.decisions.get(key) or {}).get("edit")
        fut = self.submit("export", (key, frame, token), exporter.export_item, item, frame,
                          self.export_dir, self.current_settings(with_video), snapshot, edit,
                          favorite, queue=self.export_q)
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
                missing: list[Path] = []
                renamed = exporter.restore_from_trash(d.get("moved", []), new_names, missing)
            except OSError as e:
                self.status.setStyleSheet("")
                self.status.setText(tr('Ripristino da “cancellare” non riuscito: {e} (riprova)', e=e))
                return False
            item = self.item_by_id(item_id)
            if item and new_names:   # l'elemento ora è il file rinominato, non quello che occupa il posto
                for attr in ("image", "raw", "video"):
                    p = getattr(item, attr)
                    if p is not None and p in new_names:
                        setattr(item, attr, new_names[p])
            if missing:   # tolti a mano da "cancellare": la scelta si annulla, ma va detto
                QMessageBox.warning(
                    self, APP_TITLE, tr('Questi file non sono più in “cancellare” e non si possono rimettere a posto:\n')
                    + "\n".join(str(p) for p in missing))
            if renamed:
                QMessageBox.information(
                    self, APP_TITLE, tr("Al posto originale c'era già un file con lo stesso nome: nessuno è stato sovrascritto. Ripristinati come:\n")
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
            try:   # sposta e registra insieme: se non si salva, i file tornano al loro posto
                exporter.trash_item(self.session, item, self.root, base=d)
            except (OSError, ValueError) as e:
                self.status.setText(tr('Spostamento non riuscito: {e}', e=e))
                self.session.decisions.pop(item_id, None)
                return
            return
        self.session.decisions[item_id] = d
        try:
            self.session.save()
        except OSError as e:
            self.status.setText(tr('Scelta non salvata: {e}', e=e), ms=0)
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
            self.flash(tr('Foto annullata'))
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
                self.show_message(tr('Completo gli export in corso… ({left})\n\nLe copie non finite verranno rifatte alla prossima apertura.', left=left))
                QApplication.processEvents()
                time.sleep(0.05)
        for k in list(self._ready_jobs):   # le attese dei download finiscono subito
            self.drop_ready_job(k)
        for ex in (self.bg, self.pre, self.waiters, self.export_q, self.frames_q, self.print_q,
                   self.edit_pool, self.thumb_q.pool):
            ex.shutdown(wait=False, cancel_futures=True)
        stop_child_processes()   # ffmpeg e Real-ESRGAN: non restano orfani né lasciano file a metà
        if self.session:
            self.session.close()
        log.info("uscita")
        super().closeEvent(e)


def stop_child_processes() -> None:
    """Ferma i processi figli ancora in corso (ffmpeg dei fotogrammi, Real-ESRGAN della stampa):
    con os._exit resterebbero orfani e potrebbero lasciare file a metà."""
    for name, kill in (("ffmpeg", frames.kill_running),
                       ("stampa", getattr(printprep, "kill_running", lambda: None))):
        try:
            n = kill()
            if n:
                log.info("uscita: fermati %s processi %s", n, name)
        except Exception as e:  # noqa: BLE001 - l'uscita non si blocca per questo
            log.warning("uscita: non riesco a fermare %s: %r", name, e)


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":
        from selftest import selftest
        sys.exit(selftest(Path(sys.argv[2]), Path(sys.argv[3]), APP_TITLE))
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoSwipe")
    if hasattr(app.styleHints(), "setColorScheme"):
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)  # finestre di sistema scure
    if sys.platform != "darwin":
        apply_dark_palette(app)   # Windows/Linux: Fusion scuro, finestre di dialogo e menu compresi
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
    stop_child_processes()   # anche se la finestra non è passata da closeEvent
    logging.shutdown()
    # Uscita immediata: senza questo Python aspetterebbe i download iCloud ancora in corso
    # nei thread in background (anche minuti) e l'app resterebbe appesa.
    os._exit(rc)


if __name__ == "__main__":
    main()
