"""Persistent application settings (JSON in the user's config folder)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import APP_NAME


def config_dir() -> Path:
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


@dataclass
class AppSettings:
    language: str = "auto"  # auto | de | en
    theme: str = "system"  # system | dark | light
    units: str = "mm"  # mm | inch
    check_updates: bool = True
    skipped_version: str = ""
    output_mode: str = "printer"  # printer | path
    printer: str = ""
    device_path: str = ""
    confirm_send: bool = True
    arc_tolerance: float = 0.005  # mm
    active_profile: str = "Standard"
    session_params: dict = field(default_factory=dict)  # last used working parameters
    last_dir: str = ""
    recent_files: list[str] = field(default_factory=list)
    geometry: str = ""  # window geometry, hex
    show_pads: bool = True
    show_cuts: bool = True

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "settings.json"

    @classmethod
    def load(cls) -> "AppSettings":
        raw = read_json(cls.path(), {})
        s = cls()
        if isinstance(raw, dict):
            for f in fields(cls):
                if f.name in raw and isinstance(raw[f.name], type(getattr(s, f.name))):
                    setattr(s, f.name, raw[f.name])
        return s

    def save(self) -> None:
        try:
            write_json(self.path(), asdict(self))
        except OSError:
            pass

    def add_recent(self, path: str) -> None:
        self.recent_files = [path] + [p for p in self.recent_files if p != path]
        del self.recent_files[8:]
        self.last_dir = str(Path(path).parent)
