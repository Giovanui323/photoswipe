"""Barra in alto: ‹ Cartelle, ↶ Annulla, ↷ Ripristina (come in Word), anche con un ritaglio aperto."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402,F401

import exporter  # noqa: E402
from test_ui import (DATED1, PHOTO1, PHOTO2, click, exported, exports_done, go,  # noqa: E402,F401
                     open_folder, qapp, sd, sd_template, win)


def test_redo_puts_back_an_undone_yes(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    item_id = win.current().id
    assert not win.btn_undo.isEnabled() and not win.btn_redo.isEnabled()
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert exported(win) == [f"Foto/{DATED1}"]
    assert win.btn_undo.isEnabled() and not win.btn_redo.isEnabled()
    click(qapp, win, win.btn_undo)
    exports_done(qapp, win)
    assert exported(win) == [] and win.session.get(item_id) is None
    assert win.btn_redo.isEnabled()
    click(qapp, win, win.btn_redo)                 # di nuovo SÌ, di nuovo copiata
    exports_done(qapp, win)
    assert win.session.get(item_id)["choice"] == "yes"
    assert exported(win) == [f"Foto/{DATED1}"]
    assert win.current().id != item_id             # come dopo una scelta: si va avanti
    assert not win.btn_redo.isEnabled() and win.btn_undo.isEnabled()


def test_redo_moves_to_trash_again(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO2)
    original = next(sd.rglob(PHOTO2))
    click(qapp, win, win.btn_trash)
    click(qapp, win, win.btn_undo)
    assert original.exists()
    click(qapp, win, win.btn_redo)
    assert not original.exists()
    assert (sd / exporter.TRASH_DIR / original.relative_to(sd)).exists()


def test_new_choice_empties_redo(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_no)
    click(qapp, win, win.btn_undo)
    assert win.btn_redo.isEnabled()
    click(qapp, win, win.btn_skip)                 # scelta nuova: Ripristina non ha più senso
    assert not win.btn_redo.isEnabled() and not win.redo_stack


def test_top_bar_answers_during_unconfirmed_edit(qapp, win, sd):
    """Con modifiche da confermare i pulsanti in alto non sono spenti: dicono cosa fare."""
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_no)
    win.auto_enhance()
    assert win.edit_pending()
    assert win.nav_pill.isEnabled() and win.btn_undo.isEnabled() and win.btn_home.isEnabled()
    before = win.session.get(win.current().id)
    click(qapp, win, win.btn_undo)
    assert "OK oppure Annulla" in win.status.text()
    assert win.edit_pending() and win.session.get(win.current().id) == before
    click(qapp, win, win.btn_home)
    assert win.stack.currentWidget() is not win.setup_page
    win.cancel_edit()
