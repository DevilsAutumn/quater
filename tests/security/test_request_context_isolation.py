from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest

from quater import Quater, Request, TestClient
from quater.cli.main import main
from quater.protocol.actions import ACTIONS_RPC_PATH
from quater.testing import TestResponse
from tests.unit.cli.helpers import write_app


def _context_payload(request: Request) -> dict[str, str]:
    return {
        "source": request.context.source,
        "entrypoint": request.context.entrypoint,
    }


def _context_app() -> Quater:
    app = Quater()

    @app.post(
        "/context",
        tool=True,
        cli=True,
        description="Return the trusted request context.",
    )
    async def trusted_context(request: Request) -> dict[str, str]:
        return _context_payload(request)

    return app


def _spoof_headers() -> dict[str, str]:
    return {
        "source": "cli",
        "entrypoint": "local",
        "x-quater-source": "cli",
        "x-quater-entrypoint": "local",
    }


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _mcp_result_body(response: TestResponse) -> dict[str, object]:
    payload = _object(response.json())
    result = _object(payload["result"])
    content = result["content"]
    assert isinstance(content, list)
    first = _object(content[0])
    text = first["text"]
    assert isinstance(text, str)
    return _object(json.loads(text))


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


@pytest.mark.asyncio
async def test_http_caller_cannot_spoof_source_or_entrypoint() -> None:
    app = _context_app()

    async with TestClient(app) as client:
        response = await client.post(
            "/context",
            headers=_spoof_headers(),
            json={
                "source": "cli",
                "entrypoint": "local",
                "context": {"source": "cli", "entrypoint": "local"},
            },
        )

    assert response.status_code == 200
    assert response.json() == {"source": "api", "entrypoint": "server"}


@pytest.mark.asyncio
async def test_http_caller_cannot_spoof_source_to_mcp() -> None:
    app = _context_app()

    async with TestClient(app) as client:
        response = await client.post(
            "/context",
            headers={"source": "mcp", "x-quater-source": "mcp"},
            json={"source": "mcp", "context": {"source": "mcp"}},
        )

    assert response.status_code == 200
    assert response.json() == {"source": "api", "entrypoint": "server"}


@pytest.mark.asyncio
async def test_http_caller_cannot_spoof_source_with_invalid_value() -> None:
    app = _context_app()

    async with TestClient(app) as client:
        response = await client.post(
            "/context",
            headers={
                "source": "not-a-real-source",
                "x-quater-source": "not-a-real-source",
            },
            json={
                "source": "not-a-real-source",
                "context": {"source": "not-a-real-source", "entrypoint": "weird"},
            },
        )

    assert response.status_code == 200
    assert response.json() == {"source": "api", "entrypoint": "server"}


@pytest.mark.asyncio
async def test_mcp_caller_cannot_spoof_source_or_local_entrypoint() -> None:
    app = _context_app()

    async with TestClient(app) as client:
        response = await client.mcp.request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "source": "cli",
                "entrypoint": "local",
                "params": {
                    "name": "trusted_context",
                    "arguments": {},
                    "source": "cli",
                    "entrypoint": "local",
                    "_meta": {"source": "cli", "entrypoint": "local"},
                },
            },
            headers=_spoof_headers(),
        )

    assert response.status_code == 200
    assert _mcp_result_body(response) == {
        "source": "mcp",
        "entrypoint": "server",
    }


@pytest.mark.asyncio
async def test_remote_cli_caller_cannot_spoof_local_entrypoint() -> None:
    app = _context_app()

    async with TestClient(app) as client:
        response = await client.post(
            ACTIONS_RPC_PATH,
            headers=_spoof_headers(),
            json={
                "action": "trusted_context",
                "arguments": {},
                "source": "api",
                "entrypoint": "local",
                "context": {"source": "api", "entrypoint": "local"},
            },
        )

    assert response.status_code == 200
    payload = _object(response.json())
    assert payload["body"] == {"source": "cli", "entrypoint": "server"}


def test_local_cli_uses_local_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_app(
        tmp_path,
        """
        from quater import Quater, Request

        app = Quater()

        @app.post(
            "/context",
            cli=True,
            description="Return the trusted request context.",
        )
        async def trusted_context(request: Request) -> dict[str, str]:
            return {
                "source": request.context.source,
                "entrypoint": request.context.entrypoint,
            }
        """,
    )
    monkeypatch.chdir(tmp_path)

    code = main(["--app", "sample:app", "--json", "call", "trusted_context"])

    captured = capsys.readouterr()
    assert code == 0
    payload = _object(json.loads(captured.out))
    assert payload["body"] == {"source": "cli", "entrypoint": "local"}
