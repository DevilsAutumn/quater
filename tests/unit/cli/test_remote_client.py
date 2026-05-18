from __future__ import annotations

from email.message import Message
from io import BytesIO
from typing import Protocol
from urllib.error import HTTPError, URLError

import pytest

from quater.cli.client import (
    MAX_REMOTE_RESPONSE_BYTES,
    RemoteClientError,
    RemoteResponse,
    _read_limited_body,
    _remote_url,
    _request_json,
    call_action,
    fetch_manifest,
)
from quater.cli.errors import CLIUsageError
from quater.serialization import loads_json


class BuiltURLRequest(Protocol):
    data: bytes | None
    full_url: str

    def get_method(self) -> str: ...

    def header_items(self) -> list[tuple[str, str]]: ...


class OversizedResponse:
    def read(self, size: int = -1) -> bytes:
        assert size == MAX_REMOTE_RESPONSE_BYTES + 1
        return b"x" * size


class FakeHTTPResponse:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


def test_fetch_manifest_rejects_http_error_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request_json(
        method: str,
        url: str,
        *,
        token: str | None,
        body: bytes | None = None,
    ) -> RemoteResponse:
        return RemoteResponse(
            status_code=401,
            body={"ok": False, "error": {"code": "unauthorized"}},
        )

    monkeypatch.setattr("quater.cli.client._request_json", fake_request_json)

    with pytest.raises(RemoteClientError, match="401"):
        fetch_manifest("https://api.example.com", token="bad-token")


def test_fetch_manifest_rejects_non_quater_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request_json(
        method: str,
        url: str,
        *,
        token: str | None,
        body: bytes | None = None,
    ) -> RemoteResponse:
        return RemoteResponse(status_code=200, body={"status": "ok"})

    monkeypatch.setattr("quater.cli.client._request_json", fake_request_json)

    with pytest.raises(RemoteClientError, match="manifest is invalid"):
        fetch_manifest("https://api.example.com", token="secret")


def test_remote_client_rejects_oversized_responses() -> None:
    with pytest.raises(RemoteClientError, match="too large"):
        _read_limited_body(OversizedResponse())


def test_call_action_sends_json_payload_and_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, object]] = []

    def fake_urlopen(request: BuiltURLRequest, timeout: int) -> FakeHTTPResponse:
        method = request.get_method()
        headers = {key.lower(): value for key, value in request.header_items()}
        assert request.data is not None
        payload = loads_json(request.data)
        seen.append(
            {
                "url": request.full_url,
                "method": method,
                "timeout": timeout,
                "headers": headers,
                "payload": payload,
            }
        )
        return FakeHTTPResponse(b'{"ok": true, "body": {"accepted": true}}')

    monkeypatch.setattr("quater.cli.client.urlopen", fake_urlopen)

    response = call_action(
        "https://api.example.com/",
        token="secret",
        action="orders.ship",
        arguments={"order_id": "ord_1001"},
        dry_run=True,
        approval_token="approval-123",
    )

    assert response.status_code == 200
    assert response.body == {"ok": True, "body": {"accepted": True}}
    assert seen == [
        {
            "url": "https://api.example.com/__quater__/actions/call",
            "method": "POST",
            "timeout": 10,
            "headers": {
                "accept": "application/json",
                "user-agent": "quater-cli",
                "content-type": "application/json",
                "authorization": "Bearer secret",
            },
            "payload": {
                "action": "orders.ship",
                "arguments": {"order_id": "ord_1001"},
                "dry_run": True,
                "approval_token": "approval-123",
            },
        }
    ]


def test_request_json_accepts_json_error_bodies_from_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: BuiltURLRequest, timeout: int) -> FakeHTTPResponse:
        raise HTTPError(
            request.full_url,
            404,
            "Not Found",
            hdrs=Message(),
            fp=BytesIO(b'{"ok": false, "error": {"code": "missing"}}'),
        )

    monkeypatch.setattr("quater.cli.client.urlopen", fake_urlopen)

    response = _request_json(
        "GET",
        "https://api.example.com/.well-known/quater-actions.json",
        token=None,
    )

    assert response.status_code == 404
    assert response.body == {"ok": False, "error": {"code": "missing"}}


def test_request_json_rejects_network_errors_non_json_and_non_object_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def network_error(request: BuiltURLRequest, timeout: int) -> FakeHTTPResponse:
        raise URLError("connection refused")

    monkeypatch.setattr("quater.cli.client.urlopen", network_error)
    with pytest.raises(RemoteClientError, match="Remote request failed"):
        _request_json(
            "GET",
            "https://api.example.com/.well-known/quater-actions.json",
            token=None,
        )

    monkeypatch.setattr(
        "quater.cli.client.urlopen",
        lambda request, timeout: FakeHTTPResponse(b"not-json"),
    )
    with pytest.raises(RemoteClientError, match="non-JSON"):
        _request_json(
            "GET",
            "https://api.example.com/.well-known/quater-actions.json",
            token=None,
        )

    monkeypatch.setattr(
        "quater.cli.client.urlopen",
        lambda request, timeout: FakeHTTPResponse(b'["not", "an", "object"]'),
    )
    with pytest.raises(RemoteClientError, match="invalid JSON response"):
        _request_json(
            "GET",
            "https://api.example.com/.well-known/quater-actions.json",
            token=None,
        )


def test_remote_client_revalidates_base_url_before_request_building() -> None:
    assert _remote_url("https://api.example.com/", "/health") == (
        "https://api.example.com/health"
    )

    with pytest.raises(CLIUsageError, match="absolute http"):
        _remote_url("file:///tmp/actions.json", "/health")
