"""The main work page: load a Gerber, tune parameters, preview, cut."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import graphtec, output
from ..core.gerber import GerberError, GerberResult, load_gerber
from ..core.toolpath import MM_PER_INCH, CutParams, CutPass, Job, build_job
from ..i18n import tr
from .context import Context
from .preview import PreviewWidget
from .theme import Glyph
from .widgets import Card, ComboBox, DoubleSpinBox, LengthSpin, SpinBox, label, push_button, tool_button

GERBER_FILTER = "Gerber (*.gbr *.ger *.gtp *.gbp *.gp* *.pho *.art *.g*);;"

MEDIA_PRESETS: list[tuple[str, float, float]] = [
    ("12 x 11 in", 12 * MM_PER_INCH, 11 * MM_PER_INCH),
    ("12 x 12 in", 12 * MM_PER_INCH, 12 * MM_PER_INCH),
    ("Letter 8.5 x 11 in", 8.5 * MM_PER_INCH, 11 * MM_PER_INCH),
    ("A4 210 x 297 mm", 210.0, 297.0),
]

MAX_PASSES = 6


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {sec:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


class PassEditor(QWidget):
    """Editable list of cutting passes (speed / force)."""

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._rows: list[tuple[SpinBox, SpinBox]] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(1, 1)
        self._grid.setColumnStretch(2, 1)
        self._layout.addLayout(self._grid)
        self.add_button = push_button(tr("Add pass"), Glyph.ADD)
        self.add_button.clicked.connect(self._add)
        self._layout.addWidget(self.add_button)

    def passes(self) -> list[CutPass]:
        return [CutPass(s.value(), f.value()) for s, f in self._rows]

    def set_passes(self, passes: list[CutPass]) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows = []
        self._grid.addWidget(label("#", "fieldLabel"), 0, 0)
        self._grid.addWidget(label(tr("Speed (1-10)"), "fieldLabel"), 0, 1)
        self._grid.addWidget(label(tr("Force (1-33)"), "fieldLabel"), 0, 2)
        for i, cp in enumerate(passes[:MAX_PASSES]):
            speed = SpinBox(1, 10, max(1, min(10, cp.speed)))
            force = SpinBox(1, 33, max(1, min(33, cp.force)))
            speed.valueChanged.connect(self._on_change)
            force.valueChanged.connect(self._on_change)
            remove = tool_button(Glyph.CLOSE, tr("Remove this pass"))
            remove.clicked.connect(lambda _=False, idx=i: self._remove(idx))
            remove.setEnabled(len(passes) > 1)
            self._grid.addWidget(label(str(i + 1), "fieldLabel"), i + 1, 0)
            self._grid.addWidget(speed, i + 1, 1)
            self._grid.addWidget(force, i + 1, 2)
            self._grid.addWidget(remove, i + 1, 3)
            self._rows.append((speed, force))
        self.add_button.setEnabled(len(self._rows) < MAX_PASSES)

    def _add(self) -> None:
        passes = self.passes()
        last = passes[-1] if passes else CutPass()
        self.set_passes(passes + [CutPass(last.speed, last.force)])
        self._on_change()

    def _remove(self, idx: int) -> None:
        passes = self.passes()
        if len(passes) > 1:
            del passes[idx]
            self.set_passes(passes)
            self._on_change()


class JobPage(QWidget):
    def __init__(self, ctx: Context, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.gerber: GerberResult | None = None
        self.gerber_path: str = ""
        self.job: Job | None = None
        self._loading = False
        session = dict(ctx.settings.session_params)

        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(120)
        self._rebuild_timer.timeout.connect(self.rebuild)

        self._sim_timer = QTimer(self)
        self._sim_timer.setInterval(30)
        self._sim_timer.timeout.connect(self._sim_tick)

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 16, 12, 16)
        root.setSpacing(16)
        root.addLayout(self._build_left(), 1)
        root.addWidget(self._build_panel())

        ctx.profilesChanged.connect(self._refresh_profiles)
        ctx.unitsChanged.connect(self._update_stats)
        ctx.themeChanged.connect(self.preview.update)
        ctx.loadProfileRequested.connect(self.apply_profile)

        self._refresh_profiles()
        if session:
            self.set_params(CutParams.from_dict(session))
        else:
            self.apply_profile(ctx.settings.active_profile)
        self.rebuild()

    # ------------------------------------------------------------------ UI

    def _build_left(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        names = QVBoxLayout()
        names.setSpacing(1)
        self.file_label = label(tr("No file loaded"), "fileName")
        self.file_sub = label(tr("Open the solder paste layer of your board"), "muted")
        names.addWidget(self.file_label)
        names.addWidget(self.file_sub)
        head.addLayout(names, 1)

        self.open_button = push_button(tr("Open"), Glyph.OPEN)
        self.open_button.clicked.connect(self.open_dialog)
        self.recent_button = tool_button(Glyph.FILE, tr("Recent files"))
        self.recent_button.clicked.connect(self._show_recent)
        self.export_button = push_button(tr("Export"), Glyph.SAVE)
        self.export_button.setToolTip(tr("Save the Graphtec command file"))
        self.export_button.clicked.connect(self.export_file)
        self.send_button = push_button(tr("Send to cutter"), Glyph.SEND, primary=True)
        self.send_button.clicked.connect(self.send)
        for w in (self.open_button, self.recent_button, self.export_button, self.send_button):
            head.addWidget(w)
        col.addLayout(head)

        frame = QFrame()
        frame.setObjectName("previewFrame")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(6, 6, 6, 6)
        fl.setSpacing(4)

        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.preview = PreviewWidget()
        self.preview.fileDropped.connect(self.load_file)
        self.preview.show_pads = self.ctx.settings.show_pads
        self.preview.show_cuts = self.ctx.settings.show_cuts
        self.pads_toggle = QCheckBox(tr("Pads"))
        self.pads_toggle.setChecked(self.preview.show_pads)
        self.pads_toggle.toggled.connect(self._toggle_layers)
        self.cuts_toggle = QCheckBox(tr("Cut lines"))
        self.cuts_toggle.setChecked(self.preview.show_cuts)
        self.cuts_toggle.toggled.connect(self._toggle_layers)
        bar.addSpacing(8)
        bar.addWidget(self.pads_toggle)
        bar.addSpacing(12)
        bar.addWidget(self.cuts_toggle)
        bar.addStretch(1)
        for glyph, tip, fn in (
            (Glyph.ZOOM_OUT, tr("Zoom out"), lambda: self.preview.zoom(1 / 1.4)),
            (Glyph.ZOOM_IN, tr("Zoom in"), lambda: self.preview.zoom(1.4)),
            (Glyph.ZOOM, tr("Zoom to stencil"), self.preview.fit_stencil),
            (Glyph.FIT, tr("Show whole sheet"), self.preview.fit_sheet),
        ):
            b = tool_button(glyph, tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        fl.addLayout(bar)
        fl.addWidget(self.preview, 1)

        sim = QHBoxLayout()
        sim.setSpacing(8)
        self.play_button = tool_button(Glyph.PLAY, tr("Simulate the cutting order"))
        self.play_button.clicked.connect(self._toggle_play)
        self.sim_slider = QSlider(Qt.Orientation.Horizontal)
        self.sim_slider.valueChanged.connect(self._sim_changed)
        self.sim_label = label("", "muted")
        self.sim_label.setMinimumWidth(110)
        self.sim_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sim.addWidget(self.play_button)
        sim.addWidget(self.sim_slider, 1)
        sim.addWidget(self.sim_label)
        sim.addSpacing(6)
        fl.addLayout(sim)
        col.addWidget(frame, 1)

        stat_bar = QFrame()
        stat_bar.setObjectName("statBar")
        sl = QHBoxLayout(stat_bar)
        sl.setContentsMargins(18, 10, 14, 10)
        sl.setSpacing(28)
        self.stats: dict[str, object] = {}
        for key, caption in (
            ("pads", tr("Pads")),
            ("size", tr("Stencil size")),
            ("lifts", tr("Knife strokes")),
            ("length", tr("Cut length")),
            ("time", tr("Duration (est.)")),
        ):
            box = QVBoxLayout()
            box.setSpacing(0)
            value = label("-", "statValue")
            box.addWidget(value)
            box.addWidget(label(caption, "statLabel"))
            sl.addLayout(box)
            self.stats[key] = value
        sl.addStretch(1)
        self.chip = label("", "okChip")
        self.chip.hide()
        sl.addWidget(self.chip)
        col.addWidget(stat_bar)
        return col

    def _build_panel(self) -> QScrollArea:
        changed = self._params_changed
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 14, 0)
        v.setSpacing(12)

        # profile
        card = Card(tr("Profile"))
        self.dirty_label = label("", "muted")
        card.header.addWidget(self.dirty_label)
        self.profile_combo = ComboBox()
        self.profile_combo.activated.connect(lambda _: self.apply_profile(self.profile_combo.currentText()))
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.profile_combo, 1)
        self.save_profile_button = tool_button(Glyph.SAVE, tr("Save changes to this profile"))
        self.save_profile_button.clicked.connect(self.save_profile)
        save_as = tool_button(Glyph.SAVE_AS, tr("Save as new profile"))
        save_as.clicked.connect(self.save_profile_as)
        self.revert_button = tool_button(Glyph.UNDO, tr("Discard changes"))
        self.revert_button.clicked.connect(lambda: self.apply_profile(self.ctx.settings.active_profile))
        for b in (self.save_profile_button, save_as, self.revert_button):
            row.addWidget(b)
        card.add_wide(row)
        v.addWidget(card)

        # cutting
        card = Card(tr("Cutting"))
        self.mode_group = QButtonGroup(self)
        seg = QHBoxLayout()
        seg.setSpacing(6)
        for i, (text, tip) in enumerate(
            (
                (tr("Accurate"), tr("Every edge is cut as a single line, sorted by knife angle. Best for fine pitch.")),
                (tr("Fast"), tr("Pads are cut as closed outlines. Quicker, less precise corners.")),
            )
        ):
            b = QToolButton()
            b.setObjectName("segment")
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.mode_group.addButton(b, i)
            seg.addWidget(b, 1)
        self.mode_group.idClicked.connect(changed)
        card.add_wide(seg)
        self.pass_editor = PassEditor(changed)
        card.add_wide(self.pass_editor)
        self.inset = LengthSpin(0.0, 0.5, 0.005)
        self.inset.mmChanged.connect(changed)
        card.add_row(
            tr("Pad shrink"),
            self.inset,
            tip=tr("Shrinks every pad on all sides. The knife widens openings by roughly 0.05 mm (2 mil) in thin Mylar."),
        )
        v.addWidget(card)

        # placement
        card = Card(tr("Placement"))
        self.offset_x = LengthSpin(0, 1000, 1)
        self.offset_y = LengthSpin(0, 1000, 1)
        self.border_x = LengthSpin(0, 200, 1)
        self.border_y = LengthSpin(0, 200, 1)
        for w in (self.offset_x, self.offset_y, self.border_x, self.border_y):
            w.mmChanged.connect(changed)
        card.add_row(tr("Offset X / Y"), self.offset_x, self.offset_y, tip=tr("Position of the stencil on the media."))
        card.add_row(
            tr("Border X / Y"),
            self.border_x,
            self.border_y,
            tip=tr("Frame cut around the stencil (blue, dashed). 0 / 0 disables the frame cut."),
        )
        self.rotate = DoubleSpinBox(-360, 360, 1, 90, " °")
        self.rotate.valueChanged.connect(changed)
        rot90 = tool_button(Glyph.ROTATE, tr("Rotate by 90 degrees"))
        rot90.clicked.connect(lambda: self.rotate.setValue((self.rotate.value() + 90) % 360))
        rrow = QHBoxLayout()
        rrow.setSpacing(4)
        rrow.addWidget(self.rotate, 1)
        rrow.addWidget(rot90)
        holder = QWidget()
        holder.setLayout(rrow)
        rrow.setContentsMargins(0, 0, 0, 0)
        card.add_row(tr("Rotation"), holder)
        self.mirror = QCheckBox(tr("Mirror horizontally"))
        self.mirror.toggled.connect(changed)
        card.add_wide(self.mirror)
        v.addWidget(card)

        # media
        card = Card(tr("Media"))
        self.media_combo = ComboBox()
        for name, _, _ in MEDIA_PRESETS:
            self.media_combo.addItem(name)
        self.media_combo.addItem(tr("Custom"))
        self.media_combo.activated.connect(self._media_preset)
        card.add_row(tr("Format"), self.media_combo)
        self.media_w = LengthSpin(20, 3000, 1)
        self.media_h = LengthSpin(20, 3000, 1)
        self.media_w.mmChanged.connect(changed)
        self.media_h.mmChanged.connect(changed)
        card.add_row(tr("Size X / Y"), self.media_w, self.media_h)
        v.addWidget(card)

        # calibration
        card = Card(tr("Calibration"))
        reset = tool_button(Glyph.UNDO, tr("Reset to identity"))
        reset.clicked.connect(lambda: (self._set_matrix((1, 0, 0, 1)), changed()))
        card.header.addWidget(reset)
        self.matrix: list[DoubleSpinBox] = []
        grid = QGridLayout()
        grid.setSpacing(8)
        for i in range(4):
            sp = DoubleSpinBox(-2, 2, 5, 0.0005)
            sp.valueChanged.connect(changed)
            self.matrix.append(sp)
            grid.addWidget(sp, i // 2, i % 2)
        card.add_wide(grid)
        hint = label(
            tr("Linear correction matrix [a b; c d] for scale and skew of your machine. Leave at 1 0 / 0 1 unless measured."),
            "muted",
            wrap=True,
        )
        card.add_wide(hint)
        v.addWidget(card)

        # statistics
        card = Card(tr("Statistics"))
        self.detail: dict[str, object] = {}
        for key, caption, tip in (
            ("pads", tr("Pads"), ""),
            ("area", tr("Open area"), ""),
            ("smallest", tr("Smallest opening"), tr("Narrowest pad dimension - an indicator of how demanding the stencil is.")),
            ("passes", tr("Passes"), ""),
            ("lifts", tr("Knife strokes"), tr("How often the knife is lowered and raised (per pass / total).")),
            ("segments", tr("Straight cuts"), tr("Number of straight cut segments per pass.")),
            ("groups", tr("Knife angles"), tr("Angle groups, each started with a training cut outside the stencil.")),
            ("cut", tr("Cut length"), tr("Distance with the knife down (per pass / total).")),
            ("travel", tr("Travel"), tr("Distance with the knife lifted between cuts (per pass / total).")),
            (
                "time",
                tr("Duration (est.)"),
                tr("Rough estimate: speed unit = 10 mm/s, travel 100 mm/s, 0.15 s per knife stroke. Real machines differ."),
            ),
            ("data", tr("Job data"), tr("Size of the command stream sent to the cutter.")),
        ):
            value = label("-")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            card.add_row(caption, value, tip=tip)
            self.detail[key] = value
        v.addWidget(card)
        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        scroll.setFixedWidth(396)
        return scroll

    # ------------------------------------------------------------- params

    def _set_matrix(self, m) -> None:
        for sp, value in zip(self.matrix, m):
            sp.blockSignals(True)
            sp.setValue(value)
            sp.blockSignals(False)

    def params(self) -> CutParams:
        return CutParams(
            offset_x=self.offset_x.mm(),
            offset_y=self.offset_y.mm(),
            border_x=self.border_x.mm(),
            border_y=self.border_y.mm(),
            matrix=tuple(round(sp.value(), 6) for sp in self.matrix),  # type: ignore[arg-type]
            passes=self.pass_editor.passes(),
            mode="fast" if self.mode_group.checkedId() == 1 else "accurate",
            media_w=self.media_w.mm(),
            media_h=self.media_h.mm(),
            rotate=self.rotate.value(),
            mirror=self.mirror.isChecked(),
            inset=self.inset.mm(),
        )

    def set_params(self, p: CutParams) -> None:
        self._loading = True
        try:
            self.offset_x.set_mm(p.offset_x)
            self.offset_y.set_mm(p.offset_y)
            self.border_x.set_mm(p.border_x)
            self.border_y.set_mm(p.border_y)
            self._set_matrix(p.matrix)
            self.pass_editor.set_passes(p.passes)
            self.mode_group.button(1 if p.mode == "fast" else 0).setChecked(True)
            self.media_w.set_mm(p.media_w)
            self.media_h.set_mm(p.media_h)
            self.rotate.setValue(p.rotate)
            self.mirror.setChecked(p.mirror)
            self.inset.set_mm(p.inset)
        finally:
            self._loading = False
        self._sync_media_combo()
        self._params_changed()

    def _params_changed(self, *_) -> None:
        if self._loading:
            return
        self._sync_media_combo()
        self._update_dirty()
        self._rebuild_timer.start()

    def _sync_media_combo(self) -> None:
        w, h = self.media_w.mm(), self.media_h.mm()
        idx = len(MEDIA_PRESETS)
        for i, (_, pw, ph) in enumerate(MEDIA_PRESETS):
            if abs(pw - w) < 0.01 and abs(ph - h) < 0.01:
                idx = i
        self.media_combo.setCurrentIndex(idx)

    def _media_preset(self, idx: int) -> None:
        if idx < len(MEDIA_PRESETS):
            _, w, h = MEDIA_PRESETS[idx]
            self.media_w.set_mm(w)
            self.media_h.set_mm(h)
            self._params_changed()

    # ------------------------------------------------------------ profiles

    def _refresh_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.ctx.store.all():
            self.profile_combo.addItem(p.name)
        if not self.ctx.store.get(self.ctx.settings.active_profile):
            self.ctx.settings.active_profile = "Standard"
        self.profile_combo.setCurrentText(self.ctx.store.get(self.ctx.settings.active_profile).name)
        self.profile_combo.blockSignals(False)
        if hasattr(self, "inset"):
            self._update_dirty()

    def apply_profile(self, name: str) -> None:
        profile = self.ctx.store.get(name) or self.ctx.store.get("Standard")
        self.ctx.settings.active_profile = profile.name
        self.profile_combo.setCurrentText(profile.name)
        self.set_params(CutParams.from_dict(profile.params.to_dict()))

    def _update_dirty(self) -> None:
        profile = self.ctx.store.get(self.ctx.settings.active_profile)
        dirty = profile is not None and self.params() != profile.params
        self.dirty_label.setText(tr("modified") if dirty else "")
        self.revert_button.setEnabled(dirty)
        self.save_profile_button.setEnabled(dirty and profile is not None and not profile.builtin)
        self.ctx.settings.session_params = self.params().to_dict()

    def save_profile(self) -> None:
        profile = self.ctx.store.get(self.ctx.settings.active_profile)
        if profile is None or profile.builtin:
            return self.save_profile_as()
        self.ctx.store.put(profile.name, self.params())
        self.ctx.profilesChanged.emit()
        self.ctx.toast.emit(tr("Profile \"{0}\" saved").format(profile.name))

    def save_profile_as(self) -> None:
        suggestion = self.ctx.store.unique_name(tr("My profile"))
        name, ok = QInputDialog.getText(self, tr("Save as new profile"), tr("Profile name:"), text=suggestion)
        name = name.strip()
        if not ok or not name:
            return
        existing = self.ctx.store.get(name)
        if existing and existing.builtin:
            QMessageBox.warning(self, tr("Save as new profile"), tr("Built-in profiles cannot be overwritten. Choose another name."))
            return
        if existing:
            answer = QMessageBox.question(self, tr("Save as new profile"), tr("Overwrite the profile \"{0}\"?").format(name))
            if answer != QMessageBox.StandardButton.Yes:
                return
        profile = self.ctx.store.put(name, self.params())
        self.ctx.settings.active_profile = profile.name
        self.ctx.profilesChanged.emit()
        self.ctx.toast.emit(tr("Profile \"{0}\" saved").format(profile.name))

    # ---------------------------------------------------------------- file

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Open Gerber file"), self.ctx.settings.last_dir, GERBER_FILTER + tr("All files") + " (*)"
        )
        if path:
            self.load_file(path)

    def _show_recent(self) -> None:
        menu = QMenu(self)
        files = [f for f in self.ctx.settings.recent_files if Path(f).exists()]
        if not files:
            menu.addAction(tr("No recent files")).setEnabled(False)
        for f in files:
            menu.addAction(Path(f).name, lambda f=f: self.load_file(f)).setToolTip(f)
        menu.setToolTipsVisible(True)
        menu.exec(self.recent_button.mapToGlobal(self.recent_button.rect().bottomLeft()))

    def load_file(self, path: str) -> bool:
        try:
            result = load_gerber(path, self.ctx.settings.arc_tolerance)
        except (OSError, GerberError) as exc:
            QMessageBox.critical(self, tr("Open Gerber file"), tr("The file could not be read:") + f"\n\n{exc}")
            return False
        if not result.polygons:
            QMessageBox.warning(self, tr("Open Gerber file"), tr("The file contains no pads. Is this the solder paste layer?"))
            return False
        self.gerber, self.gerber_path = result, path
        self.ctx.settings.add_recent(path)
        self.file_label.setText(Path(path).name)
        sub = str(Path(path).parent)
        if result.warnings:
            sub = tr("{0} import warning(s) - hover for details").format(len(result.warnings))
            self.file_sub.setToolTip("\n".join(tr(w) for w in result.warnings))
        else:
            self.file_sub.setToolTip(path)
        self.file_sub.setText(sub)
        self.rebuild(refit=True)
        return True

    def reload(self) -> None:
        """Re-read the current file (e.g. after the arc tolerance changed)."""
        if self.gerber_path and Path(self.gerber_path).exists():
            self.load_file(self.gerber_path)

    # ----------------------------------------------------------------- job

    def rebuild(self, refit: bool = False) -> None:
        self._rebuild_timer.stop()
        self._stop_sim()
        geometry = self.gerber.geometry if self.gerber else None
        self.job = build_job(geometry, self.params())
        self.preview.set_job(self.job, refit=refit)
        n = self.preview.line_count()
        self.sim_slider.blockSignals(True)
        self.sim_slider.setRange(0, max(n, 1))
        self.sim_slider.setValue(max(n, 1))
        self.sim_slider.blockSignals(False)
        self.sim_slider.setEnabled(n > 0)
        self.play_button.setEnabled(n > 0)
        self.preview.set_progress(None)
        self._update_stats()

    def _update_stats(self) -> None:
        job = self.job
        ready = job is not None and not job.is_empty
        self.export_button.setEnabled(ready)
        self.send_button.setEnabled(ready)
        self.sim_label.setText("")
        if not ready:
            for value in (*self.stats.values(), *self.detail.values()):
                value.setText("-")
            if self.gerber is not None:
                self._chip(tr("Nothing left to cut - reduce the pad shrink"), ok=False)
            else:
                self.chip.hide()
            return
        fmt = self.ctx.format_length
        st = job.stats()
        inch = self.ctx.settings.units == "inch"

        def dist(mm: float) -> str:  # long distances: metres or inches
            return f"{mm / 25.4:,.1f} in" if inch else (f"{mm / 1000:.2f} m" if mm >= 1000 else f"{mm:.0f} mm")

        def both(a: str, b: str) -> str:
            return a if st.passes == 1 else f"{a}  /  {b}"

        self.stats["pads"].setText(str(st.pads))
        self.stats["size"].setText(f"{fmt(st.width)} x {fmt(st.height)}")
        self.stats["lifts"].setText(f"{st.lifts_total:,}".replace(",", " "))
        self.stats["length"].setText(dist(st.cut_total))
        self.stats["time"].setText("≈ " + format_duration(st.seconds))

        d = self.detail
        d["pads"].setText(str(st.pads))
        area = f"{st.pad_area / 645.16:.3f} in²" if inch else f"{st.pad_area:.1f} mm²"
        d["area"].setText(area)
        d["smallest"].setText(fmt(st.smallest_opening, 4 if inch else 3))
        d["passes"].setText(str(st.passes))
        d["lifts"].setText(both(str(st.lifts_per_pass), str(st.lifts_total)))
        d["segments"].setText(str(st.segments_per_pass))
        d["groups"].setText(str(st.angle_groups) if job.params.mode == "accurate" else "-")
        d["cut"].setText(both(dist(st.cut_per_pass), dist(st.cut_total)))
        d["travel"].setText(both(dist(st.travel_per_pass), dist(st.travel_total)))
        d["time"].setText("≈ " + format_duration(st.seconds))
        d["data"].setText(f"{len(graphtec.encode(job)) / 1024:.0f} kB")
        if job.fits_media():
            self._chip(tr("Fits on the media"), ok=True)
        else:
            self._chip(tr("Exceeds the media - adjust offset or media size"), ok=False)

    def _chip(self, text: str, ok: bool) -> None:
        self.chip.setObjectName("okChip" if ok else "warnChip")
        self.chip.setText(text)
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)
        self.chip.show()

    def _toggle_layers(self) -> None:
        self.preview.show_pads = self.ctx.settings.show_pads = self.pads_toggle.isChecked()
        self.preview.show_cuts = self.ctx.settings.show_cuts = self.cuts_toggle.isChecked()
        self.preview.update()

    # ---------------------------------------------------------- simulation

    def _sim_changed(self, value: int) -> None:
        n = self.preview.line_count()
        if value >= n:
            self.preview.set_progress(None)
            self.sim_label.setText("")
        else:
            self.preview.set_progress(value)
            self.sim_label.setText(f"{value} / {n}")

    def _toggle_play(self) -> None:
        if self._sim_timer.isActive():
            return self._stop_sim()
        if self.sim_slider.value() >= self.sim_slider.maximum():
            self.sim_slider.setValue(0)
        if not self.cuts_toggle.isChecked():
            self.cuts_toggle.setChecked(True)
        from . import theme

        theme.set_glyph(self.play_button, Glyph.PAUSE, "text", 16)
        self._sim_timer.start()

    def _stop_sim(self) -> None:
        if self._sim_timer.isActive():
            self._sim_timer.stop()
        from . import theme

        theme.set_glyph(self.play_button, Glyph.PLAY, "text", 16)

    def _sim_tick(self) -> None:
        n = self.sim_slider.maximum()
        value = self.sim_slider.value() + max(1, n // 400)
        self.sim_slider.setValue(min(value, n))
        if value >= n:
            self._stop_sim()

    # -------------------------------------------------------------- output

    def _encoded(self) -> bytes | None:
        self.rebuild()
        if self.job is None or self.job.is_empty:
            return None
        if not self.job.fits_media():
            answer = QMessageBox.warning(
                self,
                tr("Exceeds the media"),
                tr("The cut is larger than the configured media. Continue anyway?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
        return graphtec.encode(self.job)

    def export_file(self) -> None:
        data = self._encoded()
        if data is None:
            return
        base = Path(self.gerber_path).with_suffix(".graphtec") if self.gerber_path else Path("stencil.graphtec")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export"), str(base), tr("Graphtec command file") + " (*.graphtec *.txt);;" + tr("All files") + " (*)"
        )
        if not path:
            return
        try:
            output.save_file(path, data)
        except output.OutputError as exc:
            QMessageBox.critical(self, tr("Export"), str(exc))
            return
        self.ctx.toast.emit(tr("Saved {0}").format(Path(path).name))

    def send(self) -> None:
        s = self.ctx.settings
        target = s.printer if s.output_mode == "printer" else s.device_path
        if not target:
            QMessageBox.information(
                self,
                tr("Send to cutter"),
                tr("No cutter is configured yet. Choose your cutter under Settings > Cutter output."),
            )
            return
        data = self._encoded()
        if data is None:
            return
        if s.confirm_send:
            p = self.job.params
            passes = ", ".join(f"{cp.speed}/{cp.force}" for cp in p.passes)
            box = QMessageBox(self)
            box.setWindowTitle(tr("Send to cutter"))
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(tr("Start cutting on \"{0}\"?").format(target))
            box.setInformativeText(
                tr("{0} pads, {1} pass(es) (speed/force: {2}).\nMake sure the media is loaded and the blade is set.").format(
                    len(self.job.strokes), len(p.passes), passes
                )
            )
            start = box.addButton(tr("Start cutting"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is not start:
                return
        try:
            if s.output_mode == "printer":
                output.send_to_printer(target, data, f"Stencil {Path(self.gerber_path).name}")
            else:
                output.send_to_path(target, data)
        except output.OutputError as exc:
            QMessageBox.critical(self, tr("Send to cutter"), tr("Sending failed:") + f"\n\n{exc}")
            return
        self.ctx.toast.emit(tr("Job sent to {0}").format(target))
