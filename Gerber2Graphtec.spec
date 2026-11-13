# PyInstaller build recipe:  pyinstaller --noconfirm Gerber2Graphtec.spec
# Produces a single-file executable in dist/ (Gerber2Graphtec.exe on Windows).
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "src/g2g/__init__.py").read_text()).group(1)

version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )

    nums = tuple(int(n) for n in (VERSION.split("-")[0].split(".") + ["0"] * 4)[:4])
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "reserve85"),
                StringStruct("FileDescription", "Gerber2Graphtec - SMT stencil cutting"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "Gerber2Graphtec"),
                StringStruct("LegalCopyright", "GPL-2.0. Based on gerber2graphtec (c) 2012 Peter Monta"),
                StringStruct("OriginalFilename", "Gerber2Graphtec.exe"),
                StringStruct("ProductName", "Gerber2Graphtec"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

a = Analysis(
    [str(ROOT / "src/g2g/__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src/g2g/assets"), "g2g/assets")],
    hiddenimports=["g2g.lang_de"],
    excludes=["tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Gerber2Graphtec",
    console=False,
    upx=False,
    icon=str(ROOT / "src/g2g/assets/icon.ico"),
    version=version_info,
)
