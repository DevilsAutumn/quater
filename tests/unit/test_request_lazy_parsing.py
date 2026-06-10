from __future__ import annotations

import pytest

from quater.exceptions import BadRequestError
from quater.request import Request


@pytest.mark.asyncio
async def test_query_string_is_not_parsed_until_accessed() -> None:
    request = Request(method="GET", path="/items", query_string="bad=%")

    body = await request.body()

    assert body == b""
    with pytest.raises(BadRequestError):
        _ = request.query


def test_headers_are_case_insensitive_and_lazy() -> None:
    request = Request(
        method="GET",
        path="/",
        headers=[("Content-Type", "application/json"), (b"X-Request-ID", b"abc")],
    )

    assert request.headers["content-type"] == "application/json"
    assert request.headers["CONTENT-TYPE"] == "application/json"
    assert request.headers["x-request-id"] == "abc"
    assert request.headers is request.headers


def test_query_params_preserve_repeated_values() -> None:
    request = Request(method="GET", path="/search", query_string="tag=a&tag=b&q=hello")

    assert request.query["tag"] == "b"
    assert request.query.get_all("tag") == ("a", "b")
    assert request.query["q"] == "hello"


def test_cookies_are_parsed_from_headers_lazily() -> None:
    request = Request(
        method="GET",
        path="/",
        headers=[("Cookie", "session=abc; theme=light")],
    )

    assert request.cookies["session"] == "abc"
    assert request.cookies["theme"] == "light"
    assert request.cookies is request.cookies


def test_malformed_cookie_segment_is_skipped_not_fatal() -> None:
    request = Request(
        method="GET",
        path="/",
        headers=[("Cookie", "session=abc; \x00=x")],
    )

    assert dict(request.cookies) == {"session": "abc"}
