"""Interfaccia e video: download iCloud scorrendo veloce, anticipo che fallisce, uscita con
processi figli, calcoli di Regola vecchi, ffmpeg con righe strane, fuso orario dei video
iPhone, salvataggio che fallisce dopo "cancellare", frecce della striscia, stampa con le
modifiche e occhi rossi in Ritaglia."""
from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from PySide6.QtGui import QImage

import app as A
import cloud
import edits as E
import exporter
import frames
import printprep
from test_core import FF, LONG, make_clip
from test_ui import (LIVE, PHOTO1, PHOTO2, click, exports_done, go, index_of, open_folder,  # noqa: F401
                     pump, qapp, sd, sd_template, wait, win)

EXTRA = [f"DJI_202607301324{k:02d}_00{k:02d}_D.JPG" for k in range(6, 10)]


# ------------------------------------------------------------------ 1. iCloud: scorrendo veloce
def remote_photos(monkeypatch, w, names, fast):
    """Le foto names sono "su iCloud": il download di fast è immediato, gli altri restano appesi
    finché non si apre il cancello (come un download lento lasciato indietro)."""
    paths = {w.items[index_of(w, n)].image for n in names}
    done: set[Path] = set()
    gate = threading.Event()
    calls: list[str] = []
    monkeypatch.setattr(cloud, "is_local", lambda p: Path(p) not in paths or Path(p) in done)

    def download(p, timeout=900):
        p = Path(p)
        calls.append(p.name)
        if p.name in fast:
            done.add(p)
            return True
        gate.wait(30)
        return False
    monkeypatch.setattr(cloud, "download", download)
    return gate, calls


def test_item_you_stop_on_does_not_wait_behind_skipped_downloads(qapp, win, sd, monkeypatch):
    open_folder(qapp, win, sd)
    target = EXTRA[-1]
    slow = [PHOTO1, PHOTO2, *EXTRA[:-1]]   # 5 attese appese: più dei 4 posti di "waiters"
    gate, _ = remote_photos(monkeypatch, win, [*slow, target], fast={target})
    monkeypatch.setattr(win, "prefetch", lambda: None)   # qui conta solo l'elemento corrente
    try:
        for name in slow:
            win.jump_to(index_of(win, name))
            pump(qapp, 0.25)   # abbastanza per far partire i download degli elementi passati
        tid = win.items[index_of(win, target)].id
        win.jump_to(index_of(win, target))
        assert wait(qapp, lambda: tid in win.ready and win.stack.currentWidget() is win.image_view, 5), \
            "l'elemento corrente aspetta dietro ai download degli elementi saltati"
        # le attese degli elementi lasciati non contano più
        assert not [k for k in win.pending if k[0] == "ready-now" and k[1] != tid]
    finally:
        gate.set()


def test_skipped_quickly_items_do_not_start_downloads(qapp, win, sd, monkeypatch):
    open_folder(qapp, win, sd)
    gate, calls = remote_photos(monkeypatch, win, [PHOTO1, PHOTO2, *EXTRA], fast=set())
    monkeypatch.setattr(win, "prefetch", lambda: None)
    # ritardo più lungo dei 150 ms veri: con la CPU carica (altre suite in parallelo) un salto
    # può durarne di più, e la foto solo sfiorata partiva comunque. Il comportamento è lo stesso.
    monkeypatch.setattr(win, "READY_DELAY_S", 1.0)
    try:
        for name in [PHOTO1, PHOTO2, *EXTRA[:2]]:
            win.jump_to(index_of(win, name))
            qapp.processEvents()   # scorrendo velocissimo
        assert wait(qapp, lambda: EXTRA[1] in calls, 10), calls
        pump(qapp, 0.3)
        # l'ultimo, su cui ti sei fermato, sì; quelli solo sfiorati (quasi tutti) no
        assert EXTRA[1] in calls and len(calls) <= 2, calls
    finally:
        gate.set()


def test_failed_prefetch_does_not_clear_the_current_wait(qapp, win, sd, monkeypatch):
    open_folder(qapp, win, sd)
    item = win.items[index_of(win, PHOTO1)]
    paths = {item.image}
    gate = threading.Event()
    monkeypatch.setattr(cloud, "is_local", lambda p: Path(p) not in paths)
    monkeypatch.setattr(win, "prefetch", lambda: None)

    def download(p, timeout=900):
        if threading.current_thread().name.startswith("icloud-"):   # attesa dell'elemento corrente
            gate.wait(30)
            paths.discard(Path(p))
            return True
        return False                                                  # anticipo: non riuscito
    monkeypatch.setattr(cloud, "download", download)
    try:
        win.jump_to(index_of(win, PHOTO1))
        assert wait(qapp, lambda: ("ready-now", item.id) in win.pending, 2)
        win.request_ready(item, now=False)
        assert wait(qapp, lambda: ("ready-pre", item.id) not in win.pending, 5)
        pump(qapp, 0.2)
        assert ("ready-now", item.id) in win.pending, "l'anticipo fallito ha tolto l'attesa corrente"
        assert "non riuscito" not in win.message.text()
        gate.set()
        assert wait(qapp, lambda: win.stack.currentWidget() is win.image_view, 5)
    finally:
        gate.set()


def test_prefetch_outside_the_window_is_dropped(qapp, win, sd, monkeypatch):
    open_folder(qapp, win, sd)
    gate, _ = remote_photos(monkeypatch, win, [PHOTO1, PHOTO2, *EXTRA], fast=set())
    monkeypatch.setattr(A, "PREFETCH", 3)
    try:
        win.jump_to(0)   # la Live: anticipa foto 1, foto 2 (il video è già sul disco)
        win.prefetch()
        pump(qapp, 0.1)
        ids = [win.items[index_of(win, n)].id for n in (PHOTO1, PHOTO2)]
        jobs = [win._ready_jobs[("ready-pre", i)] for i in ids]
        win.jump_to(index_of(win, EXTRA[0]))   # più avanti: foto 1 e 2 non servono più
        pump(qapp, 0.1)
        for i, (fut, abandon, _) in zip(ids, jobs):
            assert ("ready-pre", i) not in win.pending
            assert abandon.is_set() and (fut.cancelled() or fut.running() or fut.done())
            assert ("ready-pre", i) not in win._ready_jobs
    finally:
        gate.set()


# ------------------------------------------------------------------ 3. uscita: processi figli
def test_kill_running_stops_ffmpeg(tmp_path):
    res = {}

    def long_job():
        t0 = time.monotonic()
        try:
            frames._run(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=600",
                         "-f", "null", "-"], timeout=300)
        except Exception as e:  # noqa: BLE001
            res["err"] = e
        res["secs"] = time.monotonic() - t0
    th = threading.Thread(target=long_job)
    th.start()
    end = time.monotonic() + 10
    while not frames._procs and time.monotonic() < end:
        time.sleep(0.02)
    assert frames.kill_running() == 1
    th.join(10)
    assert not th.is_alive() and res["secs"] < 10
    assert not frames._procs


def test_close_stops_child_processes_and_all_pools(qapp, win, monkeypatch):
    called = []
    monkeypatch.setattr(frames, "kill_running", lambda: called.append("ffmpeg") or 0)
    monkeypatch.setattr(printprep, "kill_running", lambda: called.append("print") or 0, raising=False)
    win.close()
    assert called == ["ffmpeg", "print"]
    with pytest.raises(RuntimeError):
        win.edit_pool.submit(lambda: None)


def test_close_works_without_printprep_kill_running(qapp, win, monkeypatch):
    monkeypatch.delattr(printprep, "kill_running", raising=False)
    win.close()   # niente errori


# ------------------------------------------------------------------ 4. calcoli di Regola vecchi
def _red():
    img = QImage(64, 48, QImage.Format_RGB888)
    img.fill(0xFF0000)
    return Image.new("RGB", (64, 48), "red"), img


def test_old_or_other_frame_renders_do_not_paint(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    pil, _ = _red()
    shown = win.image_view.full
    owner = win.edit_base_owner
    ekey = win.shown_edit_key()
    win.invalidate_edit_renders()            # a schermo è cambiato qualcosa
    stale = win.edit_gen - 1
    win._edit_busy = True
    win.on_edit_rendered((owner, stale, False, ekey), pil)
    assert win.image_view.full is shown, "un calcolo di prima ha coperto la foto"
    win.on_edit_rendered((owner, win.edit_gen, False, ekey + "#f9"), pil)
    assert win.image_view.full is shown, "le modifiche di un altro fotogramma sono finite qui"
    win.on_edit_rendered((owner, win.edit_gen, False, ekey), pil)
    assert win.image_view.full is not shown   # quello giusto si vede


def test_video_frame_render_for_another_frame_is_dropped(qapp, win, sd):
    open_folder(qapp, win, sd)
    go(qapp, win, f"{LONG}.MP4")
    item = win.current()
    win.toggle_scene()
    assert wait(qapp, lambda: win.still_owner == item.id and win.edit_base_owner == item.id, 20)
    pump(qapp, 0.3)
    shown = win.image_view.full
    other = f"{item.id}#f{win.shown_frame + 7}"
    win._edit_busy = True
    win.on_edit_rendered((item.id, win.edit_gen, False, other), _red()[0])
    assert win.image_view.full is shown


# ------------------------------------------------------------------ 5. frames: probe e sharpest_near
def _fake_run(monkeypatch, stderr: str):
    monkeypatch.setattr(frames, "_run", lambda *a, **k: subprocess.CompletedProcess([], 1, b"", stderr.encode()))


def test_probe_unexpected_stream_line_is_a_clear_error(monkeypatch, tmp_path):
    _fake_run(monkeypatch, "Input #0\n  Duration: 00:00:02.00\n  Stream #0:0: Video: none\n")
    with pytest.raises(RuntimeError):
        frames.probe(tmp_path / "x.mp4")


def test_probe_skips_cover_art_and_odd_fps(monkeypatch, tmp_path):
    _fake_run(monkeypatch, "Input #0\n  Duration: 00:00:02.00, start: 0\n"
              "  Stream #0:0: Video: mjpeg (Baseline), yuvj420p(pc), 320x240, 90k tbr, 90k tbn (attached pic)\n"
              "  Stream #0:1[0x1](und): Video: hevc (Main 10) (hvc1 / 0x31637668), yuv420p10le(tv, bt2020nc/bt2020/arib-std-b67), 3840x2160, . fps, 30 tbr\n")
    info = frames.probe(tmp_path / "x.mp4")
    assert (info.width, info.height) == (3840, 2160)
    assert info.fps == 30 and info.bits == 10 and info.transfer == "arib-std-b67"


def test_sharpest_near_past_the_real_end_returns_a_real_frame(tmp_path):
    v = tmp_path / "c.mp4"
    make_clip(v, 1.0)
    info = frames.probe(v)
    real = info.frames
    info.frames += 40              # stima dalla durata più lunga del vero
    n = info.frames - 1
    got = frames.sharpest_near(v, info, n)
    assert 0 <= got < real, (got, real)


def test_analyze_probes_the_original_once(monkeypatch, sd):
    from scanner import Item, scan
    item = next(i for i in scan(sd) if i.kind == "live")
    calls = []
    real = frames.probe
    monkeypatch.setattr(frames, "probe", lambda p: calls.append(Path(p)) or real(p))
    lrf = item.video.with_suffix(".LRF")
    monkeypatch.setattr(Item, "preview_video", property(lambda self: lrf))
    info, _ = A.MainWindow.analyze(item)
    assert calls.count(item.video) == 1 and calls.count(lrf) == 1
    assert info.original_dims == (640, 360)


# ------------------------------------------------------------------ 6. fuso orario dei video iPhone
def test_capture_times_uses_the_iphone_timezone_in_the_video(tmp_path):
    v = tmp_path / "IMG_0001.MOV"
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "use_metadata_tags",
                    "-metadata", "com.apple.quicktime.creationdate=2026-01-15T10:00:00-0500",
                    "-metadata", "creation_time=2026-01-15T15:00:00Z", str(v)], check=True)
    info = frames.probe(v)
    assert info.created_local is not None
    mac_time = info.created_utc.astimezone().replace(tzinfo=None)   # come scanner.mp4_created
    when, off = frames.capture_times(mac_time, info, None)
    assert when == datetime(2026, 1, 15, 10, 0, 0)
    assert off == timedelta(hours=-5)
    assert frames._fmt_offset(off) == "-05:00"


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="serve time.tzset")
def test_capture_times_uses_the_offset_of_that_day_not_today(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Rome")
    time.tzset()
    try:
        winter = datetime(2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
        summer = datetime(2026, 7, 15, 15, 0, 0, tzinfo=timezone.utc)
        for utc, hours in ((winter, 1), (summer, 2)):
            info = frames.VideoInfo(320, 240, frames.Fraction(30), 1.0, 30, created_utc=utc)
            local = utc.astimezone().replace(tzinfo=None)
            when, off = frames.capture_times(local, info, None)
            assert when == local and off == timedelta(hours=hours)
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_capture_times_keeps_dji_camera_clock_offset():
    utc = datetime(2026, 7, 30, 11, 22, 4, tzinfo=timezone.utc)
    info = frames.VideoInfo(320, 240, frames.Fraction(30), 1.0, 30, created_utc=utc)
    when, off = frames.capture_times(datetime(2026, 7, 30, 20, 22, 4), info, None)   # Tokyo
    assert off == timedelta(hours=9) and when == datetime(2026, 7, 30, 20, 22, 4)
    when, off = frames.capture_times(datetime(2026, 7, 30, 20, 22, 4), info, -4)
    assert off == timedelta(hours=-4) and when == datetime(2026, 7, 30, 7, 22, 4)


# ------------------------------------------------------------------ 7. salvataggio non riuscito
def _broken_save(monkeypatch):
    def save(self, touch=True):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(exporter.Session, "save", save)


def test_trash_with_failed_save_puts_the_files_back(qapp, win, sd, monkeypatch):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    item = win.current()
    idx = win.idx
    _broken_save(monkeypatch)
    win._last_decision = 0
    win.decide("trash")
    pump(qapp, 0.1)
    assert item.image.exists(), "l'originale è rimasto in “cancellare” senza che il salvataggio lo sappia"
    assert not list((sd / exporter.TRASH_DIR).rglob("*.JPG")) if (sd / exporter.TRASH_DIR).exists() else True
    assert win.session.get(item.id) is None
    assert not win.history
    assert win.idx == idx
    assert "No space" in win.status.text()
    monkeypatch.undo()
    win._last_decision = 0
    win.decide("trash")            # col disco a posto si può rifare
    assert win.session.get(item.id)["choice"] == "trash" and not item.image.exists()


def test_yes_with_failed_save_exports_nothing_and_stays(qapp, win, sd, monkeypatch):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    item = win.current()
    idx = win.idx
    _broken_save(monkeypatch)
    win._last_decision = 0
    win.decide("yes")
    pump(qapp, 0.1)
    assert win.session.get(item.id) is None and not win.history and win.idx == idx
    assert item.id not in win.export_futures
    assert "No space" in win.status.text()


# ------------------------------------------------------------------ 8. frecce della striscia
def test_strip_arrows_only_after_resume_from_home(qapp, win, sd):
    open_folder(qapp, win, sd)
    assert not win.btn_thumb_prev.isVisible() and not win.btn_thumb_next.isVisible()
    go(qapp, win, PHOTO2)
    win.go_home()
    open_folder(qapp, win, sd)
    assert win.came_from_home
    assert win.btn_thumb_prev.isVisible() and win.btn_thumb_next.isVisible()
    win.locate_thumb()
    pump(qapp, 0.1)
    assert not win.btn_thumb_prev.isVisible() and not win.btn_thumb_next.isVisible()


# ------------------------------------------------------------------ 9. stampa con le modifiche
def _wait_print(qa, w):
    assert wait(qa, lambda: w.print_job is None, 20)


def test_print_copy_gets_the_confirmed_edit(qapp, win, sd, monkeypatch):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    item = win.current()
    win.session.set_edit(item.id, {"exposure": 0.4})
    got = {}

    def improve(src, dst, progress=None, edit=None):
        got["edit"] = edit
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (30, 20), "green").save(dst)
        return "ok"
    monkeypatch.setattr(printprep, "improve", improve)
    win.print_yes()
    _wait_print(qapp, win)
    assert got["edit"] == E.clean({"exposure": 0.4})


def test_print_copy_with_old_printprep_signature(qapp, win, sd, monkeypatch):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    item = win.current()
    win.session.set_edit(item.id, {"exposure": 0.4})
    got = {}

    def improve(src, dst, progress=None):
        got["args"] = (src, dst)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (30, 20), "green").save(dst)
        return "ok"
    monkeypatch.setattr(printprep, "improve", improve)
    win.print_yes()
    _wait_print(qapp, win)
    assert got["args"][0] == item.image


def test_print_compare_off_shows_the_edited_photo(qapp, win, sd, monkeypatch):
    open_folder(qapp, win, sd)
    go(qapp, win, PHOTO1)
    item = win.current()
    win.session.set_edit(item.id, {"exposure": -1.0})
    copy = win.print_copy(item)
    copy.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (30, 20), "green").save(copy)
    win.update_print_box()
    win.btn_print_cmp.setChecked(True)
    assert win.image_view.full.size().width() == 30
    win.request_full_edit()   # un calcolo della foto intera non copre la copia
    pump(qapp, 0.6)
    assert win.image_view.full.size().width() == 30
    win.btn_print_cmp.setChecked(False)
    pump(qapp, 0.3)
    c = win.image_view.full.pixelColor(10, 10)
    assert c.red() < 200, "tolto il confronto si vede l'originale invece della foto modificata"


# ------------------------------------------------------------------ 10. occhi rossi in Ritaglia
def test_redeye_in_crop_mode_stays_on_the_eye():
    img = Image.new("RGB", (400, 400), (120, 120, 120))
    ImageDraw.Draw(img).ellipse((294, 294, 306, 306), fill=(230, 20, 20))   # occhio in (300, 300)
    e = {"crop": [0.5, 0.5, 0.5, 0.5]}
    e["redeye"] = [[0.5, 0.5, 0.04] + E.redeye_frame(e)]   # segnato nel ritaglio: il suo centro
    final = E.render(img, e)
    assert final.getpixel((100, 100))[0] < 150             # nella foto finita è corretto
    preview = A.render_edit_job(img, e, crop_mode=True)    # Ritaglia: foto intera
    assert preview.size == (400, 400)
    r, g, b = preview.getpixel((300, 300))
    assert r < 150, "in Ritaglia la correzione è finita fuori dall'occhio"
    assert preview.getpixel((200, 200)) == (120, 120, 120)
