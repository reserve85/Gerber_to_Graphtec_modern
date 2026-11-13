"""Update check against the GitHub releases of the project.

Only looks up the latest published release and compares version numbers.
Nothing is downloaded or installed automatically; the user is sent to the
release page instead.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import APP_NAME, GITHUB_REPO, __version__


class UpdateError(RuntimeError):
    pass


@dataclass
class Release:
    version: str
    url: str
    notes: str = ""
    download_url: str = ""  # direct link to the build for this platform, if any

    @property
    def is_newer(self) -> bool:
        return parse_version(self.version) > parse_version(__version__)


def parse_version(text: str) -> tuple[int, ...]:
    """'v2.1.0-beta' -> (2, 1, 0).  Unparseable input sorts lowest."""
    nums = re.findall(r"\d+", text.split("-", maxsplit=1)[0].split("+", maxsplit=1)[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def releases_url(repo: str = GITHUB_REPO) -> str:
    return f"https://github.com/{repo}/releases"


def fetch_latest(repo: str = GITHUB_REPO, timeout: float = 8.0) -> Release | None:
    """Return the latest release, or None if the project has no releases yet."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"{APP_NAME}/{__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise UpdateError(f"GitHub: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(str(getattr(exc, "reason", exc))) from exc

    tag = str(data.get("tag_name") or data.get("name") or "")
    if not tag:
        return None
    download = ""
    for asset in data.get("assets") or []:
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe") if sys.platform == "win32" else "linux" in name:
            download = str(asset.get("browser_download_url", ""))
            break
    return Release(
        version=tag.lstrip("vV"),
        url=str(data.get("html_url") or releases_url(repo)),
        notes=str(data.get("body") or ""),
        download_url=download,
    )
