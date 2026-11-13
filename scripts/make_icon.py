"""Render the application icon (PNG + ICO) into src/g2g/assets.

Run once after changing the design:  python scripts/make_icon.py
"""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

OUT = Path(__file__).resolve().parent.parent / "src" / "g2g" / "assets"


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 256, size / 256)

    # stencil sheet
    grad = QLinearGradient(0, 0, 256, 256)
    grad.setColorAt(0, QColor("#2ee6bb"))
    grad.setColorAt(1, QColor("#0a8f72"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(QRectF(12, 12, 232, 232), 54, 54)

    # apertures: a QFN-like footprint cut out of the sheet
    hole = QColor("#06231c")
    p.setBrush(hole)
    p.drawRoundedRect(QRectF(98, 98, 60, 60), 8, 8)
    for i in range(4):
        o = 86 + i * 23
        p.drawRoundedRect(QRectF(o, 54, 14, 30), 4, 4)
        p.drawRoundedRect(QRectF(o, 172, 14, 30), 4, 4)
        p.drawRoundedRect(QRectF(54, o, 30, 14), 4, 4)
        p.drawRoundedRect(QRectF(172, o, 30, 14), 4, 4)

    # knife stroke
    pen = QPen(QColor("#ffffff"), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(182, 214), QPointF(214, 182))
    blade = QPainterPath()
    blade.moveTo(170, 226)
    blade.lineTo(182, 196)
    blade.lineTo(200, 214)
    blade.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffffff"))
    p.drawPath(blade)
    p.end()
    return img


def main() -> None:
    app = QGuiApplication([])  # noqa: F841
    OUT.mkdir(parents=True, exist_ok=True)
    render(256).save(str(OUT / "icon.png"))
    render(256).save(str(OUT / "icon.ico"))
    print("written to", OUT)


if __name__ == "__main__":
    main()
