"""Unit tests for the immutable request/response data views.

``Headers``, ``QueryParams``, and ``Cookies`` back request parsing, so their
case-handling, repeated-value, and malformed-input behaviour is pinned here
directly rather than only through full request round-trips.
"""

from __future__ import annotations

import pytest

from quater.datastructures import (
    Cookies,
    Headers,
    QueryParams,
    normalize_response_headers,
)
from quater.exceptions import BadRequestError


class TestHeaders:
    def test_lookup_is_case_insensitive(self) -> None:
        headers = Headers([("Content-Type", "text/plain")])

        assert headers["content-type"] == "text/plain"
        assert headers["CONTENT-TYPE"] == "text/plain"
        assert headers.get("missing") is None
        assert headers.get("missing", "default") == "default"

    def test_decodes_bytes_names_and_values(self) -> None:
        headers = Headers([(b"X-Trace", b"abc")])

        assert headers["x-trace"] == "abc"

    def test_len_iter_and_raw_reflect_all_items(self) -> None:
        headers = Headers([("Accept", "text/html"), ("X-A", "1"), ("X-A", "2")])

        assert len(headers) == 2
        assert set(headers) == {"accept", "x-a"}
        # raw preserves every pair, including duplicates, in order.
        assert headers.raw == (
            ("accept", "text/html"),
            ("x-a", "1"),
            ("x-a", "2"),
        )

    def test_get_all_returns_every_value_for_repeated_header(self) -> None:
        headers = Headers([("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")])

        assert headers.get_all("set-cookie") == ("a=1", "b=2")
        assert headers.get_all("missing") == ()

    def test_accepts_mapping_input(self) -> None:
        headers = Headers({"Content-Length": "12"})

        assert headers["content-length"] == "12"

    def test_rejects_non_string_header(self) -> None:
        with pytest.raises(TypeError):
            Headers([(123, "value")])  # type: ignore[list-item]


class TestQueryParams:
    def test_parses_pairs_and_keeps_blank_values(self) -> None:
        params = QueryParams.from_query_string("a=1&b=&a=2")

        assert params["a"] == "2"  # mapping view collapses to the last value
        assert params["b"] == ""
        assert params.get_all("a") == ("1", "2")
        assert params.raw == (("a", "1"), ("b", ""), ("a", "2"))

    def test_len_and_iter_reflect_distinct_keys(self) -> None:
        params = QueryParams.from_query_string("a=1&a=2&b=3")

        assert len(params) == 2
        assert set(params) == {"a", "b"}

    def test_accepts_bytes_query_string(self) -> None:
        params = QueryParams.from_query_string(b"q=search")

        assert params["q"] == "search"

    def test_empty_query_string_is_empty(self) -> None:
        params = QueryParams.from_query_string("")

        assert len(params) == 0
        assert params.get_all("anything") == ()

    @pytest.mark.parametrize("query", ["a=%", "a=%ZZ", "a=%2"])
    def test_rejects_malformed_percent_escapes(self, query: str) -> None:
        with pytest.raises(BadRequestError, match="Malformed query string"):
            QueryParams.from_query_string(query)

    def test_rejects_non_utf8_percent_bytes(self) -> None:
        # %ff is a syntactically valid escape but decodes to a non-UTF-8 byte.
        with pytest.raises(BadRequestError, match="Malformed query string"):
            QueryParams.from_query_string("name=%ff")

    def test_rejects_non_ascii_query_bytes(self) -> None:
        with pytest.raises(BadRequestError, match="Malformed query string"):
            QueryParams.from_query_string("q=é".encode())


class TestCookies:
    def test_parses_cookie_header(self) -> None:
        cookies = Cookies.from_cookie_header("session=abc; theme=dark")

        assert cookies["session"] == "abc"
        assert cookies["theme"] == "dark"
        assert len(cookies) == 2
        assert set(cookies) == {"session", "theme"}

    def test_missing_or_empty_header_yields_empty_cookies(self) -> None:
        assert len(Cookies.from_cookie_header(None)) == 0
        assert len(Cookies.from_cookie_header("")) == 0

    def test_malformed_segments_are_dropped_not_fatal(self) -> None:
        # SimpleCookie is lenient: an unparseable segment is skipped while valid
        # morsels are still returned, so a junk Cookie header never crashes the
        # request. The control-character segment is dropped and "a" survives.
        cookies = Cookies.from_cookie_header("a=b; \x00=c")

        assert dict(cookies) == {"a": "b"}


class TestNormalizeResponseHeaders:
    def test_returns_empty_for_none(self) -> None:
        assert normalize_response_headers(None) == ()

    def test_lowercases_names_and_decodes_bytes(self) -> None:
        assert normalize_response_headers([(b"X-Custom", b"value")]) == (
            ("x-custom", "value"),
        )

    @pytest.mark.parametrize(
        "name",
        ["", ":authority", "bad header", "x\tname"],
    )
    def test_rejects_invalid_header_names(self, name: str) -> None:
        with pytest.raises(ValueError, match="Invalid response header name"):
            normalize_response_headers([(name, "value")])

    @pytest.mark.parametrize(
        "value",
        ["line\nbreak", "carriage\rreturn", "null\x00byte", "snow☃man"],
    )
    def test_rejects_invalid_header_values(self, value: str) -> None:
        with pytest.raises(ValueError, match="Invalid response header value"):
            normalize_response_headers([("x-custom", value)])

    def test_allows_tab_in_header_value(self) -> None:
        assert normalize_response_headers([("x-custom", "a\tb")]) == (
            ("x-custom", "a\tb"),
        )
