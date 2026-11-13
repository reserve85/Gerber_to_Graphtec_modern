"""Command line front end: gerber in, Graphtec command stream out."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .core import graphtec, output
from .core.gerber import GerberError, load_gerber
from .core.toolpath import MM_PER_INCH, CutParams, CutPass, build_job
from .profiles import ProfileStore


def _pair(text: str) -> tuple[float, float]:
    a, b = (float(v) for v in text.split(","))
    return a, b


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="g2g-cli", description="Cut SMT stencils from Gerber files on Graphtec cutters.")
    ap.add_argument("gerber", help="solder paste Gerber file")
    ap.add_argument("-o", "--output", help="write the command stream to this file")
    ap.add_argument("--printer", help="send to this Windows printer (RAW)")
    ap.add_argument("--list-printers", action="store_true")
    ap.add_argument("--profile", help="start from this profile (default: Standard)")
    ap.add_argument("--inch", action="store_true", help="lengths below are inches instead of mm")
    ap.add_argument("--offset", type=_pair, metavar="X,Y")
    ap.add_argument("--border", type=_pair, metavar="X,Y", help="0,0 disables the border cut")
    ap.add_argument("--media-size", type=_pair, metavar="W,H")
    ap.add_argument("--matrix", metavar="A,B,C,D")
    ap.add_argument("--speed", metavar="S[,S2..]")
    ap.add_argument("--force", metavar="F[,F2..]")
    ap.add_argument("--mode", choices=["accurate", "fast"])
    ap.add_argument("--rotate", type=float, metavar="DEG")
    ap.add_argument("--mirror", action="store_true")
    ap.add_argument("--inset", type=float, help="shrink pads by this amount")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    if args.list_printers:
        print("\n".join(output.list_printers()))
        return 0

    store = ProfileStore()
    profile = store.get(args.profile or "Standard")
    if profile is None:
        ap.error(f"unknown profile {args.profile!r}; available: {', '.join(store.names())}")
    p = CutParams.from_dict(profile.params.to_dict())
    k = MM_PER_INCH if args.inch else 1.0
    if args.offset:
        p.offset_x, p.offset_y = args.offset[0] * k, args.offset[1] * k
    if args.border:
        p.border_x, p.border_y = args.border[0] * k, args.border[1] * k
    if args.media_size:
        p.media_w, p.media_h = args.media_size[0] * k, args.media_size[1] * k
    if args.matrix:
        p.matrix = tuple(float(v) for v in args.matrix.split(","))  # type: ignore[assignment]
    if args.speed or args.force:
        speeds = [int(v) for v in (args.speed or "").split(",") if v] or [c.speed for c in p.passes]
        forces = [int(v) for v in (args.force or "").split(",") if v] or [c.force for c in p.passes]
        p.passes = [CutPass(s, f) for s, f in zip(speeds, forces)]
    if args.mode:
        p.mode = args.mode
    if args.rotate is not None:
        p.rotate = args.rotate
    if args.mirror:
        p.mirror = True
    if args.inset is not None:
        p.inset = args.inset * k

    try:
        gerber = load_gerber(args.gerber)
    except (OSError, GerberError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for w in gerber.warnings:
        print(f"warning: {w}", file=sys.stderr)
    job = build_job(gerber.geometry, p)
    if job.is_empty:
        print("error: no pads found", file=sys.stderr)
        return 1
    if not job.fits_media():
        print("warning: the cut exceeds the media size", file=sys.stderr)
    data = graphtec.encode(job)
    try:
        if args.printer:
            output.send_to_printer(args.printer, data)
        elif args.output:
            output.save_file(args.output, data)
        else:
            sys.stdout.buffer.write(data)
    except output.OutputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
