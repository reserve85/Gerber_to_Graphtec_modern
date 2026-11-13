# Changelog

## 2.0.1

- User manual in English and German (`docs/`), opened from the About page or with F1
- The repository is now `reserve85/gerber2graphtec-modern`; the update check and all links use the new address
- LICENSE contains the full GPL-2.0 text

## 2.0.0

Complete rewrite as a desktop application for Windows and Linux.

**New**

- Native Gerber (RS-274X) reader: aperture macros, regions, arcs, polarity,
  aperture transformations. gerbv, pstoedit and Ghostscript are no longer needed.
- Qt user interface with live preview, zoom / pan and a simulation of the
  cutting order
- Profiles (built-in and user defined, import / export)
- Statistics: pads, knife strokes, straight cuts, cut length, travel, smallest
  opening, estimated duration
- Pad shrink, rotation, mirroring, media presets, calibration matrix
- Output as RAW job to an installed printer (Windows spooler, CUPS), to a
  device path, or to a file
- Settings page, dark / light theme, German / English, mm / inch
- Update check against the GitHub releases
- Single-file executable for Windows and Linux, command line tool `g2g-cli`

**Compared with the original tool chain**

- The cutting strategy is unchanged (single lines in both directions, grouped
  by knife angle, a training cut per angle); the command stream is verified
  against the original code.
- Round pads are cut round instead of as 8-point diamonds.
- Pads at the board edge are no longer clipped, and no pads are dropped.
- KiCad-style rounded rectangle pads, clear polarity and arcs are read correctly.
