"""HTTP client for Quater remote action servers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request as URLRequest
from urllib.request import urlopen

from quater.cli.errors import CLIError
from quater.cli.remotes import validate_remote_url
from quater.exceptions import RequestJSONError
from quater.protocol.actions import (
    ACTIONS_MANIFEST_PATH,
    ACTIONS_PROTOCOL,
    ACTIONS_RPC_PATH,
)
from quater.serialization import dumps_json, loads_json

DEFAULT_TIMEOUT_SECONDS = 10
MAX_REMOTE_RESPONSE_BYTES = 5 * 1024 * 1024


class RemoteClientError(CLIError):
    pass


class _ReadableResponse(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


@dataclass(slots=True, frozen=True)
class RemoteResponse:
    status_code: int
    body: dict[str, object]


def fetch_manifest(base_url: str, *, token: str | None) -> dict[str, object]:
    response = _request_json(
        "GET",
        _remote_url(base_url, ACTIONS_MANIFEST_PATH),
        token=token,
    )
    if response.status_code >= 400:
        message = f"Remote manifest request failed ({response.status_code})"
        raise RemoteClientError(message)
    _validate_manifest(response.body)
    return response.body


def call_action(
    base_url: str,
    *,
    token: str | None,
    action: str,
    arguments: dict[str, object],
    dry_run: bool,
    approval_token: str | None,
) -> RemoteResponse:
    payload: dict[str, object] = {
        "action": action,
        "arguments": arguments,
        "dry_run": dry_run,
    }
    if approval_token is not None:
        payload["approval_token"] = approval_token

    return _request_json(
        "POST",
        _remote_url(base_url, ACTIONS_RPC_PATH),
        token=token,
        body=dumps_json(payload),
    )


def _request_json(
    method: str,
    url: str,
    *,
    token: str | None,
    body: bytes | None = None,
) -> RemoteResponse:
    headers = {
        "accept": "application/json",
        "user-agent": "quater-cli",
    }
    if body is not None:
        headers["content-type"] = "application/json"
    if token is not None:
        headers["authorization"] = f"Bearer {token}"

    request = URLRequest(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:  # nosec B310
            status_code = response.status
            raw_body = _read_limited_body(response)
    except HTTPError as exc:
        status_code = exc.code
        raw_body = _read_limited_body(exc)
    except URLError as exc:
        raise RemoteClientError("Remote request failed") from exc

    try:
        decoded = loads_json(raw_body)
    except RequestJSONError as exc:
        message = f"Remote returned non-JSON response ({status_code})"
        raise RemoteClientError(message) from exc
    if not isinstance(decoded, dict):
        raise RemoteClientError("Remote returned invalid JSON response")
    return RemoteResponse(
        status_code=status_code,
        body=cast(dict[str, object], decoded),
    )


def _validate_manifest(manifest: dict[str, object]) -> None:
    if manifest.get("protocol") != ACTIONS_PROTOCOL:
        raise RemoteClientError("Remote manifest is invalid")
    if not isinstance(manifest.get("actions"), list):
        raise RemoteClientError("Remote manifest is invalid")


def _read_limited_body(response: _ReadableResponse) -> bytes:
    body = response.read(MAX_REMOTE_RESPONSE_BYTES + 1)
    if len(body) > MAX_REMOTE_RESPONSE_BYTES:
        raise RemoteClientError("Remote response is too large")
    return body


def _remote_url(base_url: str, path: str) -> str:
    validated_base_url = validate_remote_url(base_url)
    return urljoin(validated_base_url.rstrip("/") + "/", path.lstrip("/"))
