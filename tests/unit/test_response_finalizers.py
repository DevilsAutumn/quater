from __future__ import annotations

import asyncio
import logging

import pytest

from quater import Request, Response
from quater._finalize import (
    add_request_finalizer,
    close_request_finalizers,
    move_request_finalizers_to_response,
    move_response_finalizers,
    run_response_finalizers,
    schedule_response_finalizers,
)


@pytest.mark.asyncio
async def test_response_finalizers_run_lifo_and_log_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    response = Response()

    async def first() -> None:
        events.append("first")

    async def failing() -> None:
        events.append("failing")
        raise RuntimeError("cleanup failed")

    async def last() -> None:
        events.append("last")

    response._finalizers = [first, failing, last]
    caplog.set_level(logging.ERROR, logger="quater.finalize")

    await run_response_finalizers(response)

    assert events == ["last", "failing", "first"]
    assert response._finalizers is None
    assert "Response cleanup failed" in caplog.text


def test_request_finalizers_move_to_response_once() -> None:
    async def cleanup() -> None:
        return None

    request = Request(method="GET", path="/orders")
    response = Response()

    assert move_request_finalizers_to_response(request, response) is response
    assert response._finalizers is None

    add_request_finalizer(request, cleanup)
    assert move_request_finalizers_to_response(request, response) is response

    assert request._finalizers is None
    assert response._finalizers == [cleanup]


def test_response_finalizers_move_between_responses_without_duplication() -> None:
    async def source_cleanup() -> None:
        return None

    async def target_cleanup() -> None:
        return None

    source = Response()
    target = Response()
    source._finalizers = [source_cleanup]
    target._finalizers = [target_cleanup]

    assert move_response_finalizers(source, target) is target
    assert source._finalizers is None
    assert target._finalizers == [target_cleanup, source_cleanup]


@pytest.mark.asyncio
async def test_close_request_finalizers_runs_lifo_and_propagates_errors() -> None:
    events: list[str] = []
    request = Request(method="GET", path="/orders")

    async def first() -> None:
        events.append("first")

    async def failing() -> None:
        events.append("failing")
        raise RuntimeError("close failed")

    async def last() -> None:
        events.append("last")

    request._finalizers = [first, failing, last]

    with pytest.raises(RuntimeError, match="close failed"):
        await close_request_finalizers(request)

    assert request._finalizers is None
    assert events == ["last", "failing"]


def test_scheduled_finalizers_are_ignored_without_running_loop() -> None:
    async def cleanup() -> None:
        return None

    response = Response()
    response._finalizers = [cleanup]

    schedule_response_finalizers(response)

    assert response._finalizers == [cleanup]


@pytest.mark.asyncio
async def test_scheduled_finalizers_run_on_current_event_loop() -> None:
    events: list[str] = []
    response = Response()

    async def cleanup() -> None:
        events.append("closed")

    response._finalizers = [cleanup]

    schedule_response_finalizers(response)
    await asyncio.sleep(0)

    assert response._finalizers is None
    assert events == ["closed"]
