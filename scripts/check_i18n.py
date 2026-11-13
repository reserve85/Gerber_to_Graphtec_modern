"""List source strings that are missing in the German catalogue (and stale ones)."""

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "g2g"
sys.path.insert(0, str(SRC.parent))


def strings() -> set[str]:
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return found


def main() -> int:
    try:
        from g2g.lang_de import DE, DYNAMIC
    except ImportError:
        DE, DYNAMIC = {}, set()
    used = strings()
    missing = sorted(used - set(DE))
    stale = sorted(set(DE) - used - set(DYNAMIC))
    for s in missing:
        print(f"    {s!r}: ,")
    for s in stale:
        print("STALE:", repr(s))
    print(f"{len(used)} strings, {len(missing)} missing, {len(stale)} stale", file=sys.stderr)
    return 1 if missing or stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
