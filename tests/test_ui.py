"""Test dell'interfaccia (nuova grafica): la finestra vera, senza schermo (Qt "offscreen").

Si apre una SD finta (foto, Live, video), si usano pulsanti, tasti e miniature come farebbe
l'utente e si controlla che file, sessione e interfaccia siano giusti."""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROFILE = f"pytest-ui-{os.getpid()}"   # non tocca le impostazioni dell'utente né di altri test in corso
os.environ["PHOTOSWIPE_PROFILE"] = PROFILE

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app as A  # noqa: E402
import exporter  # noqa: E402
import frames  # noqa: E402
from test_core import LIVE, LONG, make_clip  # noqa: E402

PHOTO1 = "DJI_20260730132210_0002_D.JPG"
PHOTO2 = "DJI_20260730132220_0003_D.JPG"
# nomi in export: data e ora di scatto davanti (dal nome DJI: le foto finte non hanno EXIF)
from album_names import nodate  # noqa: E402
DATED1 = f"20260730_132210_{nodate(PHOTO1)}"
DATED2 = f"20260730_132220_{nodate(PHOTO2)}"
SNAP31 = f"Foto/20260730_132301_{nodate(LONG + '_f0031.jpg')}"
CAM_FRAME = 40   # fotogramma della Live scelto dalla "fotocamera" (anteprima .SCR)


@pytest.fixture(scope="module")
def qapp():
    qa = QApplication.instance() or QApplication([])
    qa.setStyleSheet(A.STYLE)
    return qa


@pytest.fixture(scope="module")
def sd_template(tmp_path_factory) -> Path:
    """Ordine dopo la scansione: Live, foto, foto, video, poi altre 4 foto."""
    root = tmp_path_factory.mktemp("sdtpl") / "sd"
    dcim = root / "DCIM" / "DJI_001"
    dcim.mkdir(parents=True)
    make_clip(dcim / f"{LIVE}.MP4", 3.036)
    shutil.copy(dcim / f"{LIVE}.MP4", dcim / f"{LIVE}.LRF")
    make_clip(dcim / f"{LONG}.MP4", 4)
    Image.new("RGB", (1200, 900), "red").save(dcim / PHOTO1, quality=90)
    Image.new("RGB", (900, 1200), "blue").save(dcim / PHOTO2, quality=90)
    for k in range(6, 10):
        Image.new("RGB", (800, 600), (40 * k % 255, 90, 160)).save(
            dcim / f"DJI_202607301324{k:02d}_00{k:02d}_D.JPG", quality=90)
    thm = root / "MISC" / "THM" / "DJI_001"
    thm.mkdir(parents=True)
    info = frames.probe(dcim / f"{LIVE}.MP4")
    frames.frame_rgb(dcim / f"{LIVE}.MP4", info, CAM_FRAME).resize((320, 180)).save(
        thm / f"{LIVE}.SCR", "JPEG", quality=85)
    return root


@pytest.fixture
def sd(sd_template, tmp_path) -> Path:
    root = tmp_path / "sd"
    shutil.copytree(sd_template, root)
    return root


def pump(qa, seconds: float = 0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qa.processEvents()
        time.sleep(0.005)


def wait(qa, cond, seconds: float = 20) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qa.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


@pytest.fixture
def win(qapp):
    QSettings("PhotoSwipe", PROFILE).clear()
    w = A.MainWindow()
    w.show()
    w.activateWindow()
    pump(qapp, 0.1)
    yield w
    for f in list(w.export_futures.values()):
        try:
            f.result(timeout=20)
        except Exception:  # noqa: BLE001
            pass
    w.close()
    pump(qapp, 0.05)
    w.deleteLater()


def open_folder(qa, w, root: Path):
    w.pick_root = root
    w.refresh_setup()
    w.start_from_setup()
    assert wait(qa, lambda: w.session is not None and w.stack.currentWidget() is not w.msg_page), \
        "la cartella non si apre"
    pump(qa, 0.2)


def index_of(w, name: str) -> int:
    return next(i for i, it in enumerate(w.items) if it.main.name == name)


def go(qa, w, name: str):
    w.jump_to(index_of(w, name))
    it = w.current()
    if it.is_clip:
        assert wait(qa, lambda: it.id in w.infos), "analisi del video non finita"
    pump(qa, 0.2)


def press(qa, w, key, mod=Qt.NoModifier):
    w._last_decision = 0   # niente protezione dal doppio tocco nei test
    QTest.keyClick(w, key, mod)
    pump(qa, 0.1)


def click(qa, w, button):
    w._last_decision = 0
    QTest.mouseClick(button, Qt.LeftButton)
    pump(qa, 0.1)


def exports_done(qa, w):
    assert wait(qa, lambda: all(f.done() for f in w.export_futures.values()))
    w.export_q.submit(lambda: None).result(timeout=20)   # anche le rimozioni in coda
    pump(qa, 0.1)


def exported(w) -> list[str]:
    if not w.export_dir.exists():
        return []
    return sorted(p.relative_to(w.export_dir).as_posix() for p in w.export_dir.rglob("*") if p.is_file())


# ------------------------------------------------------------------ schermata iniziale

def test_setup_screen_hides_browsing_controls(qapp, win, sd):
    assert win.stack.currentWidget() is win.setup_page
    for w_ in (win.decision_bar, win.nav_pill, win.zoom_pill, win.fav_pill, win.thumbs_strip):
        assert not w_.isVisible()
    assert not win.btn_start.isEnabled()
    assert not win.btn_pick_dst.isEnabled()
    win.pick_root = sd
    win.refresh_setup()
    assert win.btn_start.isEnabled() and win.btn_pick_dst.isEnabled()
    assert str(sd / "export") in win.dst_label.text()
    assert "su disco" in win.q_local.text()


def test_open_folder_shows_first_item_with_info_and_thumbs(qapp, win, sd):
    open_folder(qapp, win, sd)
    assert [it.kind for it in win.items] == ["live", "photo", "photo", "video"] + ["photo"] * 4
    for w_ in (win.decision_bar, win.nav_pill, win.fav_pill, win.thumbs_strip):
        assert w_.isVisible()
    assert win.heading.text() == f"{LIVE}.MP4"
    assert win.badge.text() == "LIVE"
    assert "1 di 8" in win.title.text()
    assert "luglio 2026" in win.side_details.text()
    assert win.scene_bar.isVisible()
    assert win.thumbs_strip.current == 0
    assert [e[0] for e in win.thumbs_strip.entries] == list(range(8))
    assert wait(qapp, lambda: win.stamp.isVisible())
    assert "30 lug 2026" in win.stamp.text()


def test_photo_shows_image_and_no_scene_bar(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    assert win.stack.currentWidget() is win.image_view
    assert not win.image_view.full.isNull()
    assert not win.scene_bar.isVisible()
    assert win.badge.text() == "FOTO"
    assert not win.btn_yes_video.isEnabled()   # foto senza video: niente "Sì + video"


# ------------------------------------------------------------------ scelte

def test_yes_button_copies_photo_identical_and_advances(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert exported(win) == [f"Foto/{DATED1}"]
    assert (win.export_dir / "Foto" / DATED1).read_bytes() == next(sd.rglob(PHOTO1)).read_bytes()
    assert win.current().main.name == PHOTO2
    assert "1 approvate" in win.counter.text()


def test_keyboard_shortcuts_decide(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    press(qapp, win, Qt.Key_N)
    assert win.session.get(win.items[1].id)["choice"] == "no"
    press(qapp, win, Qt.Key_S)
    assert win.session.get(win.items[2].id)["choice"] == "skip"
    press(qapp, win, Qt.Key_Left)                   # indietro (Su/Giù sono i fotogrammi del video)
    assert win.idx == 2
    press(qapp, win, Qt.Key_Right)                  # avanti
    assert win.idx == 3
    go(qapp, win, PHOTO1)
    press(qapp, win, Qt.Key_Return)                 # Invio = Sì
    assert win.session.get(win.items[1].id)["choice"] == "yes"


def test_trash_moves_original_and_undo_puts_it_back(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO2)
    original = next(sd.rglob(PHOTO2))
    click(qapp, win, win.btn_trash)
    assert not original.exists()
    assert (sd / exporter.TRASH_DIR / original.relative_to(sd)).exists()
    assert exported(win) == []                     # “cancellare” non copia niente
    click(qapp, win, win.btn_undo)
    assert original.exists()
    assert win.session.get(win.items[2].id) is None
    assert win.current().main.name == PHOTO2


def test_going_back_shows_choice_and_new_choice_replaces_it(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_no)
    click(qapp, win, win.btn_back)
    assert win.current().main.name == PHOTO1
    assert win.chosen_tag.isVisible() and "NO" in win.chosen_tag.text()
    assert win.btn_no.property("chosen") == "true"
    assert win.btn_yes.property("chosen") == "false"
    click(qapp, win, win.btn_yes)                  # cambio idea: NO -> SÌ
    exports_done(qapp, win)
    assert win.session.get(win.items[1].id)["choice"] == "yes"
    assert exported(win) == [f"Foto/{DATED1}"]
    assert "Scelta cambiata" in win.status.text()
    click(qapp, win, win.btn_undo)                 # annulla: di nuovo NO, copia tolta
    exports_done(qapp, win)
    assert win.session.get(win.items[1].id)["choice"] == "no"
    assert exported(win) == []


def test_same_choice_again_just_moves_on(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_skip)
    click(qapp, win, win.btn_back)
    click(qapp, win, win.btn_skip)
    assert win.current().main.name == PHOTO2
    assert "Scelta confermata" in win.status.text()
    assert len(win.history) == 1


def test_double_tap_is_ignored(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win._last_decision = 0
    win.decide("no")
    win.decide("no")                               # entro 0,25 s: ignorato
    assert win.current().main.name == PHOTO2
    assert win.session.get(win.items[2].id) is None


# ------------------------------------------------------------------ Live e video

def test_live_yes_exports_the_frame_chosen_on_the_strip(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    assert win.camera_frames[win.current().id] == CAM_FRAME
    assert "della fotocamera" in win.frame_label.text()
    assert win.btn_live.isVisible() and not win.btn_snap.isVisible()
    press(qapp, win, Qt.Key_Down, Qt.ShiftModifier)    # 10 avanti
    assert win.frame == CAM_FRAME + 10
    assert "scelta da te" in win.frame_label.text()
    assert win.btn_reset.isVisible()
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    d = win.session.get(win.items[0].id)
    assert d["choice"] == "yes" and d["frame"] == CAM_FRAME + 10
    # la foto della Live ha l'ora del fotogramma scelto (50 a 30 fps: +1,7 s dall'inizio)
    assert exported(win) == [f"Foto/20260730_132205_{nodate(LIVE + '.jpg')}"]


def test_live_reset_goes_back_to_camera_frame(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    win.step(3)
    press(qapp, win, Qt.Key_R)
    assert win.frame is None
    assert win.live_photo_frame(win.current()) == CAM_FRAME


def test_live_yes_with_video_copies_the_mp4_too(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    assert win.btn_yes_video.isEnabled()
    click(qapp, win, win.btn_yes_video)
    exports_done(qapp, win)
    assert exported(win) == [f"Foto/20260730_132205_{nodate(LIVE + '.jpg')}", f"Video/20260730_132204_{nodate(LIVE + '.MP4')}"]


def test_live_view_toggles_between_photo_and_video(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LIVE}.MP4")
    click(qapp, win, win.btn_live)
    assert win.live_view and win.stack.currentWidget() is win.video_widget
    assert "Torna alla foto" in win.btn_live.text()
    click(qapp, win, win.btn_live)
    assert not win.live_view and win.stack.currentWidget() is win.image_view


def test_video_snapshot_marks_strip_and_yes_keeps_only_photos(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    assert win.btn_snap.isVisible() and not win.btn_live.isVisible()
    assert not win.btn_yes_video.isEnabled()          # serve prima una foto presa
    win.on_strip_picked(30)
    pump(qapp, 0.2)
    click(qapp, win, win.btn_snap)
    exports_done(qapp, win)
    assert exported(win) == [SNAP31]   # fotogramma 30: 1 s dopo l'inizio
    assert win.strip.marks == [30]
    assert "1 foto salvata" in win.snaps_label.text()
    assert win.btn_yes_video.isEnabled()
    click(qapp, win, win.btn_yes)                    # Sì = solo le foto, niente video
    exports_done(qapp, win)
    assert exported(win) == [SNAP31]
    assert win.session.get(win.items[3].id).get("noexport")


def test_video_yes_without_snapshots_copies_the_video(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert exported(win) == [f"Video/20260730_132300_{nodate(LONG + '.MP4')}"]


def test_undo_snapshot_stays_on_video(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    win.on_strip_picked(12)
    pump(qapp, 0.2)
    press(qapp, win, Qt.Key_F)
    exports_done(qapp, win)
    press(qapp, win, Qt.Key_Z)
    exports_done(qapp, win)
    assert exported(win) == []
    assert win.current().main.name == f"{LONG}.MP4"
    assert win.strip.marks == []


# ------------------------------------------------------------------ navigazione e barre

def test_thumbnail_click_jumps_to_item(qapp, win, sd):
    open_folder(qapp, win, sd)
    win.resize(1440, 900)
    pump(qapp, 0.3)
    target = next(r for r, i in win.thumbs_strip._rects if i == 2)
    QTest.mouseClick(win.thumbs_strip, Qt.LeftButton, Qt.NoModifier, target.center().toPoint())
    pump(qapp, 0.2)
    assert win.idx == 2 and win.thumbs_strip.current == 2


def test_thumbnails_get_choice_dots(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_no)
    entry = next(e for e in win.thumbs_strip.entries if e[0] == 1)
    assert entry[2] == "no"
    assert wait(qapp, lambda: any(e[1] is not None for e in win.thumbs_strip.entries))


def test_end_screen_and_review_skipped(qapp, win, sd):
    open_folder(qapp, win, sd)
    win._last_decision = 0
    win.decide("no")
    win._last_decision = 0
    win.decide("skip")                           # PHOTO1
    while win.current() is not None:
        win._last_decision = 0
        win.decide("no")
        pump(qapp, 0.02)
    assert win.stack.currentWidget() is win.msg_page
    assert "Finito" in win.message.text()
    for b in (win.btn_yes, win.btn_no, win.btn_skip, win.btn_trash):
        assert not b.isEnabled()
    assert win.msg_btn2.isVisible() and "saltate" in win.msg_btn2.text()
    click(qapp, win, win.msg_btn2)
    assert win.current().main.name == PHOTO1
    assert win.btn_yes.isEnabled()


def test_photos_only_filter_hides_videos(qapp, win, sd):
    open_folder(qapp, win, sd)
    win.view_filter.setCurrentIndex(1)
    pump(qapp, 0.2)
    assert "di 7" in win.title.text()
    assert all(win.items[e[0]].kind != "video" for e in win.thumbs_strip.entries)
    go(qapp, win, PHOTO2)
    press(qapp, win, Qt.Key_Down)                # salta il video nascosto
    assert win.current().kind == "photo" and win.idx == 4
    win.view_filter.setCurrentIndex(0)


def test_videos_only_filter_hides_photos_and_lives(qapp, win, sd):
    open_folder(qapp, win, sd)
    win.view_filter.setCurrentIndex(2)
    pump(qapp, 0.2)
    assert win.media_filter == "videos"
    assert all(win.items[e[0]].kind == "video" for e in win.thumbs_strip.entries)
    assert win.current().kind == "video" and win.idx == 3   # la Live (idx 0) e le foto sono nascoste
    win.view_filter.setCurrentIndex(0)
    pump(qapp, 0.2)
    assert win.media_filter == "all"


def test_favorite_goes_to_preferite(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_fav)
    assert win.btn_fav.text() == "♥" and win.btn_fav.property("on") == "true"
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert exported(win) == [f"Foto/Preferite/{DATED1}"]


def test_export_names_sort_in_capture_order_whatever_the_approval_order(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO2)                        # prima la foto scattata dopo
    click(qapp, win, win.btn_yes)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_yes)
    exports_done(qapp, win)
    assert sorted(os.listdir(exporter.photo_dir(win.export_dir))) == [DATED1, DATED2]


def test_zoom_slider_and_double_click(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    assert win.zoom_slider.isEnabled()
    win.zoom_slider.setValue(60)
    assert win.image_view.zoomed
    win.image_view.mouseDoubleClickEvent(None)
    assert not win.image_view.zoomed and win.zoom_slider.value() == 0
    win.image_view.zoom_by(1.5)                  # rotella / trackpad muovono il cursore
    assert win.zoom_slider.value() > 0
    press(qapp, win, Qt.Key_N)                   # elemento nuovo: di nuovo intero
    assert not win.image_view.zoomed and win.zoom_slider.value() == 0


def test_zoom_slider_disabled_on_video(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    assert win.stack.currentWidget() is win.video_widget
    assert not win.zoom_slider.isEnabled()


def test_settings_popup_opens_and_closes(qapp, win, sd):
    open_folder(qapp, win, sd)
    click(qapp, win, win.btn_settings)
    assert win.settings_pop.isVisible()
    assert win.btn_export.text() == "Export: export"
    win.settings_pop.hide()
    win.fmt.setCurrentIndex(1)
    assert QSettings("PhotoSwipe", PROFILE).value("fmt") == "png16"
    win.fmt.setCurrentIndex(0)


def test_open_folder_from_settings_returns_to_setup(qapp, win, sd):
    """Un risultato in background (fotogramma 4K della Live) non deve riportare alla foto."""
    open_folder(qapp, win, sd)
    win.btn_open.click()
    pump(qapp, 3)                                # lascia arrivare i lavori in background
    assert win.stack.currentWidget() is win.setup_page
    assert not win.decision_bar.isVisible() and not win.scene_bar.isVisible()
    assert win.src_label.text() == str(sd.resolve())


def test_toast_is_placed_inside_the_photo_area(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.flash("prova")
    assert win.status.isVisible()
    g = win.status.geometry()
    assert win.stack.rect().contains(g)
    win.resize(1000, 700)
    pump(qapp, 0.2)
    assert win.stack.rect().contains(win.status.geometry())   # si riposiziona


def test_resume_restores_choices(qapp, sd):
    QSettings("PhotoSwipe", PROFILE).clear()
    w1 = A.MainWindow()
    w1.show()
    open_folder(qapp, w1, sd)
    go(qapp, w1, f"{LIVE}.MP4")
    for _ in range(2):
        w1._last_decision = 0
        w1.decide("no")
    w1.close()
    w2 = A.MainWindow()
    w2.show()
    assert "sd" in w2.btn_resume.text() and w2.btn_resume.isVisible()
    w2.btn_resume.click()
    assert wait(qapp, lambda: w2.session is not None and w2.current() is not None)
    pump(qapp, 0.2)
    assert w2.idx == 2
    assert "2 già decise" in w2.status.text()
    w2.close()


# ------------------------------------------------------------------ problemi della nuova grafica (corretti)

def test_file_name_readable_on_narrow_window_with_choice_tag(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    click(qapp, win, win.btn_no)
    click(qapp, win, win.btn_back)             # compare l'etichetta "GIÀ SCELTO"
    win.resize(1024, 768)
    pump(qapp, 0.3)
    assert win.chosen_tag.isVisible()
    assert win.heading.width() >= 80


def test_toast_hides_by_itself(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.flash("prova")
    assert win.status.isVisible()
    pump(qapp, 4.5)                             # conferme: ~3,5 s
    assert not win.status.isVisible()
    win.flash("di nuovo")                       # e ricompare al messaggio successivo
    assert win.status.isVisible() and win.status.text() == "di nuovo"


def test_error_toast_stays_longer_and_export_warning_stays(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    win.status.setText("errore")
    pump(qapp, 4.5)
    assert win.status.isVisible()               # errori: 8 s
    win.status.setText("export non raggiungibile", ms=0)
    pump(qapp, 9)
    assert win.status.isVisible()               # ms=0: resta


def test_info_panel_button_toggles_and_is_remembered(qapp, win, sd):
    open_folder(qapp, win, sd)
    assert win.btn_info.isVisible() and win.side.isVisible()
    assert win.btn_info.property("on") == "true"
    click(qapp, win, win.btn_info)
    assert not win.side.isVisible() and win.btn_info.property("on") == "false"
    assert QSettings("PhotoSwipe", PROFILE).value("side") == "0"
    w2 = A.MainWindow()                         # riaperta: il pannello resta chiuso
    try:
        assert w2.side_wanted is False
    finally:
        w2.close()
    press(qapp, win, Qt.Key_I)                  # tasto I: di nuovo aperto
    assert win.side.isVisible() and win.btn_info.property("on") == "true"


def test_end_screen_with_undecided_items_left_offers_to_go_back(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO2)                         # la Live e la prima foto restano da decidere
    while win.current() is not None:
        win._last_decision = 0
        win.decide("no")
        pump(qapp, 0.02)
    assert "Finito" not in win.message.text()
    assert "mancano 2 elementi" in win.message.text()
    assert win.msg_btn2.isVisible() and "primo da decidere" in win.msg_btn2.text()
    click(qapp, win, win.msg_btn2)
    assert win.idx == 0 and win.current().kind == "live"
    assert win.btn_yes.isEnabled()
