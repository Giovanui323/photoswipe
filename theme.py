"""Stile dell'app: il foglio di stile Qt e i colori usati dal codice, in un solo posto."""
from __future__ import annotations

# colore del bordo della miniatura attuale: quello del tipo scelto nel filtro a sinistra
STRIP_FRAME_COLORS = {"yes": "#2ad48e", "no": "#ff4458", "skip": "#3ca4ff", "trash": "#b46cff"}
CHOICE_COLOR = {"yes": "#2ad48e", "no": "#ff4458", "skip": "#3ca4ff", "trash": "#b46cff"}  # = pulsanti
KIND_COLOR = {"photo": "#5b8def", "pano": "#a46bf0", "live": "#f0b429", "video": "#4fb7a8"}

EDIT_STYLE = """
QFrame#segbar { background: #2c2c2e; border: 1px solid #48484a; border-radius: 16px; }
QFrame#side QFrame#segbar QPushButton { background: transparent; border: none; border-radius: 12px;
    padding: 5px 0; font-size: 13px; font-weight: 600; color: #f2f2f7; text-align: center; }
QFrame#side QFrame#segbar QPushButton:hover { background: #3a3a3c; }
QFrame#side QFrame#segbar QPushButton:checked { background: #545456; }
QFrame#side QFrame#segbar QPushButton:disabled { color: #6e6e73; }
QLabel#editnote { color: #98989f; font-size: 11px; }
QFrame#side QPushButton#chev { background: transparent; border: none; padding: 0; font-size: 12px; color: #d1d1d6;
    min-width: 14px; max-width: 14px; text-align: center; }
QFrame#side QPushButton#sectitle { background: transparent; border: none; padding: 2px 0; font-size: 15px;
    color: #f2f2f7; text-align: left; }
QFrame#side QPushButton#sectitle:hover { color: #ffffff; }
QFrame#side QPushButton#secundo { background: transparent; border: none; padding: 0; font-size: 15px; color: #8e8e93;
    min-width: 20px; max-width: 20px; text-align: center; }
QFrame#side QPushButton#secundo:hover { color: #f2f2f7; }
QFrame#side QPushButton#auto { background: transparent; border: 1px solid #8e8e93; border-radius: 8px;
    padding: 0 5px; font-size: 9px; font-weight: 700; color: #d1d1d6; min-height: 15px; max-height: 15px;
    text-align: center; }
QFrame#side QPushButton#auto:hover { border-color: #f2f2f7; color: #ffffff; }
QFrame#side QPushButton#auto[on="true"] { background: #8e8e93; border-color: #8e8e93; color: #1c1c1e; }
QFrame#side QPushButton#secundo:disabled { color: #545456; }
QFrame#side QPushButton#opts { background: transparent; border: none; padding: 2px 0 2px 18px; font-size: 13px;
    color: #d1d1d6; text-align: left; }
QFrame#side QPushButton#reset, QFrame#side QPushButton#cropbtn { background: #3a3a3c; border: none; border-radius: 15px;
    padding: 7px 14px; font-size: 13px; text-align: center; }
QFrame#side QPushButton#reset:hover, QFrame#side QPushButton#cropbtn:hover { background: #48484a; }
QFrame#side QPushButton#reset:disabled, QFrame#side QPushButton#cropbtn:disabled { color: #6e6e73; background: #2c2c2e; }
QFrame#side QPushButton#cropok { background: #ffd60a; color: #1c1c1e; border: none; border-radius: 15px;
    padding: 7px 14px; font-size: 14px; font-weight: 700; text-align: center; }
QFrame#side QPushButton#cropok:hover { background: #ffe14d; }
QLabel#panelhead { color: #98989f; font-size: 13px; font-weight: 700; padding-bottom: 7px;
    border-bottom: 2px solid #48484a; }
QFrame#side QPushButton#cropitem { background: transparent; border: none; padding: 4px 0; font-size: 15px;
    color: #d1d1d6; text-align: left; }
QFrame#side QPushButton#cropitem:hover { color: #ffffff; }
QFrame#side QPushButton#cropitem[on="true"] { color: #ffffff; }
QLabel#cropitemlabel { font-size: 15px; color: #d1d1d6; padding: 4px 0; }
QFrame#side QPushButton#cropbig { background: #48484a; border: none; border-radius: 20px; min-height: 40px;
    max-height: 40px; font-size: 15px; color: #f2f2f7; text-align: center; padding: 0 12px; }
QFrame#side QPushButton#cropbig:hover { background: #545456; }
QFrame#side QPushButton#cropbig:disabled { background: #2f2f31; color: #6e6e73; }
QFrame#side QPushButton#aspect:checked { color: #ffffff; }
QFrame#side QPushButton#aspect { background: transparent; border: none; border-radius: 0; padding: 5px 0;
    font-size: 15px; color: #aeaeb2; text-align: left; }
QFrame#side QPushButton#aspect:hover { color: #ffffff; }
QFrame#side QPushButton#aspect:checked { color: #ffffff; }
QFrame#side QPushButton#flip { background: transparent; border: none; padding: 4px 0; font-size: 15px;
    color: #d1d1d6; text-align: left; }
QFrame#side QPushButton#flip:hover { color: #ffffff; }
QFrame#side QPushButton#orient { background: #2c2c2e; border: 1px solid #48484a; border-radius: 6px; padding: 0;
    font-size: 15px; min-width: 34px; max-width: 34px; min-height: 24px; max-height: 24px; text-align: center; }
QFrame#side QPushButton#orient:checked { background: #545456; border-color: #8e8e93; }
QFrame#side QPushButton#swatch { border-radius: 11px; min-width: 22px; max-width: 22px; min-height: 22px;
    max-height: 22px; padding: 0; border: 2px solid transparent; }
QFrame#side QPushButton#swatch:checked { border: 2px solid #ffffff; }
QFrame#side QPushButton#small2 { background: #3a3a3c; border: none; border-radius: 10px; padding: 3px 10px;
    font-size: 12px; text-align: center; }
QFrame#side QPushButton#small2:hover { background: #48484a; }
QFrame#side QPushButton#discard { background: #3a3a3c; border: 1px solid #ff453a; color: #ff6961; border-radius: 15px;
    padding: 7px 14px; font-size: 13px; font-weight: 600; text-align: center; }
QFrame#side QPushButton#discard:hover { background: rgba(255, 69, 58, 50); }
QFrame#side QPushButton#discard:disabled { color: #6e6e73; border-color: #3a3a3c; background: #2c2c2e; }
QFrame#side QSpinBox { background: #2c2c2e; border: 1px solid #545456; border-radius: 6px; padding: 2px 4px; }
"""

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
QPushButton#stripnav[home="true"] { border: 2px solid #ffd60a; }
QPushButton#photoarrow { background: rgba(28,28,30,170); color: #f2f2f7; font-size: 22px;
    border: 1.5px solid #8e8e93; border-radius: 22px; padding-bottom: 3px; }
QPushButton#photoarrow:hover { background: rgba(58,58,60,220); border-color: #d1d1d6; }
QFrame#scenebar QPushButton#live { background: #ffd60a; color: #1c1c1e; font-weight: 700; }
/* come la barra Live di Foto: striscia tra parentesi, volume e menu "Live" */
QFrame#scenebar QFrame#stripbox { background: #3a3a3c; border: none; border-radius: 8px; }
QFrame#scenebar QPushButton#bracket { background: transparent; border: none; color: #f2f2f7;
    font-size: 15px; font-weight: 800; padding: 0; min-width: 18px; max-width: 18px; border-radius: 6px; }
QFrame#scenebar QPushButton#bracket:hover { background: #48484a; }
QFrame#scenebar QPushButton#volume { background: #3a3a3c; border: none; border-radius: 10px; padding: 0; }
QFrame#scenebar QPushButton#volume:hover { background: #48484a; }
QFrame#scenebar QPushButton#livemode { background: #3a3a3c; border: none; border-radius: 13px;
    padding: 0 12px; font-size: 13px; }
QFrame#scenebar QLabel#framestatus { color: #98989f; font-size: 12px; }
QFrame#scenebar QPushButton#livemode:hover { background: #48484a; }
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
QFrame#printbox { background: transparent; border: none; }
/* sottosezioni del pannello (Info): come le voci di Regola — riga sottile sopra, titolo 15 px */
QLabel#subhead { color: #f2f2f7; font-size: 15px; padding-top: 10px; border-top: 1px solid #3a3a3c;
                 margin-top: 4px; }
QFrame#infocard { background: #2c2c2e; border: none; border-radius: 10px; }
QFrame#infocard QLabel { background: transparent; }
QFrame#side QPushButton#textlink { background: transparent; border: none; padding: 0 2px; color: #0a84ff;
    font-size: 12px; text-align: left; }
QFrame#side QPushButton#textlink:hover { color: #409cff; }
QFrame#printbox QLabel { background: transparent; }
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
STYLE += EDIT_STYLE + """
QProgressBar#progress { background: #3a3a3c; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }
QProgressBar#progress::chunk { background: #d1d1d6; border-radius: 2px; }
QLabel#editbadge { color: #98989f; font-size: 12px; }
QPushButton#toolround { background: #2c2c2e; border: 1px solid #48484a; border-radius: 16px; padding: 0; }
QPushButton#toolround:hover { background: #3a3a3c; }
QPushButton#toolround:checked { background: #545456; }
QPushButton#toolpill { background: #2c2c2e; border: 1px solid #48484a; border-radius: 15px;
                       padding: 0 16px; font-size: 13px; min-height: 30px; max-height: 30px; }
QPushButton#toolpill:hover { background: #3a3a3c; }
QPushButton#donepill { background: #ffd60a; color: #1c1c1e; border: none; border-radius: 16px;
                       padding: 0 18px; font-size: 14px; font-weight: 600; min-height: 32px; max-height: 32px; }
QPushButton#donepill:hover { background: #ffe14d; }
QPushButton#toolpill[compact="true"] { padding: 0; min-width: 40px; max-width: 40px; font-size: 16px; }
"""
