"""Manage cutting profiles."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..core.toolpath import CutParams
from ..i18n import tr
from ..profiles import Profile
from .context import Context
from .theme import Glyph
from .widgets import Card, Page, label, push_button


class ProfilesPage(Page):
    def __init__(self, ctx: Context, parent=None):
        super().__init__(tr("Profiles"), tr("Presets for materials and machines. Parameters are edited on the Stencil page."), parent)
        self.ctx = ctx

        self.import_button = push_button(tr("Import"), Glyph.IMPORT)
        self.import_button.clicked.connect(self._import)
        self.head.addWidget(self.import_button)

        body = QHBoxLayout()
        body.setSpacing(16)
        self.list = QListWidget()
        self.list.setFixedWidth(280)
        self.list.currentItemChanged.connect(lambda *_: self._show())
        body.addWidget(self.list)

        right = QVBoxLayout()
        right.setSpacing(12)
        self.card = Card()
        title_row = QHBoxLayout()
        self.name_label = label("", "fileName")
        self.badge = label(tr("built-in"), "badge")
        title_row.addWidget(self.name_label)
        title_row.addWidget(self.badge)
        title_row.addStretch(1)
        self.card.add_wide(title_row)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText(tr("Description (material, blade, notes ...)"))
        self.description.setFixedHeight(84)
        self.description.textChanged.connect(self._description_changed)
        self.card.add_wide(self.description)
        self.summary: dict[str, object] = {}
        for key, caption in (
            ("mode", tr("Mode")),
            ("passes", tr("Passes (speed / force)")),
            ("inset", tr("Pad shrink")),
            ("offset", tr("Offset X / Y")),
            ("border", tr("Border X / Y")),
            ("media", tr("Media")),
            ("rotate", tr("Rotation")),
            ("matrix", tr("Calibration")),
        ):
            value = label("")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.card.add_row(caption, value)
            self.summary[key] = value
        right.addWidget(self.card)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.use_button = push_button(tr("Use for stencil"), Glyph.CHECK, primary=True)
        self.use_button.clicked.connect(self._use)
        self.dup_button = push_button(tr("Duplicate"), Glyph.COPY)
        self.dup_button.clicked.connect(self._duplicate)
        self.rename_button = push_button(tr("Rename"), Glyph.RENAME)
        self.rename_button.clicked.connect(self._rename)
        self.export_button = push_button(tr("Export"), Glyph.EXPORT)
        self.export_button.clicked.connect(self._export)
        self.delete_button = push_button(tr("Delete"), Glyph.DELETE, danger=True)
        self.delete_button.clicked.connect(self._delete)
        for b in (self.use_button, self.dup_button, self.rename_button, self.export_button):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.delete_button)
        right.addLayout(actions)
        right.addStretch(1)
        body.addLayout(right, 1)
        self.root.addLayout(body, 1)

        ctx.profilesChanged.connect(self.refresh)
        ctx.unitsChanged.connect(self._show)
        self.refresh()

    def current(self) -> Profile | None:
        item = self.list.currentItem()
        return self.ctx.store.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def refresh(self, select: str | None = None) -> None:
        select = select or (self.current().name if self.current() else self.ctx.settings.active_profile)
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.ctx.store.all():
            text = p.name + ("   • " + tr("built-in") if p.builtin else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, p.name)
            self.list.addItem(item)
            if p.name == select:
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._show()

    def _show(self) -> None:
        p = self.current()
        if p is None:
            return
        fmt = self.ctx.format_length
        c: CutParams = p.params
        self.name_label.setText(p.name)
        self.badge.setVisible(p.builtin)
        self.description.blockSignals(True)
        self.description.setPlainText(tr(p.description) if p.builtin else p.description)
        self.description.setReadOnly(p.builtin)
        self.description.blockSignals(False)
        self.summary["mode"].setText(tr("Accurate") if c.mode == "accurate" else tr("Fast"))
        self.summary["passes"].setText("   ".join(f"{cp.speed} / {cp.force}" for cp in c.passes))
        self.summary["inset"].setText(fmt(c.inset, 3))
        self.summary["offset"].setText(f"{fmt(c.offset_x)} / {fmt(c.offset_y)}")
        self.summary["border"].setText(f"{fmt(c.border_x)} / {fmt(c.border_y)}")
        self.summary["media"].setText(f"{fmt(c.media_w)} x {fmt(c.media_h)}")
        self.summary["rotate"].setText(f"{c.rotate:g}°" + (", " + tr("mirrored") if c.mirror else ""))
        self.summary["matrix"].setText("  ".join(f"{v:g}" for v in c.matrix))
        for b in (self.rename_button, self.delete_button):
            b.setEnabled(not p.builtin)

    def _description_changed(self) -> None:
        p = self.current()
        if p and not p.builtin:
            p.description = self.description.toPlainText()
            self.ctx.store.save()

    def _use(self) -> None:
        p = self.current()
        if p:
            self.ctx.loadProfileRequested.emit(p.name)
            self.ctx.toast.emit(tr("Profile \"{0}\" loaded").format(p.name))

    def _duplicate(self) -> None:
        p = self.current()
        if not p:
            return
        name = self.ctx.store.unique_name(p.name + " " + tr("copy"))
        desc = tr(p.description) if p.builtin else p.description
        self.ctx.store.put(name, p.params, desc)
        self.ctx.profilesChanged.emit()
        self.refresh(select=name)

    def _rename(self) -> None:
        p = self.current()
        if not p or p.builtin:
            return
        name, ok = QInputDialog.getText(self, tr("Rename"), tr("Profile name:"), text=p.name)
        name = name.strip()
        if not ok or not name or name == p.name:
            return
        old = p.name
        if not self.ctx.store.rename(old, name):
            QMessageBox.warning(self, tr("Rename"), tr("A profile with this name already exists."))
            return
        if self.ctx.settings.active_profile == old:
            self.ctx.settings.active_profile = name
        self.ctx.profilesChanged.emit()
        self.refresh(select=name)

    def _delete(self) -> None:
        p = self.current()
        if not p or p.builtin:
            return
        answer = QMessageBox.question(self, tr("Delete"), tr("Delete the profile \"{0}\"?").format(p.name))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ctx.store.delete(p.name)
        self.ctx.profilesChanged.emit()

    def _export(self) -> None:
        p = self.current()
        if not p:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Export"), f"{p.name}.g2gprofile.json", "JSON (*.json)")
        if path:
            try:
                self.ctx.store.export_file(p.name, path)
            except OSError as exc:
                QMessageBox.critical(self, tr("Export"), str(exc))

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Import"), "", "JSON (*.json)")
        if not path:
            return
        try:
            p = self.ctx.store.import_file(path)
        except (OSError, ValueError):
            QMessageBox.warning(self, tr("Import"), tr("This file is not a Gerber2Graphtec profile."))
            return
        self.ctx.profilesChanged.emit()
        self.refresh(select=p.name)
