"""Print the CHANGELOG.md section of a version (default: the current __version__).

Used by the release workflow for the release text; exits with an error if the
changelog has no entry for that version.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def current_version() -> str:
    return re.search(r'__version__ = "([^"]+)"', (ROOT / "src/g2g/__init__.py").read_text(encoding="utf-8")).group(1)


def notes(version: str) -> str | None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## v?{re.escape(version)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else None


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else current_version()
    body = notes(version)
    if not body:
        print(f"CHANGELOG.md has no section '## {version}'", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
