"""Application entry point."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QLocale, QTimer
from PySide6.QtWidgets import QApplication

from .. import APP_AUTHOR, APP_NAME, __version__
from .. import i18n
from . import theme
from .context import Context
from .widgets import LengthSpin


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=APP_NAME)
    ap.add_argument("file", nargs="?", help="Gerber file to open")
    ap.add_argument("--version", action="version", version=__version__)
    # developer helpers: render a page to an image and quit
    ap.add_argument("--screenshot", help=argparse.SUPPRESS)
    ap.add_argument("--page", type=int, default=0, help=argparse.SUPPRESS)
    ap.add_argument("--theme", help=argparse.SUPPRESS)
    ap.add_argument("--lang", help=argparse.SUPPRESS)
    args, qt_args = ap.parse_known_args(sys.argv[1:] if argv is None else argv)

    if sys.platform == "win32":
        try:  # own taskbar identity instead of "python"
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_AUTHOR}.{APP_NAME}")
        except Exception:
            pass

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)

    ctx = Context()
    lang = args.lang or ctx.settings.language
    if lang == "auto":
        lang = "de" if QLocale.system().name().lower().startswith("de") else "en"
    i18n.set_language(lang)
    LengthSpin.set_unit(ctx.settings.units)
    if args.theme:
        ctx.settings.theme = args.theme
    theme.apply_theme(app, ctx.settings.theme)

    from .main_window import MainWindow

    win = MainWindow(ctx)
    app.styleHints().colorSchemeChanged.connect(
        lambda _: ctx.settings.theme == "system" and theme.apply_theme(app, "system")
    )
    win.show()

    if args.file:
        QTimer.singleShot(0, lambda: win.job_page.load_file(args.file))

    if args.screenshot:
        win.show_page(args.page)

        def shoot() -> None:
            win.grab().save(args.screenshot)
            app.quit()

        QTimer.singleShot(900, shoot)
    elif ctx.settings.check_updates:
        QTimer.singleShot(1500, win.check_updates)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
