"""Application settings."""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import output
from ..i18n import tr
from ..settings import config_dir
from .context import Context
from .theme import Glyph
from .widgets import Card, ComboBox, LengthSpin, Page, label, push_button, tool_button


class SettingsPage(Page):
    def __init__(self, ctx: Context, parent=None):
        super().__init__(tr("Settings"), parent=parent)
        self.ctx = ctx
        s = ctx.settings

        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(14)

        # appearance
        card = Card(tr("Appearance"))
        self.theme = ComboBox()
        for key, text in (("system", tr("Follow system")), ("dark", tr("Dark")), ("light", tr("Light"))):
            self.theme.addItem(text, key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.theme)))
        self.theme.activated.connect(self._theme_changed)
        card.add_row(tr("Theme"), self.theme)
        self.language = ComboBox()
        for key, text in (("auto", tr("Follow system")), ("de", "Deutsch"), ("en", "English")):
            self.language.addItem(text, key)
        self.language.setCurrentIndex(max(0, self.language.findData(s.language)))
        self.language.activated.connect(self._language_changed)
        self.language_hint = label("", "muted")
        card.add_row(tr("Language"), self.language, self.language_hint)
        self.units = ComboBox()
        self.units.addItem(tr("Millimetres"), "mm")
        self.units.addItem(tr("Inches"), "inch")
        self.units.setCurrentIndex(max(0, self.units.findData(s.units)))
        self.units.activated.connect(self._units_changed)
        card.add_row(tr("Units"), self.units)
        col.addWidget(card)

        # cutter output
        card = Card(tr("Cutter output"))
        self.mode_printer = QRadioButton(tr("System printer (recommended)"))
        self.mode_path = QRadioButton(tr("Device path or printer share"))
        (self.mode_printer if s.output_mode == "printer" else self.mode_path).setChecked(True)
        self.mode_printer.toggled.connect(self._output_changed)
        card.add_wide(self.mode_printer)
        self.printer = ComboBox()
        self.printer.activated.connect(self._output_changed)
        refresh = tool_button(Glyph.REFRESH, tr("Refresh the printer list"))
        refresh.clicked.connect(self._load_printers)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.printer, 1)
        row.addWidget(refresh)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        self.printer_row = card.add_row(
            tr("Cutter"),
            holder,
            tip=tr("The Silhouette / Graphtec cutter as it appears in the printer list of your system (Windows: Printers & scanners, Linux: CUPS). The job is sent as RAW data."),
        )
        card.add_wide(self.mode_path)
        self.device_path = QLineEdit(s.device_path)
        self.device_path.setPlaceholderText(r"\\PC-NAME\Cutter   |   /dev/usb/lp0")
        self.device_path.editingFinished.connect(self._output_changed)
        card.add_row(tr("Path"), self.device_path)
        self.confirm = QCheckBox(tr("Ask before sending a job to the cutter"))
        self.confirm.setChecked(s.confirm_send)
        self.confirm.toggled.connect(self._output_changed)
        card.add_wide(self.confirm)
        col.addWidget(card)

        # import
        card = Card(tr("Gerber import"))
        self.tolerance = LengthSpin(0.001, 0.1, 0.001)
        self.tolerance.set_mm(s.arc_tolerance)
        self.tolerance.mmChanged.connect(self._tolerance_changed)
        card.add_row(
            tr("Curve tolerance"),
            self.tolerance,
            tip=tr("Maximum deviation when round pads and arcs are converted to straight cuts. Smaller = more, shorter cuts."),
        )
        col.addWidget(card)

        # updates
        card = Card(tr("Updates"))
        self.auto_update = QCheckBox(tr("Check for updates when the application starts"))
        self.auto_update.setChecked(s.check_updates)
        self.auto_update.toggled.connect(self._updates_changed)
        card.add_wide(self.auto_update)
        row = QHBoxLayout()
        self.check_button = push_button(tr("Check now"), Glyph.SYNC)
        self.check_button.clicked.connect(ctx.checkUpdatesRequested.emit)
        self.update_status = label("", "muted")
        row.addWidget(self.check_button)
        row.addWidget(self.update_status, 1)
        card.add_wide(row)
        col.addWidget(card)

        # data
        card = Card(tr("Data"))
        row = QHBoxLayout()
        folder = push_button(tr("Open settings folder"), Glyph.FOLDER)
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_dir()))))
        row.addWidget(folder)
        row.addStretch(1)
        card.add_wide(row)
        col.addWidget(card)
        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        wrap = QHBoxLayout()
        scroll.setMaximumWidth(760)
        wrap.addWidget(scroll)
        wrap.addStretch(0)
        self.root.addLayout(wrap, 1)

        self.reload_job = lambda: None  # set by the main window
        self._load_printers()
        self._sync_enabled()

    # -- handlers ----------------------------------------------------------

    def _load_printers(self) -> None:
        s = self.ctx.settings
        names = output.list_printers()
        self.printer.blockSignals(True)
        self.printer.clear()
        self.printer.addItem(tr("(not selected)"), "")
        for name in names:
            self.printer.addItem(name, name)
        if s.printer and s.printer not in names:
            self.printer.addItem(s.printer + "  " + tr("(not found)"), s.printer)
        self.printer.setCurrentIndex(max(0, self.printer.findData(s.printer)))
        self.printer.blockSignals(False)
        # Convenience: preselect an obvious cutter if nothing is configured yet.
        if not s.printer:
            for name in names:
                if any(k in name.lower() for k in ("silhouette", "cameo", "portrait", "graphtec")):
                    self.printer.setCurrentIndex(self.printer.findData(name))
                    s.printer = name
                    break

    def _sync_enabled(self) -> None:
        printer = self.mode_printer.isChecked()
        self.printer.setEnabled(printer)
        self.device_path.setEnabled(not printer)

    def _output_changed(self, *_) -> None:
        s = self.ctx.settings
        s.output_mode = "printer" if self.mode_printer.isChecked() else "path"
        s.printer = self.printer.currentData() or ""
        s.device_path = self.device_path.text().strip()
        s.confirm_send = self.confirm.isChecked()
        self._sync_enabled()
        s.save()

    def _theme_changed(self, *_) -> None:
        self.ctx.settings.theme = self.theme.currentData()
        self.ctx.settings.save()
        self.ctx.themeChanged.emit()

    def _language_changed(self, *_) -> None:
        self.ctx.settings.language = self.language.currentData()
        self.ctx.settings.save()
        self.language_hint.setText(tr("Takes effect after a restart"))

    def _units_changed(self, *_) -> None:
        self.ctx.settings.units = self.units.currentData()
        self.ctx.settings.save()
        LengthSpin.set_unit(self.ctx.settings.units)
        self.ctx.unitsChanged.emit()

    def _tolerance_changed(self, mm: float) -> None:
        self.ctx.settings.arc_tolerance = round(mm, 4)
        self.ctx.settings.save()
        self.reload_job()

    def _updates_changed(self, on: bool) -> None:
        self.ctx.settings.check_updates = on
        self.ctx.settings.save()

    def set_update_status(self, text: str, busy: bool = False) -> None:
        self.update_status.setText(text)
        self.check_button.setEnabled(not busy)
