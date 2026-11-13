"""Interactive preview of the cutting job on the media sheet."""

from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget

from ..core.toolpath import Job
from ..i18n import tr
from . import theme


class PreviewWidget(QWidget):
    """Shows the media, the pads and the cut lines.

    World coordinates are millimetres on the media (X to the right, Y up).
    Wheel zooms around the cursor, dragging pans, double click fits the view.
    """

    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(320, 240)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.job: Job | None = None
        self.show_pads = True
        self.show_cuts = True
        self.progress: int | None = None  # number of lines already cut (simulation)
        self._scale = 2.0  # px per mm
        self._center = QPointF(150, 140)
        self._auto_fit = True
        self._view = "sheet"  # automatic view: "sheet" (whole media) or "job" (cut area)
        self._drag: QPointF | None = None
        self._cursor: QPointF | None = None
        self._pads = QPainterPath()
        self._lines: list[QLineF] = []
        self._normal: list[QLineF] = []
        self._training: list[QLineF] = []
        self._border = QPolygonF()
        self._media = QRectF(0, 0, 304.8, 279.4)
        self._fits = True

    # -- data --------------------------------------------------------------

    def set_job(self, job: Job | None, refit: bool = False) -> None:
        self.job = job
        self._pads = QPainterPath()
        self._lines, self._normal, self._training = [], [], []
        self._border = QPolygonF()
        self._fits = True
        if job is not None:
            dev = job.to_device
            self._media = QRectF(0, 0, job.params.media_w, job.params.media_h)
            self._fits = job.fits_media()
            for poly in job.polygons:
                for ring in (poly.exterior, *poly.interiors):
                    pts = [QPointF(*dev(x, y)) for x, y in ring.coords]
                    self._pads.addPolygon(QPolygonF(pts))
            if job.params.mode == "accurate":
                for (x1, y1, x2, y2), t in zip(job.lines, job.training):
                    ln = QLineF(QPointF(*dev(x1, y1)), QPointF(*dev(x2, y2)))
                    self._lines.append(ln)
                    (self._training if t else self._normal).append(ln)
            else:
                for s in job.strokes:
                    pts = [QPointF(*dev(x, y)) for x, y in s]
                    for a, b in zip(pts, pts[1:] + pts[:1]):
                        self._lines.append(QLineF(a, b))
                self._normal = self._lines
            if job.border_path:
                self._border = QPolygonF([QPointF(*dev(x, y)) for x, y in job.border_path])
        if refit:
            self._view = "job"
            self._auto_fit = True
        if self._auto_fit:
            self._refit()
        self.update()

    def line_count(self) -> int:
        return len(self._lines)

    def set_progress(self, n: int | None) -> None:
        self.progress = n
        self.update()

    # -- view --------------------------------------------------------------

    def _fit_rect(self, rect: QRectF, margin: float = 28) -> None:
        if rect.width() <= 0 or rect.height() <= 0 or self.width() <= 2 * margin:
            return
        self._scale = min((self.width() - 2 * margin) / rect.width(), (self.height() - 2 * margin) / rect.height())
        self._center = rect.center()
        self.update()

    def _refit(self) -> None:
        """Re-apply the current automatic view: the cut area or the whole sheet."""
        rect = QRectF(self._media)
        if self.job is not None and not self.job.is_empty:
            b = self.job.device_bounds()
            cut = QRectF(QPointF(b[0], b[1]), QPointF(b[2], b[3]))
            rect = cut if self._view == "job" else rect.united(cut)
        self._fit_rect(rect, margin=40 if self._view == "job" else 28)

    def fit_sheet(self) -> None:
        self._view = "sheet"
        self._auto_fit = True
        self._refit()

    def fit_job(self) -> None:
        self._view = "job"
        self._auto_fit = True
        self._refit()

    def fit_stencil(self) -> None:
        if self.job is None or self.job.is_empty:
            return self.fit_sheet()
        self._auto_fit = False
        self._view = "job"
        self._fit_rect(self._pads.boundingRect(), margin=60)

    def zoom(self, factor: float, anchor: QPointF | None = None) -> None:
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        before = self.to_world(anchor)
        self._scale = max(0.05, min(4000.0, self._scale * factor))
        after = self.to_world(anchor)
        self._center += before - after
        self._auto_fit = False
        self.update()

    def transform(self) -> QTransform:
        t = QTransform()
        t.translate(self.width() / 2, self.height() / 2)
        t.scale(self._scale, -self._scale)
        t.translate(-self._center.x(), -self._center.y())
        return t

    def to_world(self, pos: QPointF) -> QPointF:
        return QPointF(
            (pos.x() - self.width() / 2) / self._scale + self._center.x(),
            -(pos.y() - self.height() / 2) / self._scale + self._center.y(),
        )

    # -- events ------------------------------------------------------------

    def resizeEvent(self, event):  # noqa: N802
        if self._auto_fit:
            self._refit()

    def wheelEvent(self, event):  # noqa: N802
        self.zoom(1.0015 ** event.angleDelta().y(), event.position())

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._drag = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):  # noqa: N802
        self._cursor = event.position()
        if self._drag is not None:
            d = event.position() - self._drag
            self._drag = event.position()
            self._center -= QPointF(d.x() / self._scale, -d.y() / self._scale)
            self._auto_fit = False
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.fit_job()

    def leaveEvent(self, event):  # noqa: N802
        self._cursor = None
        self.update()

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.fileDropped.emit(url.toLocalFile())
                break

    # -- painting ----------------------------------------------------------

    @staticmethod
    def _pen(color: str, width: float = 1.0, alpha: int = 255, style=Qt.PenStyle.SolidLine) -> QPen:
        c = QColor(color)
        c.setAlpha(alpha)
        pen = QPen(c, width, style)
        pen.setCosmetic(True)
        return pen

    def paintEvent(self, event):  # noqa: N802
        p = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(p.canvas))
        painter.save()
        painter.setTransform(self.transform(), True)

        # media sheet
        painter.setPen(self._pen(p.border if self._fits else p.danger, 1.5))
        painter.setBrush(QColor(p.sheet))
        painter.drawRect(self._media)
        self._paint_grid(painter, p)

        if self.job is not None and not self.job.is_empty:
            if not self._border.isEmpty():
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(self._pen(p.frame, 1.2, 220, Qt.PenStyle.DashLine))
                painter.drawPolygon(self._border)
            if self.show_pads:
                fill = QColor(p.pad)
                fill.setAlpha(150 if self.show_cuts else 235)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(fill))
                painter.drawPath(self._pads)
            if self.show_cuts:
                self._paint_cuts(painter, p)
        painter.restore()

        self._paint_overlay(painter, p)
        painter.end()

    def _paint_grid(self, painter: QPainter, p: theme.Palette) -> None:
        step = 10.0
        if self._scale * step < 7:
            step = 50.0
        if self._scale * step < 7:
            return
        painter.setPen(self._pen(p.grid, 1.0))
        m = self._media
        lines = []
        x = step
        while x < m.width() - 1e-6:
            lines.append(QLineF(x, 0, x, m.height()))
            x += step
        y = step
        while y < m.height() - 1e-6:
            lines.append(QLineF(0, y, m.width(), y))
            y += step
        painter.drawLines(lines)

    def _paint_cuts(self, painter: QPainter, p: theme.Palette) -> None:
        if self.progress is None:
            painter.setPen(self._pen(p.cut, 1.3))
            painter.drawLines(self._normal)
            painter.setPen(self._pen(p.training, 1.6))
            painter.drawLines(self._training)
            return
        n = max(0, min(self.progress, len(self._lines)))
        painter.setPen(self._pen(p.muted, 1.0, 70))
        painter.drawLines(self._lines[n:])
        painter.setPen(self._pen(p.cut, 1.6))
        painter.drawLines(self._lines[:n])
        if n:
            last = self._lines[n - 1]
            painter.setPen(self._pen(p.training, 2.4))
            painter.drawLine(last)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.training))
            r = 4.5 / self._scale
            painter.drawEllipse(last.p2(), r, r)

    def _paint_overlay(self, painter: QPainter, p: theme.Palette) -> None:
        font = QFont(self.font())
        font.setPointSizeF(8.5)
        painter.setFont(font)
        muted = QColor(p.muted)

        # axis hint at the media origin
        t = self.transform()
        o = t.map(QPointF(0, 0))
        painter.setPen(QPen(muted, 1))
        painter.drawLine(o, o + QPointF(34, 0))
        painter.drawLine(o, o + QPointF(0, -34))
        painter.drawText(o + QPointF(38, 4), "X")
        painter.drawText(o + QPointF(-3, -38), "Y")

        # scale bar
        target = 90 / self._scale
        exp = 10 ** math.floor(math.log10(target)) if target > 0 else 1
        nice = next((m * exp for m in (5, 2, 1) if m * exp <= target), exp)
        px = nice * self._scale
        x0, y0 = 16, self.height() - 16
        painter.setPen(QPen(QColor(p.text), 1.5))
        painter.drawLine(QPointF(x0, y0), QPointF(x0 + px, y0))
        painter.drawLine(QPointF(x0, y0 - 4), QPointF(x0, y0))
        painter.drawLine(QPointF(x0 + px, y0 - 4), QPointF(x0 + px, y0))
        painter.setPen(muted)
        painter.drawText(QPointF(x0, y0 - 8), f"{nice:g} mm")

        if self._cursor is not None:
            w = self.to_world(self._cursor)
            text = f"X {w.x():.2f}   Y {w.y():.2f} mm"
            rect = QRectF(self.width() - 220, self.height() - 30, 204, 18)
            painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

        if self.job is None or self.job.is_empty:
            big = QFont(self.font())
            big.setPointSizeF(13)
            big.setWeight(QFont.Weight.DemiBold)
            painter.setFont(big)
            painter.setPen(QColor(p.text))
            box = QRectF(0, self.height() / 2 - 40, self.width(), 30)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, tr("Drop a Gerber file here"))
            painter.setFont(font)
            painter.setPen(muted)
            box.translate(0, 28)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, tr("Solder paste layer (*.gbr, *.gtp, *.gbp ...) - or use \"Open\""))
