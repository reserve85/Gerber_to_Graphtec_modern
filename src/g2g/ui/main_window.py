"""Main window: navigation rail, pages, update check."""

from __future__ import annotations

import threading

from PySide6.QtCore import QByteArray, QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__, updater
from ..i18n import tr
from . import theme
from .about_page import ASSETS, AboutPage
from .context import Context
from .job_page import JobPage
from .profiles_page import ProfilesPage
from .settings_page import SettingsPage
from .theme import Glyph
from .widgets import Toast, label, push_button


class UpdateWorker(QObject):
    """Looks up the latest release in a daemon thread, so it can never block quitting."""

    finishedWith = Signal(object, str)  # Release | None, error text

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False

    def start(self) -> None:
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            result, error = updater.fetch_latest(), ""
        except updater.UpdateError as exc:
            result, error = None, str(exc) or "error"
        self.running = False
        try:
            self.finishedWith.emit(result, error)
        except RuntimeError:
            pass  # window already closed


class UpdateDialog(QDialog):
    """Offers a newer release: open the download, skip this version, or later."""

    def __init__(self, release: updater.Release, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Update available"))
        self.setMinimumSize(520, 420)
        self.skip = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label(tr("{0} {1} is available").format(APP_NAME, release.version), "pageTitle"))
        lay.addWidget(label(tr("You are using version {0}.").format(__version__), "muted"))
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or tr("No release notes."))
        lay.addWidget(notes, 1)
        row = QHBoxLayout()
        skip = push_button(tr("Skip this version"))
        skip.clicked.connect(self._skip)
        later = push_button(tr("Later"))
        later.clicked.connect(self.reject)
        get = push_button(tr("Download"), Glyph.EXPORT, primary=True)
        get.clicked.connect(lambda: (QDesktopServices.openUrl(QUrl(release.download_url or release.url)), self.accept()))
        row.addWidget(skip)
        row.addStretch(1)
        row.addWidget(later)
        row.addWidget(get)
        lay.addLayout(row)

    def _skip(self) -> None:
        self.skip = True
        self.reject()

    def showEvent(self, event):  # noqa: N802
        theme.set_title_bar_dark(self, theme.palette().name == "dark")
        super().showEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self._worker: UpdateWorker | None = None
        self._manual_check = False
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(QIcon(str(ASSETS / "icon.png")))
        self.setMinimumSize(1040, 660)
        self.resize(1320, 840)
        self.setAcceptDrops(True)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # navigation rail
        nav = QFrame()
        nav.setObjectName("nav")
        nav.setFixedWidth(104)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(8, 14, 8, 12)
        nl.setSpacing(6)
        logo = QLabel()
        pix = QPixmap(str(ASSETS / "icon.png"))
        if not pix.isNull():
            pix = pix.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pix.setDevicePixelRatio(2.0)
            logo.setPixmap(pix)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.addWidget(logo)
        nl.addSpacing(10)

        self.stack = QStackedWidget()
        self.job_page = JobPage(ctx)
        self.profiles_page = ProfilesPage(ctx)
        self.settings_page = SettingsPage(ctx)
        self.about_page = AboutPage(ctx)
        self.settings_page.reload_job = self.job_page.reload
        self.nav_group = QButtonGroup(self)
        pages = (
            (self.job_page, Glyph.CUT, tr("Stencil")),
            (self.profiles_page, Glyph.PROFILES, tr("Profiles")),
            (self.settings_page, Glyph.SETTINGS, tr("Settings")),
            (self.about_page, Glyph.INFO, tr("About")),
        )
        for i, (page, glyph, text) in enumerate(pages):
            self.stack.addWidget(page)
            btn = QToolButton()
            btn.setObjectName("navButton")
            btn.setText(text)
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            btn.setFixedSize(88, 60)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            theme.set_glyph(btn, glyph, "muted", 20)
            btn.setIconSize(QSize(20, 20))
            self.nav_group.addButton(btn, i)
            nl.addWidget(btn)
            if i == 1:
                nl.addStretch(1)
        self.nav_group.idClicked.connect(self.stack.setCurrentIndex)
        self.nav_group.button(0).setChecked(True)
        version = label(f"v{__version__}", "navVersion")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.addWidget(version)
        lay.addWidget(nav)
        lay.addWidget(self.stack, 1)

        self.toast = Toast(root)
        ctx.toast.connect(self.toast.show_message)
        ctx.loadProfileRequested.connect(lambda _: self.show_page(0))
        ctx.checkUpdatesRequested.connect(lambda: self.check_updates(manual=True))
        ctx.themeChanged.connect(self._apply_theme)

        QShortcut(QKeySequence.StandardKey.Open, self, self.job_page.open_dialog)
        QShortcut(QKeySequence("Ctrl+E"), self, self.job_page.export_file)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.job_page.send)
        QShortcut(QKeySequence("F5"), self, self.job_page.reload)
        QShortcut(QKeySequence("Ctrl+,"), self, lambda: self.show_page(2))

        if ctx.settings.geometry:
            self.restoreGeometry(QByteArray.fromHex(ctx.settings.geometry.encode()))

    # -- helpers -----------------------------------------------------------

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav_group.button(index).setChecked(True)

    def _apply_theme(self) -> None:
        from PySide6.QtWidgets import QApplication

        theme.apply_theme(QApplication.instance(), self.ctx.settings.theme)

    def showEvent(self, event):  # noqa: N802
        theme.set_title_bar_dark(self, theme.palette().name == "dark")
        super().showEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self.ctx.settings.geometry = bytes(self.saveGeometry().toHex()).decode()
        self.ctx.settings.save()
        super().closeEvent(event)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.show_page(0)
                self.job_page.load_file(url.toLocalFile())
                break

    # -- updates -----------------------------------------------------------

    def check_updates(self, manual: bool = False) -> None:
        if self._worker is not None and self._worker.running:
            return
        self._manual_check = manual
        self.settings_page.set_update_status(tr("Checking ..."), busy=True)
        self._worker = UpdateWorker(self)
        self._worker.finishedWith.connect(self._update_result)
        self._worker.start()

    def _update_result(self, release, error: str) -> None:
        manual = self._manual_check
        status = self.settings_page.set_update_status
        if error:
            status(tr("Update check failed: {0}").format(error))
            if manual:
                QMessageBox.warning(self, tr("Check for updates"), tr("Update check failed: {0}").format(error))
            return
        if release is None or not release.is_newer:
            status(tr("You are up to date (version {0}).").format(__version__))
            if manual:
                text = tr("You are up to date (version {0}).").format(__version__)
                if release is None:
                    text += "\n" + tr("No release has been published yet.")
                QMessageBox.information(self, tr("Check for updates"), text)
            return
        status(tr("Version {0} is available.").format(release.version))
        if not manual and release.version == self.ctx.settings.skipped_version:
            return
        dlg = UpdateDialog(release, self)
        dlg.exec()
        if dlg.skip:
            self.ctx.settings.skipped_version = release.version
            self.ctx.settings.save()
