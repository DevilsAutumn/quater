"""Application discovery for server commands."""

from __future__ import annotations

import ast
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

from quater.app import Quater
from quater.cli.errors import CLIUsageError, format_syntax_error

COMMON_APP_FILES = ("main.py", "app.py", "api.py", "server.py")
APP_ATTRIBUTE_NAMES = ("app", "application")
FACTORY_ATTRIBUTE_NAMES = ("create_app", "make_app", "get_app")


@dataclass(slots=True, frozen=True)
class DiscoveredApp:
    target: str
    factory: bool = False


@dataclass(slots=True, frozen=True)
class _Candidate:
    module_name: str
    attribute_name: str
    factory: bool

    @property
    def target(self) -> str:
        return f"{self.module_name}:{self.attribute_name}"


def resolve_app_target(
    target: str | None,
    *,
    working_dir: Path | None = None,
) -> DiscoveredApp:
    """Resolve an explicit target or discover one from common app files."""

    root = (working_dir or Path.cwd()).resolve()
    if target is not None and ":" in target:
        return DiscoveredApp(target=target)

    if target is not None:
        path = _target_path(target, root)
        if path is not None:
            discovered = _discover_from_file(path, root)
            if discovered is None:
                raise CLIUsageError(f"Could not find a Quater app in {path.name!r}")
            return discovered
        return _discover_from_module(target, root)

    searched = False
    for filename in COMMON_APP_FILES:
        path = root / filename
        if not path.is_file():
            continue
        searched = True
        discovered = _discover_from_file(path, root)
        if discovered is not None:
            return discovered

    if searched:
        names = ", ".join(COMMON_APP_FILES)
        raise CLIUsageError(f"Could not find a Quater app in {names}")
    raise CLIUsageError("Could not find a Quater app file")


def _target_path(target: str, root: Path) -> Path | None:
    path = Path(target).expanduser()
    if not path.is_absolute():
        path = root / path
    if path.suffix == ".py":
        if not path.is_file():
            raise CLIUsageError(f"App file does not exist: {target}")
        return path.resolve()
    if path.exists():
        if not path.is_file():
            raise CLIUsageError(f"App path is not a Python file: {target}")
        return path.resolve()
    return None


def _discover_from_file(path: Path, root: Path) -> DiscoveredApp | None:
    module_name = _module_name_from_path(path, root)
    static_candidates = _static_candidates(path, module_name)
    selected = _select_candidate(static_candidates)
    if selected is not None:
        return DiscoveredApp(target=selected.target, factory=selected.factory)

    dynamic_candidates = _dynamic_candidates(module_name, root)
    selected = _select_candidate(dynamic_candidates)
    if selected is None:
        return None
    return DiscoveredApp(target=selected.target, factory=selected.factory)


def _discover_from_module(module_name: str, root: Path) -> DiscoveredApp:
    selected = _select_candidate(_dynamic_candidates(module_name, root))
    if selected is None:
        raise CLIUsageError(f"Could not find a Quater app in module {module_name!r}")
    return DiscoveredApp(target=selected.target, factory=selected.factory)


def _module_name_from_path(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root)
    except ValueError as exc:
        raise CLIUsageError("App file must be inside the working directory") from exc

    parts = (*relative.with_suffix("").parts,)
    if not parts or any(not part.isidentifier() for part in parts):
        raise CLIUsageError("App file path is not importable as a Python module")
    return ".".join(parts)


def _static_candidates(path: Path, module_name: str) -> list[_Candidate]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise CLIUsageError(
            format_syntax_error(f"Could not inspect app file {path.name!r}", exc)
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise CLIUsageError(f"Could not read app file {path.name!r}: {exc}") from exc

    candidates: list[_Candidate] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and _is_quater_call(node.value):
            for target in node.targets:
                candidates.extend(_assigned_name_candidates(target, module_name))
        elif isinstance(node, ast.AnnAssign) and _is_quater_call(node.value):
            candidates.extend(_assigned_name_candidates(node.target, module_name))
        elif (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name in FACTORY_ATTRIBUTE_NAMES
            and _returns_quater(node)
        ):
            candidates.append(
                _Candidate(
                    module_name=module_name,
                    attribute_name=node.name,
                    factory=True,
                )
            )
    return candidates


def _dynamic_candidates(module_name: str, root: Path) -> list[_Candidate]:
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    try:
        module = importlib.import_module(module_name)
    except SyntaxError as exc:
        raise CLIUsageError(
            format_syntax_error(
                f"Could not import app module {module_name!r}",
                exc,
            )
        ) from exc
    except ImportError as exc:
        raise CLIUsageError(f"Could not import app module {module_name!r}") from exc

    candidates: list[_Candidate] = []
    for attribute_name in APP_ATTRIBUTE_NAMES:
        if isinstance(getattr(module, attribute_name, None), Quater):
            candidates.append(
                _Candidate(
                    module_name=module_name,
                    attribute_name=attribute_name,
                    factory=False,
                )
            )
    return candidates


def _assigned_name_candidates(target: ast.expr, module_name: str) -> list[_Candidate]:
    if not isinstance(target, ast.Name):
        return []
    return [
        _Candidate(
            module_name=module_name,
            attribute_name=target.id,
            factory=False,
        )
    ]


def _select_candidate(candidates: list[_Candidate]) -> _Candidate | None:
    if not candidates:
        return None
    for preferred in (*APP_ATTRIBUTE_NAMES, *FACTORY_ATTRIBUTE_NAMES):
        matches = [
            candidate
            for candidate in candidates
            if candidate.attribute_name == preferred
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            break
    if len(candidates) == 1:
        return candidates[0]

    names = ", ".join(candidate.target for candidate in candidates)
    raise CLIUsageError(f"Multiple Quater apps found: {names}")


def _is_quater_call(value: ast.expr | None) -> bool:
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Name):
        return func.id == "Quater"
    if isinstance(func, ast.Attribute):
        return func.attr == "Quater"
    return False


def _returns_quater(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and _is_quater_call(child.value):
            return True
    return False
