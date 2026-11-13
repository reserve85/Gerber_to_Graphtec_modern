"""Deliver the command stream to the cutter.

On Windows the cutter is addressed as an installed printer and receives the
data as a RAW spooler job, so no shared-printer trick and no extra driver is
needed.  Alternatively the data can be written to any path (a device node such
as /dev/usb/lp0 or a UNC printer share).
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path


class OutputError(RuntimeError):
    pass


def save_file(path: str | Path, data: bytes) -> None:
    try:
        Path(path).write_bytes(data)
    except OSError as exc:
        raise OutputError(str(exc)) from exc


def send_to_path(path: str, data: bytes) -> None:
    """Write raw data to a device node or printer share."""
    try:
        with open(path, "wb") as fh:
            fh.write(data)
    except OSError as exc:
        raise OutputError(str(exc)) from exc


if sys.platform == "win32":
    from ctypes import wintypes

    class _PrinterInfo4(ctypes.Structure):
        _fields_ = [
            ("pPrinterName", wintypes.LPWSTR),
            ("pServerName", wintypes.LPWSTR),
            ("Attributes", wintypes.DWORD),
        ]

    class _DocInfo1(ctypes.Structure):
        _fields_ = [
            ("pDocName", wintypes.LPWSTR),
            ("pOutputFile", wintypes.LPWSTR),
            ("pDatatype", wintypes.LPWSTR),
        ]

    def _spool() -> ctypes.WinDLL:
        spool = ctypes.WinDLL("winspool.drv", use_last_error=True)
        spool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
        spool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
        spool.StartDocPrinterW.restype = wintypes.DWORD
        spool.StartPagePrinter.argtypes = [wintypes.HANDLE]
        spool.WritePrinter.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        spool.EndPagePrinter.argtypes = [wintypes.HANDLE]
        spool.EndDocPrinter.argtypes = [wintypes.HANDLE]
        spool.ClosePrinter.argtypes = [wintypes.HANDLE]
        spool.EnumPrintersW.argtypes = [
            wintypes.DWORD,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        return spool

    def list_printers() -> list[str]:
        spool = _spool()
        flags = 0x2 | 0x4  # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
        needed, count = wintypes.DWORD(0), wintypes.DWORD(0)
        spool.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(count))
        if not needed.value:
            return []
        buf = ctypes.create_string_buffer(needed.value)
        if not spool.EnumPrintersW(flags, None, 4, buf, needed.value, ctypes.byref(needed), ctypes.byref(count)):
            return []
        infos = ctypes.cast(buf, ctypes.POINTER(_PrinterInfo4))
        return sorted(infos[i].pPrinterName for i in range(count.value))

    def send_to_printer(printer: str, data: bytes, title: str = "Gerber2Graphtec") -> None:
        spool = _spool()
        handle = wintypes.HANDLE()

        def fail(step: str) -> OutputError:
            return OutputError(f"{step}: {ctypes.FormatError(ctypes.get_last_error())}")

        if not spool.OpenPrinterW(printer, ctypes.byref(handle), None):
            raise fail("OpenPrinter")
        try:
            doc = _DocInfo1(title, None, "RAW")
            if not spool.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
                raise fail("StartDocPrinter")
            try:
                if not spool.StartPagePrinter(handle):
                    raise fail("StartPagePrinter")
                written = wintypes.DWORD(0)
                ok = spool.WritePrinter(handle, data, len(data), ctypes.byref(written))
                spool.EndPagePrinter(handle)
                if not ok or written.value != len(data):
                    raise fail("WritePrinter")
            finally:
                spool.EndDocPrinter(handle)
        finally:
            spool.ClosePrinter(handle)

else:
    import shutil
    import subprocess

    def list_printers() -> list[str]:
        """Print queues known to CUPS."""
        if not shutil.which("lpstat"):
            return []
        try:
            res = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return []
        return sorted(line.strip() for line in res.stdout.splitlines() if line.strip())

    def send_to_printer(printer: str, data: bytes, title: str = "Gerber2Graphtec") -> None:
        """Send as a raw job through CUPS."""
        if not shutil.which("lp"):
            raise OutputError("CUPS (lp) is not installed; use a device path such as /dev/usb/lp0 instead.")
        try:
            res = subprocess.run(["lp", "-d", printer, "-o", "raw", "-t", title], input=data, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise OutputError(str(exc)) from exc
        if res.returncode != 0:
            raise OutputError(res.stderr.decode("utf-8", "replace").strip() or "lp failed")
