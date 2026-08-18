"""Write generated reference files or diff them in --check mode."""

from __future__ import annotations

import difflib
import sys
from collections.abc import Mapping
from pathlib import Path

from _reference.paths import REFERENCE_DIR


def write_outputs(outputs: Mapping[Path, str]) -> None:
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    for path, content in sorted(outputs.items()):
        path.write_text(content, encoding="utf-8")


def check_outputs(outputs: Mapping[Path, str]) -> int:
    stale = False
    for path, expected in sorted(outputs.items()):
        if not path.exists():
            print(f"Missing generated reference file: {path}", file=sys.stderr)
            stale = True
            continue
        actual = path.read_text(encoding="utf-8")
        if actual == expected:
            continue
        stale = True
        diff = difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile=str(path),
            tofile=f"{path} (generated)",
            lineterm="",
        )
        print("\n".join(diff), file=sys.stderr)
    return 1 if stale else 0
