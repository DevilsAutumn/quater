"""Application loading for local CLI commands."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from quater.app import Quater
from quater.cli.errors import CLIUsageError, format_syntax_error


def load_app(
    import_path: str,
    *,
    factory: bool = False,
    working_dir: Path | None = None,
) -> Quater:
    module_name, separator, attribute_path = import_path.partition(":")
    if not module_name or not separator or not attribute_path:
        raise CLIUsageError("App must be specified as module:attribute")

    cwd = str(working_dir or os.getcwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    try:
        target: object = importlib.import_module(module_name)
    except SyntaxError as exc:
        raise CLIUsageError(
            format_syntax_error(
                f"Could not import app module {module_name!r}",
                exc,
            )
        ) from exc
    except ImportError as exc:
        raise CLIUsageError(f"Could not import app module {module_name!r}") from exc

    for attribute in attribute_path.split("."):
        if not attribute:
            raise CLIUsageError("App attribute path must not contain empty parts")
        try:
            target = getattr(target, attribute)
        except AttributeError as exc:
            raise CLIUsageError(
                f"Could not find app attribute {attribute_path!r}"
            ) from exc

    if factory:
        if not callable(target):
            raise CLIUsageError("App factory target is not callable")
        target = target()

    if not isinstance(target, Quater):
        raise CLIUsageError("Loaded object is not a Quater application")
    return target
