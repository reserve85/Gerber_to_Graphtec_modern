"""Encode a cutting job as a Graphtec (GP-GL) command stream.

Works for Silhouette Cameo / Portrait class machines.  Protocol knowledge comes
from robocut and graphtecprint via the original gerber2graphtec.
"""

from __future__ import annotations

import math

from .toolpath import MM_PER_INCH, Job, Point

UNITS_PER_MM = 20.0  # 508 device units per inch
ETX = "\x03"
# Anti-backlash: start each single cut slightly early and end slightly late.
BACKLASH = 0.001 * MM_PER_INCH


class Encoder:
    def __init__(self, job: Job):
        self.job = job
        self.out: list[str] = []

    def emit(self, s: str) -> None:
        self.out.append(s)

    def xy(self, x: float, y: float) -> str:
        dx, dy = self.job.to_device(x, y)
        return "%.3f,%.3f" % (dx * UNITS_PER_MM, dy * UNITS_PER_MM)

    def move(self, x: float, y: float) -> None:
        self.emit("M" + self.xy(x, y) + ETX)

    def draw(self, x: float, y: float) -> None:
        self.emit("D" + self.xy(x, y) + ETX)

    def closed_path(self, pts: list[Point]) -> None:
        if len(pts) < 3:
            return
        self.move(*pts[0])
        for p in pts[1:]:
            self.draw(*p)
        self.draw(*pts[0])

    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        theta = math.atan2(y2 - y1, x2 - x1)
        ex, ey = BACKLASH * math.cos(theta), BACKLASH * math.sin(theta)
        self.move(x1 - ex, y1 - ey)
        self.draw(x2 + ex, y2 + ey)

    def start(self) -> None:
        p = self.job.params
        width = int(round(UNITS_PER_MM * p.media_w))
        height = int(round(UNITS_PER_MM * p.media_h))
        margin_top, margin_right = 500, 320  # device units
        e = self.emit
        e("\x1b\x04")  # initialize plotter
        e("\x1b\x05")  # status request
        e("TT" + ETX)  # home the cutter
        e("FG" + ETX)  # query version
        e("FW100" + ETX)  # paper type
        e("FC18" + ETX)
        e("FY0" + ETX)  # track enhancing off
        e("FN1" + ETX)  # orientation
        e("FE0" + ETX)
        e("TB71" + ETX)
        e("FA" + ETX)  # begin page definition
        e("FU%d,%d" % (height - margin_top, width - margin_right) + ETX)
        e("FM1" + ETX)
        e("TB50,1" + ETX)
        e("FO%d" % (height - margin_top) + ETX)
        e("&100,100,100,\\0,0,")
        e("Z%d,%d,L0," % (width, height))

    def end(self) -> None:
        self.emit("&1,1,1,TB50,0" + ETX)
        self.emit("FO0" + ETX)  # feed the page out
        self.emit("H,")

    def encode(self) -> bytes:
        job = self.job
        self.start()
        for cp in job.params.passes:
            self.emit("!%d" % cp.speed + ETX)
            self.emit("FX%d,0" % cp.force + ETX)
            if job.params.mode == "accurate":
                for ln in job.lines:
                    self.line(*ln)
            else:
                for s in job.strokes:
                    self.closed_path(s)
            if job.border_path:
                self.closed_path(job.border_path)
        self.end()
        return "".join(self.out).encode("latin-1")


def encode(job: Job) -> bytes:
    return Encoder(job).encode()
