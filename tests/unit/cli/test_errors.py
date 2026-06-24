from __future__ import annotations

from quater.cli.errors import format_syntax_error


def test_format_syntax_error_without_line_or_column() -> None:
    exc = SyntaxError("invalid syntax")
    result = format_syntax_error("Error", exc)

    assert "invalid syntax" in result
    assert "line" not in result.lower()
    assert "column" not in result.lower()


def test_format_syntax_error_without_source_text() -> None:
    exc = SyntaxError(
        "invalid syntax",
        ("test.py", 1, 1, None),
    )

    result = format_syntax_error("Error", exc)

    assert "invalid syntax" in result


def test_format_syntax_error_blank_source_text() -> None:
    exc = SyntaxError(
        "invalid syntax",
        ("test.py", 1, 1, ""),
    )

    result = format_syntax_error("Error", exc)

    assert "invalid syntax" in result


def test_format_syntax_error_column_before_indentation() -> None:
    exc = SyntaxError(
        "invalid syntax",
        ("test.py", 1, 1, "    value"),
    )

    result = format_syntax_error("Error", exc)

    assert result == "\n".join(
        [
            "Error: invalid syntax (line 1, column 1)",
            "    value",
            "    ^",
        ]
    )


def test_format_syntax_error_column_after_line_end() -> None:
    exc = SyntaxError(
        "invalid syntax",
        ("test.py", 1, 100, "value"),
    )

    result = format_syntax_error("Error", exc)

    assert result == "\n".join(
        [
            "Error: invalid syntax (line 1, column 100)",
            "    value",
            "        ^",
        ]
    )


def test_format_syntax_error_single_source_line_can_have_later_file_line() -> None:
    exc = SyntaxError(
        "invalid syntax",
        ("test.py", 99, 5, "bad +"),
    )

    result = format_syntax_error("Error", exc)

    assert result == "\n".join(
        [
            "Error: invalid syntax (line 99, column 5)",
            "    bad +",
            "        ^",
        ]
    )


def test_format_syntax_error_multiline_text() -> None:
    exc = SyntaxError(
        "invalid syntax",
        ("test.py", 1, 1, "line1\nline2"),
    )

    result = format_syntax_error("Error", exc)

    assert result == "\n".join(
        [
            "Error: invalid syntax (line 1, column 1)",
            "    line1",
            "    ^",
            "    line2",
        ]
    )


def test_format_syntax_error_multiline_text_with_error_on_later_line() -> None:
    exc = SyntaxError(
        "invalid syntax",
        ("test.py", 2, 4, "line1\n  bad"),
    )

    result = format_syntax_error("Error", exc)

    assert result == "\n".join(
        [
            "Error: invalid syntax (line 2, column 4)",
            "    line1",
            "      bad",
            "       ^",
        ]
    )


def test_format_syntax_error_multiline_text_with_unmatched_line_skips_caret() -> None:
    exc = SyntaxError(
        "invalid syntax",
        ("test.py", 99, 2, "line1\nline2"),
    )

    result = format_syntax_error("Error", exc)

    assert result == "\n".join(
        [
            "Error: invalid syntax (line 99, column 2)",
            "    line1",
            "    line2",
        ]
    )
