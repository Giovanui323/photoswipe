"""Stile dell'app: i colori (un nome per ruolo) e il foglio di stile Qt che li usa, in un solo posto.

Nel foglio di stile i colori si scrivono $nome; per un tema chiaro basta un secondo dizionario
con gli stessi nomi."""
from __future__ import annotations

from string import Template

# tema scuro, come Foto di macOS
DARK = {
    "bg_window": "#1c1c1e",
    "bg_panel": "#232325",
    "bg_control": "#2c2c2e",
    "bg_hover": "#3a3a3c",
    "bg_pressed": "#48484a",
    "bg_checked": "#545456",
    "bg_sunken": "#1f1f21",
    "bar_bg": "#323234",          # cursori a barra di Regola (disegnati a mano)
    "bar_bg_off": "#2a2a2c",
    "bar_fill": "#4a4a4d",
    "bar_zero": "#5a5a5e",
    "bar_mark": "#a1a1a6",
    "bg_slider_off": "#636366",
    "bg_auto_on": "#8e8e93",
    "bg_fill": "#d1d1d6",
    "bg_knob": "#f2f2f7",
    "selected": "#0a84ff",
    "accent": "#ffd60a",
    "accent_hover": "#ffe14d",
    "text": "#f2f2f7",
    "text_strong": "#ffffff",
    "text_detail": "#d1d1d6",
    "text_aspect": "#aeaeb2",
    "text_2": "#98989f",
    "text_off": "#8a8a8f",
    "text_caption_off": "#7c7c80",
    "text_on_accent": "#1c1c1e",
    "text_on_color": "#111",
    "link": "#409cff",
    "link_hover": "#5eb0ff",
    "text_warn": "#ffb340",
    "text_danger": "#ff6961",
    "text_fav": "#ff375f",
    "text_ok": "#7fe3b4",
    "filter_on": "#64d2ff",
    "line_divider": "#3a3a3c",
    "line_side": "#2f2f31",
    "line_soft": "#48484a",
    "line_control": "#757579",
    "line_grid": "#545456",
    "line_check": "#8e8e93",
    "line_strong": "#8e8e93",
    "line_strong_hover": "#d1d1d6",
    "line_auto_hover": "#f2f2f7",
    "line_selected": "#ffffff",
    "line_danger": "#ff453a",
    "focus": "#0a84ff",
    "yes": "#2ad48e",
    "no": "#ff4458",
    "skip": "#3ca4ff",
    "trash": "#b46cff",
    "yesvideo": "#4fd1c5",
    # tipo di elemento (etichetta in alto)
    "kind_photo": "#5b8def",
    "kind_pano": "#a46bf0",
    "kind_live": "#f0b429",
    "kind_video": "#4fb7a8",
}
COLORS = DARK


def qss(template: str) -> str:
    """Foglio di stile con i $nomi sostituiti dai colori del tema."""
    return Template(template).substitute(COLORS)


# colore del bordo della miniatura attuale: quello del tipo scelto nel filtro a sinistra
STRIP_FRAME_COLORS = {k: COLORS[k] for k in ("yes", "no", "skip", "trash")}
CHOICE_COLOR = dict(STRIP_FRAME_COLORS)  # = pulsanti
KIND_COLOR = {k: COLORS[f"kind_{k}"] for k in ("photo", "pano", "live", "video")}


def apply_dark_palette(app) -> None:
    """Windows/Linux: Fusion scuro, così finestre di dialogo e menu non restano chiari."""
    from PySide6.QtGui import QColor, QPalette
    app.setStyle("Fusion")
    pal = QPalette()
    for role, name in ((QPalette.Window, "bg_window"), (QPalette.WindowText, "text"), (QPalette.Base, "bg_control"),
                       (QPalette.AlternateBase, "bg_panel"), (QPalette.Text, "text"), (QPalette.Button, "bg_control"),
                       (QPalette.ButtonText, "text"), (QPalette.Highlight, "selected"),
                       (QPalette.HighlightedText, "text_strong"), (QPalette.ToolTipBase, "bg_control"),
                       (QPalette.ToolTipText, "text")):
        pal.setColor(role, QColor(COLORS[name]))
    app.setPalette(pal)

EDIT_STYLE = qss("""
QFrame#segbar { background: $bg_control; border: 1px solid $line_soft; border-radius: 16px; }
QFrame#side QFrame#segbar QPushButton { background: transparent; border: none; border-radius: 12px;
    padding: 5px 0; font-size: 13px; font-weight: 600; color: $text; text-align: center; }
QFrame#side QFrame#segbar QPushButton:hover { background: $bg_hover; }
QFrame#side QFrame#segbar QPushButton:checked { background: $bg_checked; }
QFrame#side QFrame#segbar QPushButton:disabled { color: $text_off; }
QLabel#editnote { color: $text_2; font-size: 11px; }
QFrame#side QPushButton#chev { background: transparent; border: none; padding: 0; font-size: 12px; color: $text_detail;
    min-width: 14px; max-width: 14px; text-align: center; }
QFrame#side QPushButton#sectitle { background: transparent; border: none; padding: 2px 0; font-size: 15px;
    color: $text; text-align: left; }
QFrame#side QPushButton#sectitle:hover { color: $text_strong; }
QFrame#side QPushButton#secundo { background: transparent; border: none; padding: 0; font-size: 15px; color: $text_2;
    min-width: 20px; max-width: 20px; text-align: center; }
QFrame#side QPushButton#secundo:hover { color: $text; }
QFrame#side QPushButton#auto { background: transparent; border: 1px solid $line_strong; border-radius: 8px;
    padding: 0 5px; font-size: 9px; font-weight: 700; color: $text_detail; min-height: 15px; max-height: 15px;
    text-align: center; }
QFrame#side QPushButton#auto:hover { border-color: $line_auto_hover; color: $text_strong; }
QFrame#side QPushButton#auto[on="true"] { background: $bg_auto_on; border-color: $line_strong; color: $text_on_accent; }
QFrame#side QPushButton#secundo:disabled { color: $text_caption_off; }
QFrame#side QPushButton#opts { background: transparent; border: none; padding: 2px 0 2px 18px; font-size: 13px;
    color: $text_detail; text-align: left; }
QFrame#side QPushButton#reset { background: $bg_hover; border: none; border-radius: 15px;
    padding: 7px 14px; font-size: 13px; text-align: center; }
QFrame#side QPushButton#reset:hover { background: $bg_pressed; }
QFrame#side QPushButton#reset:disabled { color: $text_off; background: $bg_control; }
QFrame#side QPushButton#cropok { background: $accent; color: $text_on_accent; border: none; border-radius: 15px;
    padding: 7px 14px; font-size: 14px; font-weight: 700; text-align: center; }
QFrame#side QPushButton#cropok:hover { background: $accent_hover; }
QLabel#panelhead { color: $text_2; font-size: 13px; font-weight: 700; padding-bottom: 7px;
    border-bottom: 2px solid $line_soft; }
QFrame#side QPushButton#cropitem { background: transparent; border: none; padding: 4px 0; font-size: 15px;
    color: $text_detail; text-align: left; }
QFrame#side QPushButton#cropitem:hover { color: $text_strong; }
QFrame#side QPushButton#cropitem[on="true"] { color: $text_strong; }
QLabel#cropitemlabel { font-size: 15px; color: $text_detail; padding: 4px 0; }
QFrame#side QPushButton#cropbig { background: $bg_pressed; border: none; border-radius: 20px; min-height: 40px;
    max-height: 40px; font-size: 15px; color: $text; text-align: center; padding: 0 12px; }
QFrame#side QPushButton#cropbig:hover { background: $bg_checked; }
QFrame#side QPushButton#cropbig:disabled { background: $bg_control; color: $text_off; }
QFrame#side QPushButton#aspect:checked { color: $text_strong; }
QFrame#side QPushButton#aspect { background: transparent; border: none; border-radius: 0; padding: 5px 0;
    font-size: 15px; color: $text_aspect; text-align: left; }
QFrame#side QPushButton#aspect:hover { color: $text_strong; }
QFrame#side QPushButton#aspect:checked { color: $text_strong; }
QFrame#side QPushButton#flip { background: transparent; border: none; padding: 4px 0; font-size: 15px;
    color: $text_detail; text-align: left; }
QFrame#side QPushButton#flip:hover { color: $text_strong; }
QFrame#side QPushButton#orient { background: $bg_control; border: 1px solid $line_soft; border-radius: 6px; padding: 0;
    font-size: 15px; min-width: 34px; max-width: 34px; min-height: 24px; max-height: 24px; text-align: center; }
QFrame#side QPushButton#orient:checked { background: $bg_checked; border-color: $line_strong; }
QFrame#side QPushButton#swatch { border-radius: 11px; min-width: 22px; max-width: 22px; min-height: 22px;
    max-height: 22px; padding: 0; border: 2px solid transparent; }
QFrame#side QPushButton#swatch:checked { border: 2px solid $line_selected; }
QFrame#side QPushButton#small2 { background: $bg_hover; border: none; border-radius: 10px; padding: 3px 10px;
    font-size: 12px; text-align: center; }
QFrame#side QPushButton#small2:hover { background: $bg_pressed; }
QFrame#side QPushButton#discard { background: $bg_hover; border: 1px solid $line_danger; color: $text_danger; border-radius: 15px;
    padding: 7px 14px; font-size: 13px; font-weight: 600; text-align: center; }
QFrame#side QPushButton#discard:hover { background: rgba(255, 69, 58, 50); }
QFrame#side QPushButton#discard:disabled { color: $text_off; border-color: $line_divider; background: $bg_control; }
QFrame#side QSpinBox { background: $bg_control; border: 1px solid $line_control; border-radius: 6px; padding: 2px 4px; }
""")

# Stile ispirato a Foto di macOS (scuro, barre a "pillola", accento giallo) e, per la scelta,
# a Tinder: pulsanti rotondi centrati sotto la foto. Font di sistema (SF su Mac, Segoe su Windows).
STYLE = qss("""
QMainWindow, QDialog { background: $bg_window; }
QWidget { color: $text; font-size: 13px; }
QLabel, QRadioButton, QCheckBox { background: transparent; }
QToolTip { background: $bg_control; color: $text; border: 1px solid $line_soft; border-radius: 6px; padding: 4px 7px; font-size: 11px; }

/* pulsanti normali: pillole grigie */
QPushButton { background: $bg_control; border: 1px solid $line_control; border-radius: 15px; padding: 6px 14px; }
QPushButton:hover { background: $bg_hover; }
QPushButton:pressed { background: $bg_pressed; }
QPushButton:disabled { color: $text_off; background: $bg_panel; border-color: $line_divider; }

/* barra in alto, come la barra strumenti di Foto */
QFrame#pill { background: $bg_control; border: 1px solid $line_soft; border-radius: 18px; }
QFrame#zoompill { background: rgba(0, 0, 0, 130); border: 1px solid rgba(255, 255, 255, 40);
                  border-radius: 14px; }
QFrame#zoompill QLabel { color: $text_strong; background: transparent; }
QFrame#pill QPushButton { background: transparent; border: none; border-radius: 14px;
                          font-size: 17px; min-width: 30px; min-height: 28px; padding: 0 6px; }
QFrame#pill QPushButton:hover { background: $bg_hover; }
QFrame#navbar QPushButton { background: transparent; border: none; border-radius: 8px; }
QFrame#navbar QPushButton:hover { background: $bg_hover; }
QFrame#pill QPushButton:disabled { color: $text_off; background: transparent; }
QPushButton#fav[on="true"] { color: $text_fav; }
QLabel#chosen { border-radius: 8px; padding: 2px 9px; font-size: 11px; font-weight: 700; color: $text_on_color; }
QPushButton#info[on="true"] { background: $bg_pressed; }
QSlider::groove:horizontal { height: 4px; background: $bg_slider_off; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $bg_fill; border-radius: 2px; }
QSlider::handle:horizontal { width: 18px; height: 18px; margin: -7px 0; background: $bg_knob;
                             border-radius: 9px; }
QSlider::groove:horizontal:disabled { background: $bg_pressed; }
QSlider::sub-page:horizontal:disabled { background: $bg_slider_off; }
QSlider::handle:horizontal:disabled { background: $bg_slider_off; }
QLabel#heading { font-size: 15px; font-weight: 700; }
QLabel#subtitle, QLabel#counter { color: $text_2; font-size: 12px; }

/* foto a tutto schermo, sullo stesso grigio della finestra */
QGraphicsView { border: none; background: $bg_window; }
QLabel#stamp { background: rgba(0, 0, 0, 130); color: $text_strong; font-size: 13px; font-weight: 600;
               border-radius: 12px; padding: 5px 12px; }
QLabel#chip { background: rgba(28, 28, 30, 215); color: $text_warn; font-size: 12px; font-weight: 600;
              border: 1px solid rgba(255, 179, 64, 90); border-radius: 12px; padding: 5px 12px; }
QLabel#toast { background: rgba(44, 44, 46, 235); color: $text_danger; font-size: 13px;
               border: 1px solid $line_soft; border-radius: 14px; padding: 8px 16px; }

/* barra della striscia (Live e video): pillola che galleggia sotto la foto */
QFrame#scenebar { background: $bg_control; border: 1px solid $line_soft; border-radius: 18px; }
QFrame#snap_bar { background: rgba(28, 28, 30, 215); border: 1px solid $line_soft; border-radius: 10px; }
QFrame#scenebar QLabel { color: $text_2; font-size: 12px; }
QFrame#scenebar QPushButton { background: $bg_hover; border: none; border-radius: 13px; padding: 5px 12px; }
QFrame#scenebar QPushButton:hover { background: $bg_pressed; }
QFrame#scenebar QPushButton#arrow { background: transparent; font-size: 16px; color: $text;
    border: 1.5px solid $line_strong; border-radius: 15px; min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px; padding: 0; }
QFrame#scenebar QPushButton#arrow:hover { background: $bg_hover; border-color: $line_strong_hover; }
QFrame#scenebar QPushButton#play { background: transparent; font-size: 16px; color: $text;
    border: 1.5px solid $line_strong; border-radius: 15px; min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px; padding: 0; }
QFrame#scenebar QPushButton#play:hover { background: $bg_hover; border-color: $line_strong_hover; }
/* pulsanti della striscia in basso: bordo e hover, come quelli dei fotogrammi */
QPushButton#stripnav { background: transparent; color: $text; font-size: 13px;
    border: 1.5px solid $line_strong; border-radius: 15px; padding: 3px 10px; }
QPushButton#stripnav:hover { background: $bg_hover; border-color: $line_strong_hover; }
QPushButton#stripnav[home="true"] { border: 2px solid $accent; }
QPushButton#photoarrow { background: rgba(28,28,30,170); color: $text; font-size: 22px;
    border: 1.5px solid $line_strong; border-radius: 22px; padding-bottom: 3px; }
QPushButton#photoarrow:hover { background: rgba(58,58,60,220); border-color: $line_strong_hover; }
QFrame#scenebar QPushButton#live { background: $accent; color: $text_on_accent; font-weight: 700; }
/* come la barra Live di Foto: striscia tra parentesi, volume e menu "Live" */
QFrame#scenebar QFrame#stripbox { background: $bg_hover; border: none; border-radius: 8px; }
QFrame#scenebar QPushButton#bracket { background: transparent; border: none; color: $text;
    font-size: 15px; font-weight: 800; padding: 0; min-width: 18px; max-width: 18px; border-radius: 6px; }
QFrame#scenebar QPushButton#bracket:hover { background: $bg_pressed; }
QFrame#scenebar QPushButton#volume { background: $bg_hover; border: none; border-radius: 10px; padding: 0; }
QFrame#scenebar QPushButton#volume:hover { background: $bg_pressed; }
QFrame#scenebar QPushButton#livemode { background: $bg_hover; border: none; border-radius: 13px;
    padding: 0 12px; font-size: 13px; }
QFrame#scenebar QLabel#framestatus { color: $text_2; font-size: 12px; }
QFrame#scenebar QPushButton#livemode:hover { background: $bg_pressed; }
QFrame#scenebar QPushButton#live:hover { background: $accent_hover; }

/* scelta, stile Tinder: cerchi scuri con anello e simbolo colorati; al passaggio si riempiono */
QPushButton[round="true"] { background: $bg_panel; border: 2px solid $line_divider; padding: 0; font-weight: 700; }
QPushButton#no      { border-color: $no; color: $no; border-radius: 33px; font-size: 28px; }
QPushButton#yes     { border-color: $yes; color: $yes; border-radius: 33px; font-size: 28px; }
QPushButton#skip    { border-color: $skip; color: $skip; border-radius: 24px; font-size: 20px; }
QPushButton#trash   { border-color: $trash; color: $trash; border-radius: 24px; font-size: 18px; }
QPushButton#yesvideo{ border-color: $yesvideo; color: $yesvideo; border-radius: 24px; font-size: 20px; }
/* al passaggio e a scelta fatta il simbolo resta colorato pieno; il cerchio prende una tinta */
QPushButton#no:hover      { background: rgba(255, 68, 88, 50); border-width: 3px; }
QPushButton#yes:hover     { background: rgba(42, 212, 142, 50); border-width: 3px; }
QPushButton#skip:hover    { background: rgba(60, 164, 255, 50); border-width: 3px; }
QPushButton#trash:hover   { background: rgba(180, 108, 255, 50); border-width: 3px; }
QPushButton#yesvideo:hover{ background: rgba(79, 209, 197, 50); border-width: 3px; }
QPushButton[round="true"]:pressed { background: $bg_pressed; }
/* già deciso (tornando indietro): il cerchio della scelta fatta resta tinto, anello spesso */
QPushButton#no[chosen="true"]    { background: rgba(255, 68, 88, 80); border-width: 4px; }
QPushButton#yes[chosen="true"]   { background: rgba(42, 212, 142, 80); border-width: 4px; }
QPushButton#skip[chosen="true"]  { background: rgba(60, 164, 255, 80); border-width: 4px; }
QPushButton#trash[chosen="true"] { background: rgba(180, 108, 255, 80); border-width: 4px; }
QPushButton#yesvideo[chosen="true"] { background: rgba(79, 209, 197, 80); border-width: 4px; }
QPushButton[round="true"]:disabled { background: $bg_sunken; border-color: $line_soft; color: $text_off; }
/* con l'ID le regole sopra vincono su [round]:disabled: serve ripeterlo per ogni pulsante */
QPushButton#no:disabled, QPushButton#yes:disabled, QPushButton#skip:disabled,
QPushButton#trash:disabled, QPushButton#yesvideo:disabled { background: $bg_sunken; border-color: $line_soft;
                                                             color: $text_off; }
QLabel#cap { color: $text_2; font-size: 11px; }
QLabel#cap:disabled { color: $text_caption_off; }
QLabel#snaps { color: $text_ok; font-size: 11px; font-weight: 700; padding-bottom: 4px;
               border-bottom: 1px solid $line_divider; }
QLabel#snaps[empty="true"] { background: transparent; border: none; }
QFrame#next { background: $bg_control; border: 1px solid $line_divider; border-radius: 12px; }
QFrame#printbox { background: transparent; border: none; }
/* sottosezioni del pannello (Info): riga sottile sopra, titolo piccolo in maiuscolo grigio */
QLabel#subhead { color: $text_2; font-size: 11px; font-weight: 700; padding-top: 12px;
                 border-top: 1px solid $line_divider; margin-top: 6px; }
QFrame#infocard { background: $bg_control; border: none; border-radius: 10px; }
QFrame#infocard QLabel { background: transparent; }
QFrame#side QPushButton#textlink { background: transparent; border: none; padding: 0 2px; color: $link;
    font-size: 12px; text-align: left; }
QFrame#side QPushButton#textlink:hover { color: $link_hover; }
QFrame#side QPushButton#textlink:disabled { color: $text_2; }
QFrame#printbox QLabel { background: transparent; }
QFrame#next QLabel { background: transparent; }
QLabel#muted { color: $text_2; }
QPushButton#small { font-size: 12px; padding: 4px 9px; border-radius: 12px; }
QLabel#details { color: $text_detail; font-size: 12px; }
QFrame#settings { background: $bg_control; border: 1px solid $line_soft; border-radius: 14px; }
QFrame#settings QPushButton { background: $bg_hover; border: none; border-radius: 8px; text-align: left; padding: 7px 12px; }
QFrame#settings QPushButton:hover { background: $bg_pressed; }
QFrame#settings QComboBox { background: $bg_hover; border: none; }
QFrame#settings QPushButton#small { font-size: 12px; padding: 4px 10px; border-radius: 11px; text-align: center; }
QFrame#settings QPushButton#textlink { background: transparent; color: $link; padding: 6px 0 0 0; }
QFrame#settings QPushButton#textlink:hover { color: $link_hover; }
QLabel#settingshead { color: $text; font-size: 13px; font-weight: 600; padding: 12px 0 0 0; margin: 0; }
QLabel#settingsnote { color: $text_2; font-size: 11px; }
QFrame#settingsline { background: $line_divider; }

/* pannello laterale (cartelle e impostazioni), come il pannello Regola di Foto */
QFrame#side { background: $bg_panel; border-left: 1px solid $line_side; }
QLabel#section { color: $text_2; font-size: 11px; font-weight: 700; padding-top: 10px;
                 border-bottom: 1px solid $line_divider; padding-bottom: 4px; }
QScrollArea#sidescroll, QScrollArea#sidescroll > QWidget > QWidget#sidebody,
QScrollArea#setupscroll, QScrollArea#setupscroll > QWidget > QWidget#setuppage { background: transparent; }
QFrame#side QPushButton { border-radius: 8px; text-align: left; padding: 7px 12px; }
QFrame#side QPushButton#small { font-size: 12px; padding: 4px 9px; border-radius: 12px; text-align: center; }
QComboBox { background: $bg_control; border: 1px solid $line_control; border-radius: 8px; padding: 5px 10px; }
QComboBox:hover { background: $bg_hover; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url(__CHEVRON__); width: 10px; height: 6px; }

/* focus da tastiera visibile (Tab) */
QPushButton:focus { outline: none; border: 2px solid $focus; }
QPushButton#start:focus { border: 2px solid $focus; }
QComboBox:focus, QCheckBox:focus, QRadioButton:focus { outline: none; }
QComboBox:focus { border: 2px solid $focus; }

/* barre di scorrimento scure, sottili */
QScrollBar:vertical { width: 8px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: $bg_checked; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QComboBox QAbstractItemView { background: $bg_control; border: 1px solid $line_soft; color: $text;
                              selection-background-color: $selected; outline: 0; padding: 4px; }
/* ogni voce dell'elenco ha il suo bordo; al passaggio del mouse si evidenzia */
QComboBox QAbstractItemView::item { min-height: 26px; padding: 6px 12px; margin: 2px 4px;
    border: 1px solid $line_soft; border-radius: 8px; color: $text; }
QComboBox QAbstractItemView::item:hover { background: $bg_hover; border: 1px solid $line_strong; }
QComboBox QAbstractItemView::item:selected { background: $selected; border: 1px solid $focus; color: $text_strong; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $line_check; border-radius: 4px; background: $bg_control; }
QCheckBox::indicator:checked { background: $selected; border-color: $focus; }

/* messaggi a tutta pagina (download, fine) */
QLabel#big { font-size: 17px; color: $text_detail; }

/* schermata iniziale */
QFrame#setup { background: $bg_panel; border: 1px solid $line_soft; border-radius: 18px; }
QFrame#setup QPushButton { border-radius: 10px; }
QRadioButton { spacing: 8px; padding: 2px 0; }
QRadioButton::indicator { width: 14px; height: 14px; border-radius: 8px; border: 2px solid $line_strong;
                          background: $bg_control; }
QRadioButton::indicator:checked { background: $selected; border-color: $focus; }
QLabel#h1 { font-size: 24px; font-weight: 700; }
QLabel#step { font-size: 16px; font-weight: 600; }
QLabel#warn { color: $text_warn; }
QLabel#path { background: $bg_window; border: 1px solid $line_control; border-radius: 8px; padding: 8px 10px;
              color: $text_detail; }
QLabel#path[empty="true"] { color: $text_2; }
QPushButton#start, QPushButton#primary { background: $accent; color: $text_on_accent; border: none;
                    border-radius: 18px; font-size: 16px; font-weight: 700; padding: 9px 26px; }
QPushButton#start:hover, QPushButton#primary:hover { background: $accent_hover; }
QPushButton#start:disabled { background: $bg_hover; color: $text_2; }
""")
STYLE += EDIT_STYLE + qss("""
QProgressBar#progress { background: $bg_hover; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }
QProgressBar#progress::chunk { background: $bg_fill; border-radius: 2px; }
QLabel#editbadge { color: $text_2; font-size: 12px; }
QPushButton#toolround { background: $bg_control; border: 1px solid $line_soft; border-radius: 16px; padding: 0; }
QPushButton#toolround:hover { background: $bg_hover; }
QPushButton#toolround:checked { background: $bg_checked; }
QPushButton#toolpill { background: $bg_control; border: 1px solid $line_soft; border-radius: 15px;
                       padding: 0 16px; font-size: 13px; min-height: 30px; max-height: 30px; }
QPushButton#toolpill:hover { background: $bg_hover; }
QPushButton#donepill { background: $accent; color: $text_on_accent; border: none; border-radius: 16px;
                       padding: 0 18px; font-size: 14px; font-weight: 600; min-height: 32px; max-height: 32px; }
QPushButton#donepill:hover { background: $accent_hover; }
QPushButton#toolpill[compact="true"] { padding: 0; min-width: 40px; max-width: 40px; font-size: 16px; }
""")

# focus da tastiera (Tab) visibile anche dove le regole sopra, più specifiche, tolgono il bordo
FOCUS_IN_SIDE = ("chev", "sectitle", "secundo", "auto", "opts", "reset", "cropok", "cropitem", "cropbig",
                 "aspect", "flip", "orient", "swatch", "small", "small2", "discard", "textlink")
STYLE += qss("".join(f"QFrame#side QPushButton#{n}:focus {{ border: 2px solid $focus; }}\n" for n in FOCUS_IN_SIDE)
             + "QFrame#side QFrame#segbar QPushButton:focus { border: 2px solid $focus; }\n"
             + "QFrame#pill QPushButton:focus { border: 2px solid $focus; }\n")


def help_html(text: str) -> str:
    """Aiuto in HTML: titoletti (righe in MAIUSCOLO) piccoli, grigi e staccati dal testo."""
    from html import escape
    out = []
    for line in text.split("\n"):
        if line and line.isupper() and len(line) < 40:
            out.append(f"<p style='color:{COLORS['text_2']}; font-size:11px; font-weight:700; letter-spacing:1px;"
                       f" margin:16px 0 4px 0'>{escape(line)}</p>")
        elif not line.strip():
            out.append("<p style='margin:6px 0'></p>")
        else:
            lead = len(line) - len(line.lstrip(" "))
            out.append(f"<p style='margin:2px 0 2px {lead * 6}px'>{escape(line.lstrip(' '))}</p>")
    return "".join(out)
