"""Clicks every button of the application and checks what it does.

All dialogs, the browser, the printer and the network are replaced by fakes, so
nothing leaves the test.  Exceptions raised inside Qt slots are collected and
fail the test.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from g2g import i18n, updater
from g2g.core import graphtec, output
from g2g.core.toolpath import CutParams

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class Fakes:
    """Recorded side effects and canned dialog answers."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.open_file = str(EXAMPLES / "test_tiny.gbr")
        self.save_file = str(tmp_path / "out.graphtec")
        self.text = "My film"
        self.answer = QMessageBox.StandardButton.Yes
        self.messages: list[tuple[str, str]] = []
        self.urls: list[str] = []
        self.sent: list[tuple[str, str, bytes]] = []
        self.release: updater.Release | None = None
        self.errors: list[str] = []
        self.menus: list[list[str]] = []


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    f = Fakes(tmp_path)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (f.open_file, "")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (f.save_file, "")))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (f.text, True)))

    def message(kind):
        def show(parent, title, text, *a, **k):
            f.messages.append((kind, text))
            return f.answer

        return staticmethod(show)

    for kind in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, kind, message(kind))
    from g2g.ui import job_page

    def menu_exec(menu, *a):  # a popup menu: remember its entries, choose nothing
        f.menus.append([a.text() for a in menu.actions()])

    monkeypatch.setattr(job_page.PopupMenu, "exec", menu_exec)

    def box_exec(box):  # the "start cutting?" confirmation: answer with its first / last button
        f.messages.append(("confirm", box.text()))
        buttons = box.buttons()
        (buttons[0] if f.answer == QMessageBox.StandardButton.Yes else buttons[-1]).click()
        return 0

    monkeypatch.setattr(job_page.ConfirmBox, "exec", box_exec)

    from PySide6.QtGui import QDesktopServices

    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: f.urls.append(url.toString()) or True))
    monkeypatch.setattr(output, "list_printers", lambda: ["Office Laser", "Silhouette CAMEO"])
    monkeypatch.setattr(output, "send_to_printer", lambda name, data, title="": f.sent.append(("printer", name, data)))
    monkeypatch.setattr(output, "send_to_path", lambda path, data: f.sent.append(("path", path, data)))
    monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: f.release)
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: f.errors.append(f"{t.__name__}: {v}"))

    from g2g.ui import theme
    from g2g.ui.context import Context
    from g2g.ui.main_window import MainWindow
    from g2g.ui.widgets import LengthSpin

    qapp = QApplication.instance() or QApplication([])
    i18n.set_language("en")
    ctx = Context()
    ctx.settings.confirm_send = False
    LengthSpin.set_unit("mm")
    theme.apply_theme(qapp, "dark")
    win = MainWindow(ctx)
    win.resize(1300, 850)
    win.show()
    qapp.processEvents()
    yield win, ctx, f, qapp
    win.close()
    qapp.processEvents()
    assert f.errors == []


def button(parent, name: str) -> QAbstractButton:
    """Find a button by its (stripped) text or its tooltip."""
    hits = [b for b in parent.findChildren(QAbstractButton) if b.text().strip() == name or b.toolTip() == name]
    assert len(hits) == 1, f"{name!r}: {len(hits)} buttons found"
    return hits[0]


def click(parent, name: str, qapp) -> None:
    b = button(parent, name)
    assert b.isEnabled(), f"{name!r} is disabled"
    b.click()
    qapp.processEvents()


def wait_for(condition, qapp, timeout=5.0) -> None:
    end = time.time() + timeout
    while not condition() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert condition()


# ------------------------------------------------------------------ stencil page


def test_open_export_send(app_env):
    win, ctx, f, qapp = app_env
    page = win.job_page
    assert not button(page, "Export").isEnabled() and not button(page, "Send to cutter").isEnabled()

    click(page, "Open", qapp)
    assert page.file_label.text() == "test_tiny.gbr" and len(page.job.strokes) == 9
    assert ctx.settings.recent_files == [f.open_file]
    click(page, "Recent files", qapp)
    assert f.menus == [["test_tiny.gbr"]]

    click(page, "Export", qapp)
    assert Path(f.save_file).read_bytes() == graphtec.encode(page.job)

    # no cutter configured yet: explain, send nothing
    ctx.settings.printer = ""
    click(page, "Send to cutter", qapp)
    assert f.sent == [] and f.messages[-1][0] == "information"

    ctx.settings.printer = "Silhouette CAMEO"
    click(page, "Send to cutter", qapp)
    assert f.sent == [("printer", "Silhouette CAMEO", graphtec.encode(page.job))]

    ctx.settings.output_mode, ctx.settings.device_path = "path", "/dev/usb/lp0"
    click(page, "Send to cutter", qapp)
    assert f.sent[-1][:2] == ("path", "/dev/usb/lp0")


def test_send_asks_when_cut_exceeds_media(app_env):
    win, ctx, f, qapp = app_env
    page = win.job_page
    page.load_file(f.open_file)
    ctx.settings.printer = "Silhouette CAMEO"
    page.offset_x.setValue(400)
    page.rebuild()
    assert "Exceeds" in page.chip.text()
    f.answer = QMessageBox.StandardButton.No
    click(page, "Send to cutter", qapp)
    assert f.sent == [] and f.messages[-1][0] == "warning"
    f.answer = QMessageBox.StandardButton.Yes
    click(page, "Send to cutter", qapp)
    assert len(f.sent) == 1


def test_send_failure_is_reported(app_env, monkeypatch):
    win, ctx, f, qapp = app_env
    page = win.job_page
    page.load_file(f.open_file)
    ctx.settings.printer = "Silhouette CAMEO"

    def fail(*a, **k):
        raise output.OutputError("printer offline")

    monkeypatch.setattr(output, "send_to_printer", fail)
    click(page, "Send to cutter", qapp)
    assert f.messages[-1][0] == "critical" and "printer offline" in f.messages[-1][1]


def test_unreadable_file_is_reported(app_env):
    win, ctx, f, qapp = app_env
    bad = f.tmp / "notes.txt"
    bad.write_text("this is not a gerber file")
    f.open_file = str(bad)
    click(win.job_page, "Open", qapp)
    assert f.messages[-1][0] == "critical" and win.job_page.gerber is None


def test_preview_toolbar_and_simulation(app_env):
    win, ctx, f, qapp = app_env
    page = win.job_page
    page.load_file(f.open_file)
    pv = page.preview

    scale = pv._scale
    click(page, "Zoom in", qapp)
    assert pv._scale > scale
    click(page, "Zoom out", qapp)
    assert pv._scale == pytest.approx(scale)
    click(page, "Zoom to stencil", qapp)
    stencil = pv._scale
    click(page, "Show whole sheet", qapp)
    assert pv._scale < stencil

    click(page, "Pads", qapp)
    assert pv.show_pads is False and ctx.settings.show_pads is False
    click(page, "Cut lines", qapp)
    assert pv.show_cuts is False
    click(page, "Pads", qapp)

    # play: switches the cut lines back on, runs, can be paused
    click(page, "Simulate the cutting order", qapp)
    assert page._sim_timer.isActive() and pv.show_cuts is True
    wait_for(lambda: pv.progress is not None and pv.progress > 0, qapp)
    click(page, "Simulate the cutting order", qapp)
    assert not page._sim_timer.isActive()
    click(page, "Simulate the cutting order", qapp)
    wait_for(lambda: not page._sim_timer.isActive(), qapp, timeout=20)
    assert pv.progress is None  # finished: normal view again


def test_parameter_buttons(app_env):
    win, ctx, f, qapp = app_env
    page = win.job_page
    page.load_file(f.open_file)

    click(page, "Fast", qapp)
    assert page.params().mode == "fast"
    click(page, "Accurate", qapp)
    assert page.params().mode == "accurate"

    click(page, "Add pass", qapp)
    assert len(page.params().passes) == 3
    removers = [b for b in page.findChildren(QAbstractButton) if b.toolTip() == "Remove this pass" and b.isVisible()]
    assert len(removers) == 3
    removers[0].click()
    qapp.processEvents()
    assert [(p.speed, p.force) for p in page.params().passes] == [(2, 30), (2, 30)]
    for _ in range(6):
        if button(page, "Add pass").isEnabled():
            click(page, "Add pass", qapp)
    assert len(page.params().passes) == 6 and not button(page, "Add pass").isEnabled()

    click(page, "Rotate by 90 degrees", qapp)
    click(page, "Rotate by 90 degrees", qapp)
    assert page.params().rotate == 180
    click(page, "Mirror horizontally", qapp)
    assert page.params().mirror is True

    page.media_combo.setCurrentIndex(3)
    page.media_combo.activated.emit(3)
    assert (page.params().media_w, page.params().media_h) == (210.0, 297.0)

    page.matrix[0].setValue(1.01)
    click(page, "Reset to identity", qapp)
    assert page.params().matrix == (1.0, 0.0, 0.0, 1.0)

    page.rebuild()
    assert page.job.params == page.params()


def test_profile_buttons_on_stencil_page(app_env):
    win, ctx, f, qapp = app_env
    page = win.job_page
    save, revert = button(page, "Save changes to this profile"), button(page, "Discard changes")
    assert not save.isEnabled() and not revert.isEnabled()

    page.inset.setValue(0.03)
    assert revert.isEnabled() and not save.isEnabled()  # built-in profile: only "save as"
    click(page, "Discard changes", qapp)
    assert page.params() == CutParams()

    page.inset.setValue(0.03)
    click(page, "Save as new profile", qapp)
    assert ctx.settings.active_profile == "My film" and ctx.store.get("My film").params.inset == pytest.approx(0.03)
    assert page.profile_combo.currentText() == "My film" and not save.isEnabled()

    page.inset.setValue(0.05)
    click(page, "Save changes to this profile", qapp)
    assert ctx.store.get("My film").params.inset == pytest.approx(0.05) and not save.isEnabled()

    # a built-in name is refused
    f.text = "Standard"
    click(page, "Save as new profile", qapp)
    assert f.messages[-1][0] == "warning" and ctx.settings.active_profile == "My film"

    page.profile_combo.setCurrentText("Draft")
    page.profile_combo.activated.emit(page.profile_combo.currentIndex())
    assert page.params().mode == "fast"


# ------------------------------------------------------------------ profiles page


def test_profiles_page_buttons(app_env):
    win, ctx, f, qapp = app_env
    click(win, "Profiles", qapp)
    page = win.profiles_page
    assert win.stack.currentWidget() is page
    assert not button(page, "Rename").isEnabled() and not button(page, "Delete").isEnabled()  # built-in selected

    click(page, "Duplicate", qapp)
    assert page.current().name == "Standard copy" and not page.current().builtin
    page.description.setPlainText("0.1 mm Mylar")
    assert ctx.store.get("Standard copy").description == "0.1 mm Mylar"

    f.text = "Mylar"
    click(page, "Rename", qapp)
    assert page.current().name == "Mylar" and ctx.store.get("Standard copy") is None

    f.save_file = str(f.tmp / "mylar.json")
    click(page, "Export", qapp)
    assert json.loads(Path(f.save_file).read_text(encoding="utf-8"))["name"] == "Mylar"

    f.open_file = f.save_file
    click(page, "Import", qapp)
    assert page.current().name == "Mylar 2"

    f.open_file = str(EXAMPLES / "test_tiny.gbr")  # not a profile
    click(page, "Import", qapp)
    assert f.messages[-1][0] == "warning"

    click(page, "Delete", qapp)
    assert ctx.store.get("Mylar 2") is None and ctx.store.get("Mylar") is not None

    page.refresh(select="Fine Pitch")
    click(page, "Use for stencil", qapp)
    assert win.stack.currentWidget() is win.job_page
    assert ctx.settings.active_profile == "Fine Pitch" and len(win.job_page.params().passes) == 3

    # the list survives a restart
    from g2g.profiles import ProfileStore

    assert "Mylar" in ProfileStore().names()


# ------------------------------------------------------------------ settings page


def test_settings_page_controls(app_env):
    from g2g.ui import theme
    from g2g.ui.context import Context
    from g2g.ui.widgets import LengthSpin

    win, ctx, f, qapp = app_env
    click(win, "Settings", qapp)
    page = win.settings_page
    assert win.stack.currentWidget() is page

    def choose(combo, data):
        combo.setCurrentIndex(combo.findData(data))
        combo.activated.emit(combo.currentIndex())
        qapp.processEvents()

    choose(page.theme, "light")
    assert theme.palette().name == "light"
    choose(page.theme, "dark")
    assert theme.palette().name == "dark"

    choose(page.units, "inch")
    assert win.job_page.offset_x.suffix() == " in" and win.job_page.offset_x.value() == pytest.approx(4.0)
    choose(page.units, "mm")
    assert win.job_page.offset_x.value() == pytest.approx(101.6)
    assert LengthSpin._unit == "mm"

    choose(page.language, "de")
    assert page.language_hint.text() != ""

    # the cutter was recognised by its name and preselected
    assert page.printer.currentData() == "Silhouette CAMEO"
    click(page, "Refresh the printer list", qapp)
    choose(page.printer, "Office Laser")
    assert ctx.settings.printer == "Office Laser"

    click(page, "Device path or printer share", qapp)
    assert ctx.settings.output_mode == "path" and page.device_path.isEnabled() and not page.printer.isEnabled()
    page.device_path.setText("/dev/usb/lp0")
    page.device_path.editingFinished.emit()
    click(page, "System printer (recommended)", qapp)
    assert ctx.settings.output_mode == "printer"

    click(page, "Ask before sending a job to the cutter", qapp)
    assert ctx.settings.confirm_send is True
    click(page, "Check for updates when the application starts", qapp)
    assert ctx.settings.check_updates is False

    win.job_page.load_file(f.open_file)
    page.tolerance.setValue(0.05)
    assert ctx.settings.arc_tolerance == pytest.approx(0.05)

    click(page, "Open settings folder", qapp)
    assert f.urls and "Gerber2Graphtec" in f.urls[-1]

    saved = Context().settings  # everything above was written to disk
    assert (saved.language, saved.theme, saved.units) == ("de", "dark", "mm")
    assert (saved.printer, saved.device_path, saved.check_updates) == ("Office Laser", "/dev/usb/lp0", False)


def test_curve_tolerance_reloads_the_file(app_env):
    win, ctx, f, qapp = app_env
    win.job_page.load_file(str(EXAMPLES / "fine_pitch_sampler.gbr"))
    fine = win.job_page.job.stats().segments_per_pass
    win.settings_page.tolerance.setValue(0.05)
    assert win.job_page.job.stats().segments_per_pass < fine


# ------------------------------------------------------------------ updates and about


def test_update_check_buttons(app_env, monkeypatch):
    from g2g.ui import main_window

    win, ctx, f, qapp = app_env
    shown: list[str] = []

    def fake_exec(dialog):
        shown.append(dialog.windowTitle())
        if f.text == "skip":
            click(dialog, "Skip this version", qapp)
        elif f.text == "download":
            click(dialog, "Download", qapp)
        else:
            click(dialog, "Later", qapp)
        return 0

    monkeypatch.setattr(main_window.UpdateDialog, "exec", fake_exec)
    page = win.settings_page

    def check(where, name):
        click(where, name, qapp)
        wait_for(lambda: button(page, "Check now").isEnabled(), qapp)

    # no release published
    check(page, "Check now")
    assert "up to date" in page.update_status.text() and f.messages[-1][0] == "information"

    # newer release: download opens the browser
    f.release = updater.Release("99.1.0", "https://example.invalid/r", "notes", "https://example.invalid/app.exe")
    f.text = "download"
    check(win.about_page, "Check for updates")
    assert shown == ["Update available"] and f.urls[-1] == "https://example.invalid/app.exe"
    assert "99.1.0" in page.update_status.text()

    # skip: remembered, the automatic check stays quiet, a manual check still offers it
    f.text = "skip"
    check(page, "Check now")
    assert ctx.settings.skipped_version == "99.1.0"
    win.check_updates(manual=False)
    wait_for(lambda: button(page, "Check now").isEnabled(), qapp)
    assert len(shown) == 2
    f.text = "later"
    check(page, "Check now")
    assert len(shown) == 3

    # network failure
    def offline(*a, **k):
        raise updater.UpdateError("offline")

    monkeypatch.setattr(updater, "fetch_latest", offline)
    check(page, "Check now")
    assert "offline" in page.update_status.text() and f.messages[-1][0] == "warning"


def test_about_page_buttons(app_env):
    win, ctx, f, qapp = app_env
    click(win, "About", qapp)
    assert win.stack.currentWidget() is win.about_page
    click(win.about_page, "GitHub", qapp)
    click(win.about_page, "Releases", qapp)
    assert f.urls == [
        "https://github.com/reserve85/Gerber_to_Graphtec_modern",
        "https://github.com/reserve85/Gerber_to_Graphtec_modern/releases",
    ]
    click(win, "Stencil", qapp)
    assert win.stack.currentWidget() is win.job_page


# ------------------------------------------------------------------ everything, twice


@pytest.mark.parametrize("lang", ["en", "de"])
def test_click_every_button_without_errors(app_env, lang):
    """Brute force: press every button on every page, with and without a file."""
    win, ctx, f, qapp = app_env
    i18n.set_language(lang)
    ctx.settings.printer = "Silhouette CAMEO"
    for load in (False, True):
        if load:
            win.job_page.load_file(str(EXAMPLES / "test_tiny.gbr"))
        for index in range(win.stack.count()):
            win.show_page(index)
            qapp.processEvents()
            page = win.stack.widget(index)
            clicked = 0
            # buttons can be recreated by a click (pass list), so look them up one at a time
            for i in range(200):
                buttons = [b for b in page.findChildren(QAbstractButton) if b.isVisible() and b.isEnabled()]
                if i >= len(buttons):
                    break
                buttons[i].click()
                qapp.processEvents()
                clicked += 1
            assert clicked >= 2  # "Use for stencil" leaves the profiles page early
    win.job_page._stop_sim()
    assert f.errors == []
