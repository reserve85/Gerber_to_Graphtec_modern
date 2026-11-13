"""About page: version, links, credits."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from .. import APP_NAME, GITHUB_REPO, __version__
from ..i18n import tr
from ..updater import releases_url
from .context import Context
from .theme import Glyph
from .widgets import Card, Page, label, push_button

ASSETS = Path(__file__).resolve().parent.parent / "assets"


class AboutPage(Page):
    def __init__(self, ctx: Context, parent=None):
        super().__init__(tr("About"), parent=parent)

        card = Card()
        row = QHBoxLayout()
        row.setSpacing(18)
        logo = QLabel()
        pix = QPixmap(str(ASSETS / "icon.png"))
        if not pix.isNull():
            pix = pix.scaled(144, 144, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pix.setDevicePixelRatio(2.0)
            logo.setPixmap(pix)
        row.addWidget(logo)
        text = QVBoxLayout()
        text.setSpacing(4)
        text.addWidget(label(APP_NAME, "pageTitle"))
        text.addWidget(label(tr("Version {0}").format(__version__), "muted"))
        text.addWidget(
            label(
                tr(
                    "Cuts fine-pitch SMT solder paste stencils from Gerber files on Graphtec craft cutters "
                    "such as the Silhouette Cameo and Portrait."
                ),
                wrap=True,
            )
        )
        row.addLayout(text, 1)
        card.add_wide(row)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        update = push_button(tr("Check for updates"), Glyph.SYNC, primary=True)
        update.clicked.connect(ctx.checkUpdatesRequested.emit)
        github = push_button("GitHub", Glyph.GLOBE)
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{GITHUB_REPO}")))
        releases = push_button(tr("Releases"), Glyph.EXPORT)
        releases.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(releases_url())))
        for b in (update, github, releases):
            buttons.addWidget(b)
        buttons.addStretch(1)
        card.add_wide(buttons)
        self.root.addWidget(card)

        card = Card(tr("How it works"))
        card.add_wide(
            label(
                tr(
                    "Instead of following each pad outline in one go, every edge is cut as a separate straight line, "
                    "always in both directions and grouped by knife angle. A short training cut outside the stencil "
                    "aligns the drag knife before each group. Combined with several passes of rising force this gives "
                    "clean openings down to about 0.5 mm pitch."
                ),
                wrap=True,
            )
        )
        self.root.addWidget(card)

        card = Card(tr("Credits & license"))
        credits = label(
            tr(
                "Based on gerber2graphtec by Peter Monta (2012) with the GUI by jesuscf and Python 3 port. "
                "Protocol knowledge from robocut and graphtecprint. This rewrite reads Gerber files natively "
                "and no longer needs gerbv or pstoedit."
            )
            + "<br><br>"
            + tr("Free software under the GNU General Public License v2, without any warranty.")
            + "<br>Qt for Python (LGPL) · Shapely (BSD)",
            wrap=True,
        )
        credits.setTextFormat(Qt.TextFormat.RichText)
        card.add_wide(credits)
        self.root.addWidget(card)
        self.root.addStretch(1)
