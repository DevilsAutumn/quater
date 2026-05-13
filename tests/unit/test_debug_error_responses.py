from __future__ import annotations

import logging

import pytest

from quater import HTTPError, Quater, Request


@pytest.mark.asyncio
async def test_unexpected_errors_are_sanitized_by_default() -> None:
    app = Quater()

    @app.get("/boom")
    async def handler() -> dict[str, bool]:
        raise RuntimeError("database password leaked")

    response = await app.handle(Request(method="GET", path="/boom"))

    assert response.status_code == 500
    assert response.body == b"Internal Server Error"


@pytest.mark.asyncio
async def test_unexpected_errors_are_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = Quater()

    @app.get("/boom")
    async def handler() -> dict[str, bool]:
        raise RuntimeError("broken test")

    with caplog.at_level(logging.ERROR, logger="quater.error"):
        response = await app.handle(Request(method="GET", path="/boom"))

    assert response.status_code == 500
    assert "Unhandled exception while processing request" in caplog.text
    assert "RuntimeError: broken test" in caplog.text


@pytest.mark.asyncio
async def test_http_errors_are_not_logged_as_unhandled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = Quater()

    @app.get("/missing")
    async def handler() -> dict[str, bool]:
        raise HTTPError("missing", status_code=404)

    with caplog.at_level(logging.ERROR, logger="quater.error"):
        response = await app.handle(Request(method="GET", path="/missing"))

    assert response.status_code == 404
    assert "Unhandled exception while processing request" not in caplog.text


@pytest.mark.asyncio
async def test_debug_errors_include_exception_type_and_message() -> None:
    app = Quater(debug=True)

    @app.get("/boom")
    async def handler() -> dict[str, bool]:
        raise RuntimeError("broken test")

    response = await app.handle(Request(method="GET", path="/boom"))

    assert response.status_code == 500
    assert response.body == b"RuntimeError: broken test"
