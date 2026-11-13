"""Cutting profiles: named parameter presets, built-in and user defined."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .core.toolpath import CutParams, CutPass
from .settings import config_dir, read_json, write_json


@dataclass
class Profile:
    name: str
    description: str = ""
    params: CutParams = field(default_factory=CutParams)
    builtin: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "params": self.params.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(
            name=str(d.get("name", "")).strip() or "Profile",
            description=str(d.get("description", "")),
            params=CutParams.from_dict(d.get("params", {})),
        )


def builtin_profiles() -> list[Profile]:
    return [
        Profile(
            "Standard",
            "Two passes, line by line with knife training. The proven defaults of the original "
            "gerber2graphtec for 3-5 mil (0.08-0.12 mm) Mylar / laser transparency film.",
            CutParams(),
            builtin=True,
        ),
        Profile(
            "Fine Pitch",
            "Three slow passes with rising force and 0.025 mm pad shrink. Starting point for "
            "0.5 mm pitch QFP/QFN and 0201 parts.",
            CutParams(passes=[CutPass(1, 5), CutPass(1, 15), CutPass(1, 30)], inset=0.025),
            builtin=True,
        ),
        Profile(
            "Draft",
            "One pass with closed outlines. Fast, but less accurate - for large pads and test cuts.",
            CutParams(mode="fast", passes=[CutPass(5, 25)]),
            builtin=True,
        ),
    ]


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "profiles.json")
        self.builtin = builtin_profiles()
        self.user: list[Profile] = []
        self.load()

    def load(self) -> None:
        raw = read_json(self.path, [])
        self.user = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    p = Profile.from_dict(item)
                    if not self.get(p.name):
                        self.user.append(p)

    def save(self) -> None:
        try:
            write_json(self.path, [p.to_dict() for p in self.user])
        except OSError:
            pass

    def all(self) -> list[Profile]:
        return self.builtin + sorted(self.user, key=lambda p: p.name.lower())

    def names(self) -> list[str]:
        return [p.name for p in self.all()]

    def get(self, name: str) -> Profile | None:
        for p in self.builtin + self.user:
            if p.name.lower() == name.lower():
                return p
        return None

    def unique_name(self, base: str) -> str:
        name, n = base, 2
        while self.get(name):
            name = f"{base} {n}"
            n += 1
        return name

    def put(self, name: str, params: CutParams, description: str | None = None) -> Profile:
        """Create or overwrite a user profile.  Built-in names cannot be overwritten."""
        existing = self.get(name)
        if existing and existing.builtin:
            raise ValueError("built-in profiles are read-only")
        params = CutParams.from_dict(params.to_dict())  # detached copy
        if existing:
            existing.params = params
            if description is not None:
                existing.description = description
            profile = existing
        else:
            profile = Profile(name, description or "", params)
            self.user.append(profile)
        self.save()
        return profile

    def delete(self, name: str) -> None:
        self.user = [p for p in self.user if p.name.lower() != name.lower()]
        self.save()

    def rename(self, old: str, new: str) -> bool:
        p = self.get(old)
        if not p or p.builtin or not new.strip() or (self.get(new) and self.get(new) is not p):
            return False
        p.name = new.strip()
        self.save()
        return True

    def export_file(self, name: str, path: str) -> None:
        p = self.get(name)
        if p:
            write_json(Path(path), {"gerber2graphtec_profile": 1, **p.to_dict()})

    def import_file(self, path: str) -> Profile:
        raw = read_json(Path(path), None)
        if not isinstance(raw, dict) or "params" not in raw:
            raise ValueError("not a profile file")
        p = Profile.from_dict(raw)
        p.name = self.unique_name(p.name)
        self.user.append(p)
        self.save()
        return p
