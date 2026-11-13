"""Render the screenshots used in the README into docs/.

Runs the real application with a throw-away configuration folder:
    python scripts/make_screenshots.py
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = tempfile.mkdtemp(prefix="g2g_shots_")
os.environ["APPDATA"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from g2g import i18n  # noqa: E402
from g2g.core import output  # noqa: E402
from g2g.ui import theme  # noqa: E402
from g2g.ui.context import Context  # noqa: E402
from g2g.ui.main_window import MainWindow  # noqa: E402
from g2g.ui.widgets import LengthSpin  # noqa: E402

DOCS = ROOT / "docs"
EXAMPLES = ROOT / "examples"


def main() -> None:
    app = QApplication(sys.argv[:1])
    i18n.set_language("en")
    ctx = Context()
    ctx.settings.printer = "Silhouette CAMEO"
    output.list_printers = lambda: ["Silhouette CAMEO"]  # the same picture on every machine
    LengthSpin.set_unit("mm")
    theme.apply_theme(app, "dark")
    win = MainWindow(ctx)
    win.resize(1320, 840)
    win.show()
    page = win.job_page

    def settle() -> None:
        for _ in range(5):
            app.processEvents()

    def shot(name: str) -> None:
        settle()
        page.file_sub.setText("examples")  # no local folder names in published images
        win.grab().save(str(DOCS / name))
        print("written", name)

    # 1 - main view, dark
    page.load_file(str(EXAMPLES / "kicad_style_qfn32.gbr"))
    page.apply_profile("Fine Pitch")
    page.rebuild(refit=True)
    shot("screenshot.png")

    # 2 - simulation of the cutting order, zoomed to the QFN
    pv = page.preview
    pv.fit_stencil()
    settle()
    pv.zoom(2.6, QPointF(pv.width() * 0.62, pv.height() * 0.52))
    page.sim_slider.setValue(int(page.sim_slider.maximum() * 0.45))
    shot("simulation.png")
    page.sim_slider.setValue(page.sim_slider.maximum())

    # 3 - statistics, light theme
    theme.apply_theme(app, "light")
    page.load_file(str(EXAMPLES / "example1.gbr"))
    page.apply_profile("Standard")
    page.rebuild(refit=True)
    settle()
    scroll = page.findChild(type(page.layout().itemAt(1).widget()))
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    shot("statistics_light.png")

    # 4 - profiles and settings
    theme.apply_theme(app, "dark")
    win.show_page(1)
    win.profiles_page.refresh(select="Fine Pitch")
    shot("profiles.png")
    win.show_page(2)
    shot("settings.png")
    win.close()


if __name__ == "__main__":
    main()
