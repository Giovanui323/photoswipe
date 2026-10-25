"""Interfaccia: casi che facevano perdere modifiche o lasciavano copie sbagliate nell'album
(frecce sulla foto, riordino automatico dell'export con ♥ e annulla, riapertura di un'altra scheda, tasti)."""
from __future__ import annotations

import json
import os
import shutil

from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QMessageBox

import exporter
import frames
from test_core import make_clip
from test_ui import (DATED1, DATED2, LIVE, PHOTO1, PHOTO2, click, exported, exports_done,  # noqa: F401
                     go, index_of, open_folder, pump, qapp, sd, sd_template, wait, win)


def legacy_export(sd, copies: dict[str, str], favorites=()) -> dict[str, str]:
    """Export e salvataggio come li lasciavano le versioni di prima: copie sciolte in export o in
    export/Preferite, a volte col numero 0001_ davanti. copies: foto -> percorso in export.
    Ritorna foto -> percorso della copia."""
    export = sd / "export"
    decisions, out = {}, {}
    for name, rel in copies.items():
        src = next(sd.rglob(name))
        dst = export / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
        decisions[src.relative_to(sd).as_posix()] = {"choice": "yes", "files": [str(dst)],
                                                     "frame": None, "with_video": False}
        out[name] = str(dst)
    favs = [next(sd.rglob(n)).relative_to(sd).as_posix() for n in favorites]
    (sd / exporter.SESSION_FILE).write_text(json.dumps({
        "app": "PhotoSwipe", "root": str(sd.resolve()), "export": str(export),
        "created": "2026-07-30T13:00:00", "updated": "2026-07-30T13:00:00", "closed": "2026-07-30T14:00:00",
        "total": 8, "decided": len(decisions), "completed": False,
        "decisions": decisions, "favorites": favs}), "utf-8")
    return out


def open_and_tidy(qa, w, sd, monkeypatch, expect) -> list:
    """Apre la cartella e aspetta il riordino automatico dell'export (niente finestre di dialogo)."""
    dialogs: list = []
    for kind in ("question", "warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda *a, _k=kind, **k: dialogs.append((_k, a))))
    open_folder(qa, w, sd)
    assert wait(qa, lambda: not w._rename_busy and (w.export_dir / expect).exists()), "il riordino non finisce"
    exports_done(qa, w)
    return dialogs


def album(w) -> list[str]:
    return [f for f in exported(w) if not f.startswith(".") and "/." not in f]


def session_files(w, name) -> list[str]:
    return w.session.get(w.items[index_of(w, name)].id)["files"]


def test_photo_arrows_wait_for_pending_edits(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.auto_enhance()
    assert win.edit_pending()
    before = win.idx
    click(qapp, win, win.photo_next)
    assert win.idx == before and win.edit_pending(), "la freccia ha buttato via le modifiche"
    win.cancel_edit()
    click(qapp, win, win.photo_next)
    assert win.idx != before


def test_frame_keys_repeat_and_item_keys_do_not(qapp, win):
    reps = {QShortcut.key(s).toString(): s.autoRepeat() for s in win.findChildren(QShortcut)}
    assert all(reps[k] for k in ("Up", "Down", "Shift+Up", "Shift+Down"))
    assert not reps["Left"] and not reps["Right"]


def test_next_to_decide_button_only_away_from_it(qapp, win, sd):
    open_folder(qapp, win, sd)
    assert not win.btn_locate.isVisible()          # già sulla prossima da decidere
    go(qapp, win, PHOTO2)
    assert win.btn_locate.isVisible()
    win.locate_thumb()
    assert win.idx == win.next_index(-1) and not win.btn_locate.isVisible()


def test_second_card_with_same_names_is_analyzed_again(qapp, win, sd, tmp_path):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    item_id = win.current().id
    sd2 = tmp_path / "sd2"
    shutil.copytree(sd, sd2)
    vid = sd2 / item_id
    make_clip(vid, 6.0)
    shutil.copy(vid, vid.with_suffix(".LRF"))
    win.go_home()
    open_folder(qapp, win, sd2)
    go(qapp, win, f"{LIVE}.MP4")
    assert win.infos[item_id].frames == frames.probe(vid).frames


def test_old_export_is_tidied_on_open_and_favorite_and_undo_follow_it(qapp, win, sd, monkeypatch):
    legacy_export(sd, {PHOTO1: f"Preferite/0001_20260730_132210_{PHOTO1}", PHOTO2: PHOTO2},
                  favorites=[PHOTO1])
    dialogs = open_and_tidy(qapp, win, sd, monkeypatch, f"Foto/Preferite/{DATED1}")
    assert not dialogs
    assert album(win) == [f"Foto/{DATED2}", f"Foto/Preferite/{DATED1}"]
    assert session_files(win, PHOTO1) == [str(win.export_dir / "Foto" / "Preferite" / DATED1)]
    assert session_files(win, PHOTO2) == [str(win.export_dir / "Foto" / DATED2)]
    assert "Export in ordine" in win.status.text()

    go(qapp, win, PHOTO1)
    win.toggle_favorite()                       # ♥ tolto: la copia rinominata torna in Foto
    exports_done(qapp, win)
    assert album(win) == [f"Foto/{DATED1}", f"Foto/{DATED2}"]
    assert session_files(win, PHOTO1) == [str(win.export_dir / "Foto" / DATED1)]
    win.toggle_favorite()                       # ♥ di nuovo: in Foto/Preferite
    exports_done(qapp, win)
    assert album(win) == [f"Foto/{DATED2}", f"Foto/Preferite/{DATED1}"]
    assert session_files(win, PHOTO1) == [str(win.export_dir / "Foto" / "Preferite" / DATED1)]

    click(qapp, win, win.btn_no)                # cambio idea: la copia (al posto nuovo) si toglie
    exports_done(qapp, win)
    assert album(win) == [f"Foto/{DATED2}"]
    win.undo()                                  # di nuovo SÌ: ricopiata, preferita, col nome con la data
    exports_done(qapp, win)
    assert album(win) == [f"Foto/{DATED2}", f"Foto/Preferite/{DATED1}"]
    go(qapp, win, PHOTO2)
    click(qapp, win, win.btn_no)
    exports_done(qapp, win)
    assert album(win) == [f"Foto/Preferite/{DATED1}"]


def test_tidy_partial_failure_keeps_session_in_step(qapp, win, sd, monkeypatch):
    old = legacy_export(sd, {PHOTO1: PHOTO1, PHOTO2: f"Preferite/{PHOTO2}"}, favorites=[PHOTO2])
    fav = sd / "export" / "Preferite"
    os.chmod(fav, 0o555)                        # la copia lì dentro non si può spostare
    try:
        dialogs = open_and_tidy(qapp, win, sd, monkeypatch, f"Foto/{DATED1}")
        assert album(win) == [f"Foto/{DATED1}", f"Preferite/{PHOTO2}"]
        assert session_files(win, PHOTO1) == [str(win.export_dir / "Foto" / DATED1)]
        assert session_files(win, PHOTO2) == [old[PHOTO2]]
        for it in win.items:
            d = win.session.get(it.id)
            if d and d["choice"] == "yes":
                assert all(os.path.exists(f) for f in d["files"]), d["files"]
        assert not dialogs, "avviso nella barra di stato, non una finestra"
        assert win.status.isVisible() and "1 copie in export non si sono potute rinominare" in win.status.text()
    finally:
        os.chmod(fav, 0o755)


def test_idle_crop_closes_when_moving_to_another_photo(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.on_side_tab("ritaglia")
    pump(qapp, 0.2)
    assert win.image_view.crop_mode and not win.edit_pending()
    go(qapp, win, PHOTO2)
    assert not win.image_view.crop_mode and win.crop_draft is None


def test_discard_edits_on_approved_photo_shows_edit_badge(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.auto_enhance()
    win.confirm_edit()
    win.decide("yes")
    exports_done(qapp, win)
    go(qapp, win, PHOTO1)
    win.discard_edits()
    assert win.edit_badge.isVisible() and "Modificata dopo il Sì" in win.edit_badge.text()
    assert win.side_foot.isVisible()


def test_snap_open_fix_save_and_close_stays_paused(qapp, win, sd):
    from test_core import LONG
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    assert wait(qapp, lambda: win.current().id in win.infos)
    win.set_frame(2, manual=True)
    assert wait(qapp, lambda: win.still_owner == win.current().id)
    win.take_photo()
    exports_done(qapp, win)
    key = f"{win.current().id}#f2"
    win.open_snap(key)
    assert win.snap_bar.isVisible() and win.side_info.isVisible()
    win.fix_snap()
    assert wait(qapp, lambda: win.still_owner == win.current().id)
    win.on_side_tab("regola")
    assert win.side_tab == "regola" and win.snap_save.isVisible()
    win.on_regola_changed({"exposure": 0.25})
    assert win.edit_pending()
    win.save_snap_fix()
    exports_done(qapp, win)
    assert not win.snap_bar.isVisible() and win.snap_key is None
    assert win.scene_mode and not win.side_info.isVisible()
    assert win.session.get(key)["edit"].get("exposure") == 0.25


def test_show_chosen_highlights_yes_video_and_flash_resets_on_error(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    assert wait(qapp, lambda: win.current().id in win.infos)
    win.decide("yes", with_video=True)
    exports_done(qapp, win)
    go(qapp, win, f"{LIVE}.MP4")
    assert win.btn_yes_video.property("chosen") == "true"
    assert win.btn_yes.property("chosen") == "false"
    win.flash("Tutto bene")
    assert "color:" in win.status.styleSheet()
    win.status.setText("Errore grave")
    assert win.status.styleSheet() == ""
