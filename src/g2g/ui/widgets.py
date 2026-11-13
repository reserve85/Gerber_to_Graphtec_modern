"""Small reusable widgets."""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.toolpath import MM_PER_INCH
from . import theme


class _NoWheelMixin:
    """Spin boxes / combos inside scroll areas must not steal the wheel."""

    def wheelEvent(self, event):  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class SpinBox(_NoWheelMixin, QSpinBox):
    def __init__(self, lo: int, hi: int, value: int = 0, parent=None):
        super().__init__(parent)
        self.setRange(lo, hi)
        self.setValue(value)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.lineEdit().setTextMargins(8, 0, 0, 0)


class DoubleSpinBox(_NoWheelMixin, QDoubleSpinBox):
    def __init__(self, lo: float, hi: float, decimals: int = 3, step: float = 1.0, suffix: str = "", parent=None):
        super().__init__(parent)
        self.setDecimals(decimals)
        self.setRange(lo, hi)
        self.setSingleStep(step)
        self.setSuffix(suffix)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.lineEdit().setTextMargins(8, 0, 0, 0)


class ComboBox(_NoWheelMixin, QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


class LengthSpin(DoubleSpinBox):
    """A length input that stores millimetres and displays mm or inch."""

    mmChanged = Signal(float)
    _instances: weakref.WeakSet[LengthSpin] = weakref.WeakSet()
    _unit = "mm"

    def __init__(self, lo_mm: float, hi_mm: float, step_mm: float = 1.0, parent=None):
        super().__init__(0, 1, parent=parent)
        self._lo, self._hi, self._step = lo_mm, hi_mm, step_mm
        self._mm = 0.0
        LengthSpin._instances.add(self)
        self._configure()
        self.valueChanged.connect(self._on_value)

    @classmethod
    def set_unit(cls, unit: str) -> None:
        cls._unit = unit
        for inst in list(cls._instances):
            inst._configure()

    def _factor(self) -> float:
        return MM_PER_INCH if LengthSpin._unit == "inch" else 1.0

    def _configure(self) -> None:
        f = self._factor()
        inch = LengthSpin._unit == "inch"
        self.blockSignals(True)
        self.setDecimals(4 if inch else 3)
        self.setRange(self._lo / f, self._hi / f)
        self.setSingleStep(self._nice_step(self._step / f) if inch else self._step)
        self.setSuffix(" in" if inch else " mm")
        self.setValue(self._mm / f)
        self.blockSignals(False)

    @staticmethod
    def _nice_step(step: float) -> float:
        for nice in (0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0):
            if step <= nice * 1.5:
                return nice
        return 1.0

    def _on_value(self, value: float) -> None:
        self._mm = value * self._factor()
        self.mmChanged.emit(self._mm)

    def mm(self) -> float:
        return self._mm

    def set_mm(self, mm: float) -> None:
        self._mm = max(self._lo, min(self._hi, mm))
        self.blockSignals(True)
        self.setValue(self._mm / self._factor())
        self.blockSignals(False)


class Card(QFrame):
    """Rounded panel with an optional caption and a form grid."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(16, 14, 16, 16)
        self.outer.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(6)
        if title:
            lbl = QLabel(title.upper())
            lbl.setObjectName("cardTitle")
            self.header.addWidget(lbl)
        self.header.addStretch(1)
        self.outer.addLayout(self.header)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(8)
        self.grid.setColumnStretch(1, 1)
        self.outer.addLayout(self.grid)
        self._row = 0

    def add_row(self, label: str, *widgets: QWidget, tip: str = "") -> QLabel:
        lbl = QLabel(label)
        lbl.setObjectName("fieldLabel")
        if tip:
            lbl.setToolTip(tip)
            for w in widgets:
                w.setToolTip(tip)
        self.grid.addWidget(lbl, self._row, 0)
        if len(widgets) == 1:
            self.grid.addWidget(widgets[0], self._row, 1)
        else:
            box = QHBoxLayout()
            box.setSpacing(8)
            for w in widgets:
                box.addWidget(w, 1)
            self.grid.addLayout(box, self._row, 1)
        self._row += 1
        return lbl

    def add_wide(self, widget_or_layout) -> None:
        if isinstance(widget_or_layout, QWidget):
            self.grid.addWidget(widget_or_layout, self._row, 0, 1, 2)
        else:
            self.grid.addLayout(widget_or_layout, self._row, 0, 1, 2)
        self._row += 1


def tool_button(glyph: str, tip: str, checkable: bool = False, role: str = "text") -> QToolButton:
    btn = QToolButton()
    theme.set_glyph(btn, glyph, "muted" if checkable else role, 16)
    btn.setToolTip(tip)
    btn.setCheckable(checkable)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def push_button(text: str, glyph: str = "", primary: bool = False, danger: bool = False) -> QPushButton:
    btn = QPushButton((" " + text) if glyph else text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        btn.setObjectName("primary")
    elif danger:
        btn.setObjectName("danger")
    if glyph:
        theme.set_glyph(btn, glyph, "on_accent" if primary else "text", 15)
    return btn


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


class Toast(QLabel):
    """Transient message floating at the bottom of its parent."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        parent.installEventFilter(self)

    def show_message(self, text: str, msec: int = 3500) -> None:
        self.setText(text)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._timer.start(msec)

    def _place(self) -> None:
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 24)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False


class Page(QWidget):
    """Base class of the pages in the main stack: title + scrollable body."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 20, 24, 20)
        self.root.setSpacing(16)
        self.head = QHBoxLayout()
        self.head.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(title, "pageTitle"))
        if subtitle:
            titles.addWidget(label(subtitle, "pageSubtitle"))
        self.head.addLayout(titles, 1)
        self.root.addLayout(self.head)
