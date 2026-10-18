"""Home (casa) nella barra in alto, e la conferma delle modifiche: "Fine" e "Conferma le modifiche"."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
    assert "Fine" in win.btn_wand.toolTip() and "OK" not in win.btn_wand.toolTip()
    assert win.btn_confirm_foot.isVisible() and win.btn_confirm_foot.text() == "Conferma le modifiche"
    assert win.btn_discard.isVisible() and win.btn_discard.text() == "Annulla le modifiche"
    assert win.btn_confirm_foot.geometry().bottom() <= win.btn_discard.geometry().top()
    click(qapp, win, win.btn_confirm_foot)
    assert not win.edit_pending()
    assert win.item_edit().get("enhanced")
