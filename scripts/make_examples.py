"""Generate the synthetic example Gerber files in examples/.

They are written by this script (not exported from a CAD program) and each
exercises a different Gerber dialect:

  kicad_style_qfn32.gbr     mm, 4.6 format, X2 attributes, RoundRect aperture macros
  bga100_0.8mm.gbr          mm, round flashes on a 0.8 mm grid, fiducials
  arcs_regions_polarity.gbr mm, regions with arcs, arc draws, obround / polygon
                            apertures, rotated macro, clear polarity
  legacy_inch_soic.gbr      inch, 2.3 format with trailing zero omission, G70/G90,
                            G54 and modal operation codes

Run:  python scripts/make_examples.py
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "examples"


# ---------------------------------------------------------------- KiCad style

ROUNDRECT = """%AMRoundRect*
0 Rectangle with rounded corners*
0 $1 Rounding radius*
0 $2 $3 $4 $5 $6 $7 $8 $9 X,Y pos of 4 corners*
0 Add a 4 corners polygon primitive as box body*
4,1,4,$2,$3,$4,$5,$6,$7,$8,$9,$2,$3,0*
0 Add four circle primitives for the rounded corners*
1,1,$1+$1,$2,$3*
1,1,$1+$1,$4,$5*
1,1,$1+$1,$6,$7*
1,1,$1+$1,$8,$9*
0 Add four rect primitives between the rounded corners*
20,1,$1+$1,$2,$3,$4,$5,0*
20,1,$1+$1,$4,$5,$6,$7,0*
20,1,$1+$1,$6,$7,$8,$9,0*
20,1,$1+$1,$8,$9,$2,$3,0*%"""


def roundrect(num: int, w: float, h: float, r: float) -> str:
    x, y = w / 2 - r, h / 2 - r
    pts = [(-x, y), (x, y), (x, -y), (-x, -y)]
    args = "X".join(f"{v:.6f}" for p in pts for v in p)
    return f"%ADD{num}RoundRect,{r:.6f}X{args}X0*%"


def c46(v: float) -> str:
    return str(int(round(v * 1e6)))


def kicad_style() -> str:
    out = [
        "%TF.GenerationSoftware,Gerber2Graphtec,make_examples.py,1*%",
        "%TF.FileFunction,Paste,Top*%",
        "%TF.FilePolarity,Positive*%",
        "%FSLAX46Y46*%",
        "G04 Synthetic example: QFN-32 0.5 mm, SOIC-8, SOT-23, 0402 and 0603 parts*",
        "%MOMM*%",
        "%LPD*%",
        "G01*",
        "G04 APERTURE LIST*",
        ROUNDRECT,
        roundrect(10, 0.75, 0.25, 0.0625),  # QFN pad, horizontal
        roundrect(11, 0.25, 0.75, 0.0625),  # QFN pad, vertical
        roundrect(12, 1.30, 1.30, 0.20),  # exposed pad window pane
        roundrect(13, 0.50, 0.60, 0.125),  # 0402
        roundrect(14, 0.80, 0.95, 0.20),  # 0603
        roundrect(15, 1.55, 0.60, 0.15),  # SOIC-8
        roundrect(16, 0.90, 0.80, 0.20),  # SOT-23
        "G04 APERTURE END LIST*",
    ]
    flashes: dict[int, list[tuple[float, float]]] = {}

    def flash(ap: int, x: float, y: float) -> None:
        flashes.setdefault(ap, []).append((x, y))

    # QFN-32, 5 x 5 mm, 0.5 mm pitch, centre at (20, 20)
    cx = cy = 20.0
    for i in range(8):
        o = (i - 3.5) * 0.5
        flash(10, cx - 2.45, cy + o)
        flash(10, cx + 2.45, cy + o)
        flash(11, cx + o, cy - 2.45)
        flash(11, cx + o, cy + 2.45)
    for dx in (-0.8, 0.8):
        for dy in (-0.8, 0.8):
            flash(12, cx + dx, cy + dy)
    # 0402 decoupling capacitors around the QFN
    for i in range(6):
        x = 14.0 + i * 2.4
        flash(13, x - 0.48, 14.5)
        flash(13, x + 0.48, 14.5)
    # 0603 resistors
    for i in range(4):
        y = 16.0 + i * 2.2
        flash(14, 27.0 - 0.8, y)
        flash(14, 27.0 + 0.8, y)
    # SOIC-8, 1.27 mm pitch
    for i in range(4):
        y = 26.5 + (i - 1.5) * 1.27
        flash(15, 10.0 - 2.475, y)
        flash(15, 10.0 + 2.475, y)
    # SOT-23
    flash(16, 9.05, 17.0)
    flash(16, 10.95, 17.0)
    flash(16, 10.0, 19.0)

    for ap, pts in flashes.items():
        out.append(f"D{ap}*")
        for x, y in pts:
            out.append(f"X{c46(x)}Y{c46(y)}D03*")
    out.append("M02*")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- BGA


def bga() -> str:
    out = [
        "G04 Synthetic example: BGA-100, 0.8 mm pitch, 0.4 mm openings, 3 fiducials*",
        "%FSLAX35Y35*%",
        "%MOMM*%",
        "%ADD10C,0.4*%",
        "%ADD11C,1.0*%",
        "D10*",
    ]
    for row in range(10):
        cols = range(10) if row % 2 == 0 else range(9, -1, -1)  # serpentine order
        for col in cols:
            out.append(f"X{int(round((5 + col * 0.8) * 1e5))}Y{int(round((5 + row * 0.8) * 1e5))}D03*")
    out.append("D11*")
    for x, y in ((2.0, 2.0), (15.2, 2.0), (2.0, 15.2)):
        out.append(f"X{int(round(x * 1e5))}Y{int(round(y * 1e5))}D03*")
    out.append("M02*")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- arcs, regions, polarity


def arcs() -> str:
    def c(v: float) -> str:
        return str(int(round(v * 1e4)))

    def xy(x: float, y: float) -> str:
        return f"X{c(x)}Y{c(y)}"

    out = [
        "G04 Synthetic example: regions with arcs, arc draws, special apertures, clear polarity*",
        "%FSLAX34Y34*%",
        "%MOMM*%",
        "%AMTILTED*21,1,1.6,0.5,0,0,$1*%",
        "%ADD10C,0.5*%",
        "%ADD11O,2.0X0.8*%",
        "%ADD12O,0.8X2.0*%",
        "%ADD13P,1.6X6X0*%",
        "%ADD14P,1.6X3X90*%",
        "%ADD15TILTED,30*%",
        "%ADD16TILTED,-45*%",
        "%ADD17R,4.0X4.0*%",
        "%ADD18R,5.0X0.4*%",
        "%ADD19R,0.4X5.0*%",
        "%ADD20C,1.6X0.6*%",
        "G75*",
        "G04 D-shaped region: straight edge plus a half circle*",
        "G36*",
        f"G01{xy(2, 2)}D02*",
        f"G01{xy(2, 5)}D01*",
        f"G02{xy(2, 2)}I0J{c(-1.5)}D01*",
        "G37*",
        "G04 rounded rectangle built from lines and counter clockwise corner arcs*",
        "G36*",
        f"G01{xy(6.5, 2)}D02*",
        f"{xy(9.5, 2)}D01*",
        f"G03{xy(10, 2.5)}I0J{c(0.5)}D01*",
        f"G01{xy(10, 4.5)}D01*",
        f"G03{xy(9.5, 5)}I{c(-0.5)}J0D01*",
        f"G01{xy(6.5, 5)}D01*",
        f"G03{xy(6, 4.5)}I0J{c(-0.5)}D01*",
        f"G01{xy(6, 2.5)}D01*",
        f"G03{xy(6.5, 2)}I{c(0.5)}J0D01*",
        "G37*",
        "G04 curved slot: an arc drawn with a round aperture*",
        "D10*",
        f"G01{xy(12, 2)}D02*",
        f"G03{xy(15, 5)}I0J{c(3)}D01*",
        "G04 full circle ring drawn in one arc*",
        f"G01{xy(19.5, 3.5)}D02*",
        f"G02{xy(19.5, 3.5)}I{c(-1.5)}J0D01*",
        "G01*",
        "G04 obround, hexagon, triangle, rotated macro pads, round pad with hole*",
        f"D11*{xy(3, 8)}D03*",
        f"D12*{xy(6, 8)}D03*",
        f"D13*{xy(9, 8)}D03*",
        f"D14*{xy(12, 8)}D03*",
        f"D15*{xy(15, 8)}D03*",
        f"D16*{xy(18, 8)}D03*",
        f"D20*{xy(21, 8)}D03*",
        "G04 large pad split into four window panes by clear polarity*",
        f"D17*{xy(4, 13)}D03*",
        "%LPC*%",
        f"D18*{xy(4, 13)}D03*",
        f"D19*{xy(4, 13)}D03*",
        "%LPD*%",
        "G04 pads mirrored and rotated with aperture transformations*",
        "%LR90*%",
        f"D11*{xy(9, 13)}D03*",
        "%LR0*%",
        "%LS0.5*%",
        f"D13*{xy(12, 13)}D03*",
        "%LS1*%",
        "%LMX*%",
        f"D15*{xy(15, 13)}D03*",
        "%LMN*%",
        "M02*",
    ]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- legacy inch


def legacy() -> str:
    # 2.3 format, trailing zeros omitted: "X015" means 01.500 -> 1.5 inch
    def c(v: float) -> str:
        digits = f"{int(round(v * 1000)):05d}"
        return digits.rstrip("0") or "0"

    out = [
        "G04 Synthetic example: old style inch file, trailing zero omission, modal codes*",
        "%FSTAX23Y23*%",
        "G70*",
        "G90*",
        "%ADD10R,0.024X0.060*%",
        "%ADD11R,0.050X0.030*%",
        "%ADD12C,0.040*%",
        "G54D10*",
    ]
    # SOIC-16, 50 mil pitch, two rows; X only where it changes, D03 is modal
    out.append(f"X{c(0.5)}Y{c(0.4)}D03*")
    for i in range(1, 8):
        out.append(f"X{c(0.5 + i * 0.05)}*")
    out.append(f"X{c(0.5)}Y{c(0.64)}D03*")
    for i in range(1, 8):
        out.append(f"X{c(0.5 + i * 0.05)}*")
    # resistor array drawn as short strokes with a rectangular aperture
    out.append("G54D11*")
    for i in range(5):
        y = 0.9 + i * 0.07
        out.append(f"G01X{c(0.5)}Y{c(y)}D02*")
        out.append(f"X{c(0.52)}D01*")
        out.append(f"X{c(0.78)}D02*")
        out.append(f"X{c(0.8)}D01*")
    # test points
    out.append("G54D12*")
    for x, y in ((1.1, 0.45), (1.1, 0.75), (1.1, 1.05)):
        out.append(f"X{c(x)}Y{c(y)}D03*")
    out.append("M02*")
    return "\n".join(out) + "\n"


def main() -> None:
    files = {
        "kicad_style_qfn32.gbr": kicad_style(),
        "bga100_0.8mm.gbr": bga(),
        "arcs_regions_polarity.gbr": arcs(),
        "legacy_inch_soic.gbr": legacy(),
    }
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="ascii", newline="\n")
        print(f"{name}: {len(text)} bytes")


if __name__ == "__main__":
    main()
