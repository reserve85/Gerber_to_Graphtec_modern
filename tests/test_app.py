"""Profiles, settings, updater, statistics and a headless UI smoke test."""

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from g2g import updater
from g2g.core import graphtec
from g2g.core.gerber import load_gerber
from g2g.core.toolpath import CutParams, CutPass, build_job
from g2g.profiles import ProfileStore

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


# ---------------------------------------------------------------- statistics


def test_stats_accurate_mode():
    job = build_job(load_gerber(EXAMPLES / "corners.gbr").geometry, CutParams())
    st = job.stats()
    assert st.pads == 4 and st.passes == 2
    # 32 edge cuts + 4 training cuts + 1 border outline
    assert st.lifts_per_pass == 37 and st.lifts_total == 74
    assert st.segments_per_pass == 40
    assert st.angle_groups == 4
    pad = 0.0393 * 25.4
    training = 4 * 0.2 * 25.4
    border = 2 * (job.width + 50.8) + 2 * (job.height + 50.8)
    assert st.cut_per_pass == pytest.approx(4 * 4 * 2 * pad + training + border, rel=1e-6)
    assert st.cut_total == pytest.approx(2 * st.cut_per_pass)
    assert st.smallest_opening == pytest.approx(pad, rel=1e-6)
    assert st.travel_per_pass > 0 and st.seconds > 10
    # the stream contains exactly one move per knife stroke
    assert graphtec.encode(job).count(b"M") - 1 == st.lifts_total  # minus the "FM1" command


def test_stats_fast_mode_and_speed_scaling():
    geometry = load_gerber(EXAMPLES / "corners.gbr").geometry
    fast = build_job(geometry, CutParams(mode="fast", passes=[CutPass(5, 20)])).stats()
    assert fast.lifts_per_pass == 5 and fast.angle_groups == 0
    slow = build_job(geometry, CutParams(passes=[CutPass(1, 20)])).stats()
    quick = build_job(geometry, CutParams(passes=[CutPass(10, 20)])).stats()
    assert slow.seconds > quick.seconds


# ---------------------------------------------------------------- profiles


def test_profile_store_roundtrip(tmp_path):
    store = ProfileStore(tmp_path / "p.json")
    assert store.names()[:3] == ["Standard", "Fine Pitch", "Draft"]
    params = CutParams(inset=0.03, passes=[CutPass(1, 12)])
    store.put("Mylar 100", params, "my film")
    with pytest.raises(ValueError):
        store.put("standard", params)

    again = ProfileStore(tmp_path / "p.json")
    assert again.get("mylar 100").params == params
    assert again.rename("Mylar 100", "Mylar 125") and not again.rename("Mylar 125", "Draft")
    again.export_file("Mylar 125", str(tmp_path / "x.json"))
    imported = again.import_file(str(tmp_path / "x.json"))
    assert imported.name == "Mylar 125 2" and imported.params == params
    again.delete("Mylar 125")
    assert again.get("Mylar 125") is None
    with pytest.raises(ValueError):
        (tmp_path / "bad.json").write_text("{}")
        again.import_file(str(tmp_path / "bad.json"))


# ---------------------------------------------------------------- updater


def test_parse_version():
    assert updater.parse_version("v2.1.0") == (2, 1, 0)
    assert updater.parse_version("2.10") > updater.parse_version("2.9.9")
    assert updater.parse_version("v3.0.0-beta1") == (3, 0, 0)
    assert updater.parse_version("garbage") == (0,)


def test_fetch_latest(monkeypatch):
    payload = {
        "tag_name": "v99.0.0",
        "html_url": "https://example.invalid/release",
        "body": "notes",
        "assets": [
            {"name": "Gerber2Graphtec-99.0.0-linux-x86_64.tar.gz", "browser_download_url": "https://example.invalid/l"},
            {"name": "Gerber2Graphtec-99.0.0.exe", "browser_download_url": "https://example.invalid/w"},
        ],
    }

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout=0: Resp())
    rel = updater.fetch_latest()
    assert rel.version == "99.0.0" and rel.is_newer and rel.download_url.startswith("https://example.invalid/")

    def not_found(req, timeout=0):
        raise updater.urllib.error.HTTPError("u", 404, "nf", None, None)

    monkeypatch.setattr(updater.urllib.request, "urlopen", not_found)
    assert updater.fetch_latest() is None

    def offline(req, timeout=0):
        raise updater.urllib.error.URLError("offline")

    monkeypatch.setattr(updater.urllib.request, "urlopen", offline)
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest()


# ---------------------------------------------------------------- UI smoke test


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_main_window_workflow(qapp, tmp_path):
    from g2g import i18n
    from g2g.ui import theme
    from g2g.ui.context import Context
    from g2g.ui.main_window import MainWindow
    from g2g.ui.widgets import LengthSpin

    i18n.set_language("de")
    ctx = Context()
    LengthSpin.set_unit("mm")
    theme.apply_theme(qapp, "dark")
    win = MainWindow(ctx)
    page = win.job_page

    assert page.job.is_empty and not page.send_button.isEnabled()
    assert page.load_file(str(EXAMPLES / "test_tiny.gbr"))
    assert page.send_button.isEnabled() and page.stats["pads"].text() == "9"
    assert page.params() == CutParams()

    # editing parameters rebuilds the job and marks the profile as modified
    page.inset.setValue(0.02)
    page.rotate.setValue(90)
    page.rebuild()
    assert page.job.params.inset == pytest.approx(0.02) and page.job.params.rotate == 90
    assert page.dirty_label.text() == "geändert"

    # units: the same length shown in inches
    LengthSpin.set_unit("inch")
    assert page.offset_x.value() == pytest.approx(4.0) and page.offset_x.mm() == pytest.approx(101.6)
    LengthSpin.set_unit("mm")

    # profiles: save as user profile, then switch back
    ctx.store.put("Test", page.params())
    ctx.profilesChanged.emit()
    page.apply_profile("Test")
    assert page.dirty_label.text() == "" and page.params().rotate == 90
    page.apply_profile("Draft")
    assert page.params().mode == "fast" and len(page.params().passes) == 1
    page.rebuild()
    assert page.preview.line_count() == sum(len(s) for s in page.job.strokes)

    # simulation slider
    page.sim_slider.setValue(3)
    assert page.preview.progress == 3
    page.sim_slider.setValue(page.sim_slider.maximum())
    assert page.preview.progress is None

    # theme switch and all pages render
    theme.apply_theme(qapp, "light")
    for i in range(4):
        win.show_page(i)
        assert not win.grab().isNull()

    # session is persisted
    win.close()
    assert Context().settings.session_params["mode"] == "fast"
