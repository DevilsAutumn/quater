"""Small exception types used by the Quater CLI."""

from __future__ import annotations


class CLIError(Exception):
    exit_code = 1


class CLIUsageError(CLIError):
    exit_code = 2


def format_syntax_error(prefix: str, exc: SyntaxError) -> str:
    """Format app-file syntax errors without hiding the useful location."""

    message = f"{prefix}: {exc.msg}"
    location = _syntax_error_location(exc)
    if location:
        message = f"{message} ({location})"

    source_lines = _syntax_error_source_lines(exc)
    if not source_lines:
        return message
    return "\n".join((message, *source_lines))


def _syntax_error_location(exc: SyntaxError) -> str:
    parts: list[str] = []
    if exc.lineno is not None:
        parts.append(f"line {exc.lineno}")
    if exc.offset is not None:
        parts.append(f"column {exc.offset}")
    return ", ".join(parts)


def _syntax_error_source_lines(exc: SyntaxError) -> list[str]:
    if exc.text is None:
        return []

    line = exc.text.rstrip("\n")
    stripped = line.lstrip()
    if not stripped:
        return []

    source_lines = stripped.splitlines()

    caret_line_index: int | None = 0
    if exc.lineno is not None:
        if 1 <= exc.lineno <= len(source_lines):
            caret_line_index = exc.lineno - 1
        elif len(source_lines) > 1:
            caret_line_index = None

    lines: list[str] = []
    for index, source_line in enumerate(source_lines):
        lines.append(f"    {source_line}")
        if exc.offset is None or caret_line_index is None or index != caret_line_index:
            continue

        leading_spaces = len(line) - len(stripped) if index == 0 else 0
        caret_position = max(exc.offset - leading_spaces - 1, 0)
        caret_position = min(caret_position, max(len(source_line) - 1, 0))
        lines.append(f"    {' ' * caret_position}^")
    return lines
