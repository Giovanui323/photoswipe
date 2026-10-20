"""Home (casa) nella barra in alto, e la conferma delle modifiche nel pannello."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from test_ui import PHOTO1, click, go, open_folder, qapp, sd, sd_template, wait, win  # noqa: E402,F401


def test_home_button_goes_back_to_folder_choice(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    assert win.btn_home.isVisible()
    click(qapp, win, win.btn_home)
    assert wait(qapp, lambda: win.stack.currentWidget() is win.setup_page)


def test_home_waits_while_edit_is_open(qapp, win, sd):
    """Con modifiche non confermate la casa non esce: non si perdono."""
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.auto_enhance()
    assert win.edit_pending()
    click(qapp, win, win.btn_home)
    assert win.stack.currentWidget() is not win.setup_page
    assert win.edit_pending()
    win.cancel_edit()


def test_wand_then_confirm_button_below_title_and_no_ok(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_wand)
    assert "Conferma le modifiche" in win.btn_wand.toolTip() and "OK" not in win.btn_wand.toolTip()
    assert win.btn_confirm_foot.isVisible() and win.btn_confirm_foot.text() == "Conferma le modifiche"
    assert win.btn_discard.isVisible() and win.btn_discard.text() == "Annulla le modifiche"
    assert win.btn_confirm_foot.geometry().bottom() <= win.btn_discard.geometry().top()
    click(qapp, win, win.btn_confirm_foot)
    assert not win.edit_pending()
    assert win.item_edit().get("enhanced")


@pytest.mark.parametrize("confirmed", [True, False])
def test_title_never_covers_restore_button(qapp, win, sd, confirmed):
    """Live con modifiche: il badge LIVE e il nome non devono coprire "Ripristina originale"."""
    from PySide6.QtCore import QRect
    from test_core import LIVE
    from test_ui import go as _go, pump, wait
    open_folder(qapp, win, sd)
    _go(qapp, win, f"{LIVE}.MP4")
    win.auto_enhance()
    if confirmed:
        win.confirm_edit()
    # la modifica si calcola in background: sotto carico ci vuole più di un attimo
    assert wait(qapp, win.btn_restore.isVisible, 30)
    for width in (1000, 1100, 1200, 1400):
        win.resize(width, 800)
        pump(qapp, 0.3)
        win.balance_top()
        pump(qapp, 0.2)
        r = QRect(win.btn_restore.mapTo(win, win.btn_restore.rect().topLeft()), win.btn_restore.size())
        for w in (win.badge, win.heading):
            if not w.isVisible():
                continue
            t = QRect(w.mapTo(win, w.rect().topLeft()), w.size())
            assert not r.intersects(t), f"larghezza {width}: {w.text() or w.objectName()} copre 'Ripristina originale' {r} {t}"
