"""Shared application state handed to all pages."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..profiles import ProfileStore
from ..settings import AppSettings


class Context(QObject):
    profilesChanged = Signal()
    unitsChanged = Signal()
    themeChanged = Signal()
    toast = Signal(str)
    loadProfileRequested = Signal(str)
    checkUpdatesRequested = Signal()

    def __init__(self):
        super().__init__()
        self.settings = AppSettings.load()
        self.store = ProfileStore()

    def format_length(self, mm: float, decimals: int | None = None) -> str:
        if self.settings.units == "inch":
            return f"{mm / 25.4:.{3 if decimals is None else decimals}f} in"
        return f"{mm:.{2 if decimals is None else decimals}f} mm"
