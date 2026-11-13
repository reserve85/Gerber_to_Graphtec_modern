"""Look & feel: colour palettes, style sheet, glyph icons."""

from __future__ import annotations

import sys
import tempfile
import weakref
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    on_accent: str
    danger: str
    warning: str
    # preview canvas
    canvas: str
    sheet: str
    grid: str
    pad: str
    cut: str
    training: str
    frame: str


DARK = Palette(
    name="dark",
    bg="#0e1014",
    surface="#161920",
    surface2="#1e222b",
    border="#2a2f3b",
    text="#e7eaf0",
    muted="#8a93a5",
    accent="#1fcfa6",
    accent_hover="#43e0bb",
    on_accent="#04211a",
    danger="#f2555a",
    warning="#f5a524",
    canvas="#0a0c0f",
    sheet="#1a1e27",
    grid="#262b36",
    pad="#d9a441",
    cut="#1fcfa6",
    training="#f5a524",
    frame="#5b8def",
)

LIGHT = Palette(
    name="light",
    bg="#f3f4f7",
    surface="#ffffff",
    surface2="#eef0f4",
    border="#d9dde5",
    text="#1a1e26",
    muted="#667085",
    accent="#0b9a7a",
    accent_hover="#0db08c",
    on_accent="#ffffff",
    danger="#d92d3a",
    warning="#c77700",
    canvas="#e3e6ec",
    sheet="#ffffff",
    grid="#e6e9ef",
    pad="#b9811f",
    cut="#0b9a7a",
    training="#d97a00",
    frame="#2f6fe4",
)

_current: Palette = DARK


def palette() -> Palette:
    return _current


class Glyph:
    """Segoe Fluent Icons / Segoe MDL2 Assets code points."""

    CUT = ""
    PROFILES = ""
    SETTINGS = ""
    INFO = ""
    OPEN = ""
    SAVE = ""
    SAVE_AS = ""
    SEND = ""
    ADD = ""
    DELETE = ""
    COPY = ""
    RENAME = ""
    IMPORT = ""
    EXPORT = ""
    REFRESH = ""
    PLAY = ""
    PAUSE = ""
    ZOOM_IN = ""
    ZOOM_OUT = ""
    FIT = ""
    ZOOM = ""
    ROTATE = ""
    UNDO = ""
    WARNING = ""
    CHECK = ""
    FOLDER = ""
    GLOBE = ""
    SYNC = ""
    CLOSE = ""
    FILE = ""


def icon_font_family() -> str:
    families = set(QFontDatabase.families())
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in families:
            return name
    return ""


# Plain Unicode stand-ins for systems without the Segoe icon fonts (Linux, macOS).
_FALLBACK = {
    Glyph.CUT: "✂", Glyph.PROFILES: "☰", Glyph.SETTINGS: "⚙", Glyph.INFO: "ℹ",
    Glyph.OPEN: "↗", Glyph.SAVE: "⤓", Glyph.SAVE_AS: "⤓", Glyph.SEND: "➤",
    Glyph.ADD: "+", Glyph.DELETE: "✕", Glyph.COPY: "⧉", Glyph.RENAME: "✎",
    Glyph.IMPORT: "⤓", Glyph.EXPORT: "⤒", Glyph.REFRESH: "↻", Glyph.PLAY: "▶",
    Glyph.PAUSE: "‖", Glyph.ZOOM_IN: "+", Glyph.ZOOM_OUT: "−", Glyph.FIT: "⛶",
    Glyph.ZOOM: "⌖", Glyph.ROTATE: "↻", Glyph.UNDO: "↶", Glyph.WARNING: "⚠",
    Glyph.CHECK: "✓", Glyph.FOLDER: "▤", Glyph.GLOBE: "◎", Glyph.SYNC: "↻",
    Glyph.CLOSE: "✕", Glyph.FILE: "▾", "": "▾",
}  # fmt: skip


def glyph_pixmap(glyph: str, color: str, size: int = 18, dpr: float = 2.0) -> QPixmap:
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    family = icon_font_family()
    if family:
        font = QFont(family)
    else:
        font = QFont()
        glyph = _FALLBACK.get(glyph, glyph)
    font.setPixelSize(size)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return px


_glyph_buttons: weakref.WeakKeyDictionary[QAbstractButton, tuple[str, str, int]] = weakref.WeakKeyDictionary()


def _glyph_icon(glyph: str, role: str, size: int) -> QIcon:
    p = _current
    color = getattr(p, role)
    icon = QIcon()
    icon.addPixmap(glyph_pixmap(glyph, color, size), QIcon.Mode.Normal)
    icon.addPixmap(glyph_pixmap(glyph, p.muted, size), QIcon.Mode.Disabled)
    if role == "muted":
        icon.addPixmap(glyph_pixmap(glyph, p.accent, size), QIcon.Mode.Normal, QIcon.State.On)
    return icon


def set_glyph(button: QAbstractButton, glyph: str, role: str = "text", size: int = 16) -> None:
    """Give a button a glyph icon that follows the theme (role = palette field)."""
    _glyph_buttons[button] = (glyph, role, size)
    button.setIcon(_glyph_icon(glyph, role, size))
    button.setIconSize(QSize(size, size))


def resolve_mode(mode: str) -> str:
    if mode in ("dark", "light"):
        return mode
    scheme = QApplication.styleHints().colorScheme()
    return "light" if scheme == Qt.ColorScheme.Light else "dark"


def apply_theme(app: QApplication, mode: str) -> Palette:
    global _current
    _current = LIGHT if resolve_mode(mode) == "light" else DARK
    p = _current
    app.setStyle("Fusion")

    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, p.bg),
        (QPalette.ColorRole.Base, p.surface),
        (QPalette.ColorRole.AlternateBase, p.surface2),
        (QPalette.ColorRole.Button, p.surface2),
        (QPalette.ColorRole.Text, p.text),
        (QPalette.ColorRole.WindowText, p.text),
        (QPalette.ColorRole.ButtonText, p.text),
        (QPalette.ColorRole.ToolTipBase, p.surface2),
        (QPalette.ColorRole.ToolTipText, p.text),
        (QPalette.ColorRole.Highlight, p.accent),
        (QPalette.ColorRole.HighlightedText, p.on_accent),
        (QPalette.ColorRole.PlaceholderText, p.muted),
        (QPalette.ColorRole.Link, p.accent),
    ):
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.muted))
    app.setPalette(pal)
    app.setStyleSheet(build_qss(p))

    for button, (glyph, role, size) in list(_glyph_buttons.items()):
        button.setIcon(_glyph_icon(glyph, role, size))
    for w in app.topLevelWidgets():
        set_title_bar_dark(w, p.name == "dark")
        w.update()
    return p


def set_title_bar_dark(widget: QWidget, dark: bool) -> None:
    """Match the native Windows title bar to the theme."""
    if sys.platform != "win32" or not widget.isWindow():
        return
    try:
        import ctypes

        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def _asset_image(name: str, glyph: str, color: str, size: int) -> str:
    """Render a small glyph to a temp PNG so the style sheet can reference it."""
    folder = Path(tempfile.gettempdir()) / "gerber2graphtec"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}_{color.lstrip(chr(35))}.png"
    if not path.exists():
        glyph_pixmap(glyph, color, size).save(str(path))
    return path.as_posix()


def build_qss(p: Palette) -> str:
    arrow = _asset_image("arrow", "", p.muted, 10)
    check = _asset_image("check", Glyph.CHECK, p.on_accent, 12)
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; }}
QWidget {{ color: {p.text}; }}
QMainWindow, QDialog, #root {{ background: {p.bg}; }}
QToolTip {{ background: {p.surface2}; color: {p.text}; border: 1px solid {p.border}; padding: 6px 8px; border-radius: 6px; }}

/* navigation rail */
#nav {{ background: {p.surface}; border-right: 1px solid {p.border}; }}
#navButton {{ border: none; border-radius: 10px; padding: 8px 4px 6px 4px; color: {p.muted}; font-size: 8pt; background: transparent; }}
#navButton:hover {{ background: {p.surface2}; color: {p.text}; }}
#navButton:checked {{ background: {p.surface2}; color: {p.accent}; }}
#navVersion {{ color: {p.muted}; font-size: 8pt; }}

/* typography */
#pageTitle {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 17pt; font-weight: 600; }}
#pageSubtitle, #muted {{ color: {p.muted}; }}
#cardTitle {{ font-size: 8pt; font-weight: 700; color: {p.muted}; letter-spacing: 1px; }}
#fieldLabel {{ color: {p.muted}; }}
#statValue {{ font-size: 11pt; font-weight: 600; }}
#statLabel {{ color: {p.muted}; font-size: 8pt; }}
#fileName {{ font-size: 11pt; font-weight: 600; }}
#badge {{ background: {p.surface2}; color: {p.muted}; border: 1px solid {p.border}; border-radius: 8px; padding: 1px 8px; font-size: 8pt; }}
#warnChip {{ background: transparent; color: {p.warning}; border: 1px solid {p.warning}; border-radius: 10px; padding: 3px 10px; }}
#okChip {{ background: transparent; color: {p.accent}; border: 1px solid {p.accent}; border-radius: 10px; padding: 3px 10px; }}
#toast {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 10px; padding: 9px 16px; }}
#banner {{ background: {p.surface}; border: 1px solid {p.accent}; border-radius: 10px; }}

/* cards */
#card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
#previewFrame {{ background: {p.canvas}; border: 1px solid {p.border}; border-radius: 12px; }}
#statBar {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}

/* buttons */
QPushButton {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 8px; padding: 6px 14px; min-height: 20px; }}
QPushButton:hover {{ border-color: {p.muted}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:disabled {{ color: {p.muted}; background: transparent; }}
QPushButton#primary {{ background: {p.accent}; color: {p.on_accent}; border: none; font-weight: 600; padding: 7px 18px; }}
QPushButton#primary:hover {{ background: {p.accent_hover}; }}
QPushButton#primary:disabled {{ background: {p.surface2}; color: {p.muted}; }}
QPushButton#danger:hover {{ border-color: {p.danger}; color: {p.danger}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 5px; }}
QToolButton:hover {{ background: {p.surface2}; border-color: {p.border}; }}
QToolButton:checked {{ background: {p.surface2}; border-color: {p.border}; color: {p.accent}; }}
QToolButton#segment {{ border: 1px solid {p.border}; border-radius: 8px; padding: 6px 12px; background: {p.surface2}; color: {p.muted}; }}
QToolButton#segment:checked {{ background: {p.accent}; color: {p.on_accent}; border-color: {p.accent}; font-weight: 600; }}

/* inputs */
QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit, QTextBrowser {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 8px; padding: 5px 8px;
    selection-background-color: {p.accent}; selection-color: {p.on_accent}; min-height: 20px; }}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {p.accent}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 10px; height: 10px; margin-right: 10px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QAbstractSpinBox QLineEdit {{ border: none; padding: 0; margin: 0; background: transparent; min-height: 0; }}
QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px; outline: none; selection-background-color: {p.surface2}; selection-color: {p.accent}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {p.muted}; background: {p.surface2}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; image: url("{check}"); }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1px solid {p.muted}; background: {p.surface2}; }}
QRadioButton::indicator:checked {{ width: 6px; height: 6px; border: 5px solid {p.accent}; background: {p.on_accent}; }}

/* lists */
QListWidget {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; padding: 6px; outline: none; }}
QListWidget::item {{ border-radius: 8px; padding: 9px 10px; }}
QListWidget::item:hover {{ background: {p.surface2}; }}
QListWidget::item:selected {{ background: {p.surface2}; color: {p.accent}; }}

/* slider */
QSlider::groove:horizontal {{ height: 4px; background: {p.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: {p.accent}; }}

/* scroll */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 3px; min-width: 30px; }}

QMenu {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.surface2}; color: {p.accent}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 8px; }}
"""
