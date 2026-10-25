"""Finestrella delle impostazioni che si apre dal pulsante ⚙, come i pannelli di Foto.

Ogni riga dice a cosa serve (etichetta a sinistra) e com'è adesso (a destra): niente pulsanti
che mescolano nome e valore ("Export: export") né titoli in maiuscolo che non spiegano nulla."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

import places
from i18n import tr
from widgets import ElidedLabel

WIDTH = 340


class SettingsPopup(QFrame):
    """I controlli restano attributi pubblici: MainWindow li collega e li legge come prima."""

    def __init__(self, parent, store, file_manager: str):
        super().__init__(parent, Qt.Popup)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(WIDTH)

        # cartelle: il nome attuale, e accanto cosa si può fare
        self.root_name = ElidedLabel("—")
        self.btn_open = QPushButton(tr('Cambia…'))
        self.btn_open.setToolTip(tr('Torna alla scelta delle cartelle (la sessione resta salvata).'))
        self.export_name = ElidedLabel("—")
        self.btn_export = QPushButton(tr('Cambia…'))
        self.btn_export.setToolTip(tr('Scegli dove copiare le foto approvate. Gli originali non si toccano.'))
        self.btn_show_export = QPushButton(tr('Apri'))
        self.btn_show_export.setToolTip(tr('Apre la cartella in {FILE_MANAGER}.', FILE_MANAGER=file_manager))

        # galleria
        self.view_filter = QComboBox()
        self.view_filter.addItems([tr('Tutto'), tr('Solo foto e Live'), tr('Solo video')])
        self.view_filter.setToolTip(tr("Gli elementi nascosti non vengono toccati:\nli ritrovi scegliendo 'Tutto'."))
        self.place_switch = places.online_switch(store)
        self.place_switch.setText(tr('Nomi più precisi via internet'))

        # fotogrammi salvati da Live e video (foto e panorami si copiano sempre identici)
        self.fmt = QComboBox()
        self.fmt.addItems([tr('JPEG (consigliato)'), tr('PNG 16-bit (file grandi)')])
        self.fmt.setToolTip(tr('JPEG a qualità massima: va bene per tutti i siti di stampa.\nPNG 16-bit: senza perdita, ~40 MB a fotogramma.'))
        self.tz = QComboBox()
        self.tz.addItem(tr('Della fotocamera'), None)
        for h in range(-12, 15):
            self.tz.addItem(f"UTC{h:+d}", float(h))
        self.tz.setToolTip(tr("Fuso orario scritto nella data del fotogramma.\n'Della fotocamera' usa l'ora registrata nel file."))

        self.btn_help = QPushButton(tr('Come funziona  ?'))
        self.btn_help.setObjectName("textlink")

        for w in (self.btn_open, self.btn_export, self.btn_show_export, self.view_filter, self.fmt, self.tz,
                  self.btn_help):
            w.setFocusPolicy(Qt.TabFocus)
        for b in (self.btn_open, self.btn_export, self.btn_show_export):
            b.setObjectName("small")
        for b in (self.btn_open, self.btn_export, self.btn_show_export, self.btn_help):
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(self.hide)   # le finestre di scelta si aprono sopra

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("settings")
        outer.addWidget(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 6, 16, 12)
        v.setSpacing(4)

        self._section(v, tr('Cartelle'), None, [
            (tr('Foto da'), self._row(self.root_name, self.btn_open)),
            (tr('Copie in'), self._row(self.export_name, self.btn_show_export, self.btn_export)),
        ])
        self._section(v, tr('Galleria'), None, [
            (tr('Mostra'), self.view_filter),
            (tr('Luoghi'), self.place_switch),
        ])
        self._section(v, tr('Fotogrammi da Live e video'),
                      tr('Le foto e i panorami vengono sempre copiati identici.'), [
            (tr('Formato'), self.fmt),
            (tr('Ora'), self.tz),
        ])
        line = QFrame()
        line.setObjectName("settingsline")
        line.setFixedHeight(1)
        v.addSpacing(8)
        v.addWidget(line)
        v.addWidget(self.btn_help, 0, Qt.AlignLeft)

    def set_folders(self, root: Path | None, export: Path | None) -> None:
        for lab, p in ((self.root_name, root), (self.export_name, export)):
            lab.setText(p.name if p else "—")
            lab.setToolTip(str(p) if p else "")

    @staticmethod
    def _row(*widgets):
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(widgets[0], 1)
        for w in widgets[1:]:
            h.addWidget(w)
        return h

    @staticmethod
    def _section(v, title, note, rows):
        head = QLabel(title)
        head.setObjectName("settingshead")
        v.addWidget(head)
        if note:
            n = QLabel(note)
            n.setObjectName("settingsnote")
            n.setWordWrap(True)
            v.addWidget(n)
        g = QGridLayout()
        g.setContentsMargins(0, 2, 0, 0)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(6)
        g.setColumnMinimumWidth(0, 64)
        g.setColumnStretch(1, 1)
        for r, (label, w) in enumerate(rows):
            lab = QLabel(label)
            lab.setObjectName("muted")
            g.addWidget(lab, r, 0, Qt.AlignLeft | Qt.AlignVCenter)
            if isinstance(w, QHBoxLayout):
                g.addLayout(w, r, 1)
            else:
                g.addWidget(w, r, 1)
        v.addLayout(g)


def reveal_log() -> None:
    import subprocess
    import sys
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    import applog
    path = applog.log_path()
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def show_help_dialog(parent, app_title: str, help_text: str, reveal_fn=reveal_log) -> None:
    from PySide6.QtWidgets import QDialog, QTextBrowser
    from theme import COLORS as C, help_html
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr('Come funziona') + f" — {app_title}")
    v = QVBoxLayout(dlg)
    text = QTextBrowser()
    text.setHtml(help_html(help_text))
    text.setStyleSheet(f"QTextBrowser {{ background: {C['bg_panel']}; border: 1px solid {C['line_divider']};"
                       " border-radius: 10px; padding: 10px; font-size: 13px; }")
    v.addWidget(text, 1)
    row = QHBoxLayout()
    logs = QPushButton(tr('Mostra il file di log'))
    logs.clicked.connect(reveal_fn)
    close = QPushButton(tr('Chiudi'))
    close.setObjectName("primary")
    close.clicked.connect(dlg.accept)
    row.addWidget(logs)
    row.addStretch(1)
    row.addWidget(close)
    v.addLayout(row)
    avail = parent.screen().availableGeometry()
    dlg.resize(min(680, avail.width() - 60), min(720, int(avail.height() * 0.85)))
    dlg.exec()
