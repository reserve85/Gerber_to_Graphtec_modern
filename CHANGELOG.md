# Changelog

## 2.0.0

Complete rewrite as a desktop application.

- Native Gerber (RS-274X) reader; gerbv and pstoedit are no longer required
- New Qt user interface with live preview and cutting simulation
- Profiles (built-in and user defined, import/export)
- Statistics incl. knife strokes, cut length, travel and estimated duration
- Pad shrink, rotation, mirroring, media presets, calibration matrix
- Output to an installed printer (RAW), a device path or a file
- Settings page, dark/light theme, German/English, mm/inch
- Update check against GitHub releases
- Single-file executable for Windows, Linux build, command line tool `g2g-cli`
- Cutting strategy unchanged; output verified against the original code
