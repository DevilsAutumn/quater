"""Loader for manually-authored reference pages.

If every reference file exists and none carries the generated header, the
generator hands the manual content back unchanged (after checking each
public symbol has an anchor on its assigned page).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from _reference.pages import PAGES, ReferencePage
from _reference.paths import GENERATED_HEADER, REFERENCE_DIR
from _reference.types import symbol_anchor


def read_manual_reference(
    public_api: tuple[str, ...],
    pages_by_symbol: Mapping[str, ReferencePage],
) -> dict[Path, str] | None:
    paths = {REFERENCE_DIR / "index.md", *(page.path for page in PAGES)}
    outputs: dict[Path, str] = {}
    for path in paths:
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        if content.startswith(GENERATED_HEADER):
            return None
        outputs[path] = content

    for name in public_api:
        page = pages_by_symbol[name]
        content = outputs[page.path]
        anchor = symbol_anchor(name)
        if anchor not in content:
            raise SystemExit(
                f"Manual reference page {page.path} does not document {name!r}"
            )
    return outputs
