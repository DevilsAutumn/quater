from __future__ import annotations

import asyncio

import pytest

from quater import Quater, Request, TestClient


@pytest.mark.asyncio
async def test_request_state_and_context_do_not_leak_between_concurrent_requests() -> (
    None
):
    app = Quater()

    @app.get("/echo")
    async def echo(value: str, request: Request) -> dict[str, object]:
        request.state.value = value
        await asyncio.sleep(0)
        return {
            "value": value,
            "state_value": request.state.value,
            "source": request.context.source,
            "request_id": request.context.request_id,
        }

    async with TestClient(app) as client:
        responses = await asyncio.gather(
            *(
                client.get(
                    "/echo",
                    params={"value": f"req-{index}"},
                    headers={"x-request-id": f"request-{index}"},
                )
                for index in range(25)
            )
        )

    payloads = [response.json() for response in responses]
    assert {item["value"] for item in payloads} == {
        f"req-{index}" for index in range(25)
    }
    for item in payloads:
        assert item["state_value"] == item["value"]
        assert item["source"] == "api"
        assert item["request_id"] == item["value"].replace("req-", "request-")
