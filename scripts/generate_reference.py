"""Generate the VitePress API reference from Quater's public Python API.

The heavy lifting lives in the internal ``_reference`` package next to this
script. This file only wires up the CLI, calls the pipeline, and re-exports
the signature helpers exercised by ``tests/unit/test_generate_reference.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import griffe  # noqa: E402
from _reference.output import check_outputs, write_outputs  # noqa: E402
from _reference.pages import (  # noqa: E402
    PAGES,
    page_map,
    read_public_api,
    validate_public_docstrings,
)
from _reference.paths import SOURCE_ROOT  # noqa: E402
from _reference.render import render_reference  # noqa: E402
from _reference.signatures import (  # noqa: E402,F401
    clean_signature,
    format_signature,
    split_top_level_commas,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if generated reference files are stale.",
    )
    args = parser.parse_args(argv)

    public_api = read_public_api()
    pages_by_symbol = page_map(PAGES)
    missing = sorted(set(public_api) - set(pages_by_symbol))
    if missing:
        raise SystemExit(
            "Reference pages do not cover public exports: " + ", ".join(missing)
        )

    package = griffe.load("quater", search_paths=[str(SOURCE_ROOT)])
    validate_public_docstrings(package, public_api)
    outputs = render_reference(package, public_api, pages_by_symbol)

    if args.check:
        return check_outputs(outputs)

    write_outputs(outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
