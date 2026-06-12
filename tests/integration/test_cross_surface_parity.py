from __future__ import annotations

import asyncio
import json
import sys
import types
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import msgspec
import pytest

from quater import (
    AuthConfig,
    Cookie,
    Header,
    Quater,
    Request,
    Response,
    TestClient,
    TextResponse,
)
from quater.cli.main import main as cli_main
from quater.typing import AuthContext

ACTION_NAME = "update_inventory"
AUTH_TOKEN = "surface-token"
QueryValue = str | int | float | bool
ARGUMENT_ORDER = (
    "item_id",
    "payload",
    "active",
    "ratio",
    "count",
    "operator",
    "session_id",
    "note",
    "limit",
)


class InventoryPayload(msgspec.Struct):
    name: str
    quantity: int


@dataclass(slots=True, frozen=True)
class SurfaceResult:
    ok: bool
    body: object | None = None
    message: str | None = None


def make_parity_app() -> tuple[Quater, list[object]]:
    calls: list[object] = []

    async def authenticate(request: Request) -> AuthContext | None:
        if request.headers.get("authorization") != f"Bearer {AUTH_TOKEN}":
            return None
        return AuthContext(subject=request.context.source)

    app = Quater(
        auth=[AuthConfig(authenticate, surfaces=["api", "mcp", "cli"])],
    )

    @app.exception_handler(RuntimeError)
    async def map_runtime_error(
        request: Request,
        exc: Exception,
    ) -> Response | None:
        return TextResponse("mapped handler error", status_code=418)

    @app.post(
        "/inventory/{item_id:int}",
        tool=True,
        cli=True,
        description="Update one inventory item.",
    )
    async def update_inventory(
        item_id: int,
        payload: InventoryPayload,
        active: bool,
        ratio: float,
        count: int,
        operator: str = Header(alias="X-Operator"),
        session_id: str = Cookie(alias="session_id"),
        note: str | None = None,
        limit: int = 25,
    ) -> dict[str, object]:
        if note == "explode":
            calls.append("explode")
            raise RuntimeError("database password leaked")

        result = {
            "item_id": item_id,
            "payload": {
                "name": payload.name,
                "quantity": payload.quantity,
            },
            "active": active,
            "ratio": ratio,
            "count": count,
            "operator": operator,
            "session_id": session_id,
            "note": note,
            "limit": limit,
        }
        calls.append(result)
        return result

    return app, calls


def valid_arguments(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "item_id": 7,
        "payload": {"name": "chai", "quantity": 3},
        "active": True,
        "ratio": 2.5,
        "count": 4,
        "operator": "ops-1",
        "session_id": "sess-1",
    }
    arguments.update(overrides)
    return arguments


def register_app_module(
    monkeypatch: pytest.MonkeyPatch,
    app: Quater,
) -> str:
    module_name = f"_quater_parity_app_{id(app)}"
    module = cast(Any, types.ModuleType(module_name))
    module.app = app
    monkeypatch.setitem(sys.modules, module_name, module)
    return f"{module_name}:app"


def run(coro: Any) -> Any:
    return asyncio.run(coro)


async def call_http(
    app: Quater,
    arguments: Mapping[str, object],
    *,
    extra_request_values: bool = False,
) -> SurfaceResult:
    path = f"/inventory/{arguments.get('item_id', 7)}"
    params: dict[str, QueryValue] = {}
    for name in ("active", "ratio", "count", "note", "limit"):
        if name in arguments and arguments[name] is not None:
            params[name] = _query_value(arguments[name])
    headers = {"authorization": f"Bearer {AUTH_TOKEN}"}
    if "operator" in arguments:
        headers["X-Operator"] = str(arguments["operator"])
    cookies: dict[str, str] = {}
    if "session_id" in arguments:
        cookies["session_id"] = str(arguments["session_id"])
    if extra_request_values:
        params["unknown_query"] = "ignored"
        headers["X-Unknown"] = "ignored"
        cookies["unknown_cookie"] = "ignored"

    response = await TestClient(app).post(
        path,
        params=params,
        headers=headers,
        cookies=cookies,
        json=arguments.get("payload"),
    )
    return normalize_http(response)


async def call_mcp(app: Quater, arguments: Mapping[str, object]) -> SurfaceResult:
    response = await TestClient(app).mcp.tools_call(
        ACTION_NAME,
        arguments,
        token=AUTH_TOKEN,
    )
    payload = response.json()
    if "error" in payload:
        error = payload["error"]
        assert isinstance(error, dict)
        return SurfaceResult(ok=False, message=str(error["message"]))

    result = payload["result"]
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, list)
    text = content[0]["text"]
    body = parse_json_text(str(text))
    if result["isError"]:
        return SurfaceResult(ok=False, message=str(body))
    return SurfaceResult(ok=True, body=body)


def call_local_cli(
    module_target: str,
    arguments: Mapping[str, object],
    capsys: pytest.CaptureFixture[str],
) -> SurfaceResult:
    capsys.readouterr()
    code = cli_main(
        [
            "--app",
            module_target,
            "--json",
            "--token",
            AUTH_TOKEN,
            "call",
            ACTION_NAME,
            *_cli_argument_flags(arguments),
        ]
    )
    captured = capsys.readouterr()
    if captured.out:
        payload = json.loads(captured.out)
        assert code == (0 if payload.get("ok") else 1)
        return normalize_action_payload(payload)

    assert code != 0
    return SurfaceResult(ok=False, message=captured.err.strip())


async def call_remote_cli(
    app: Quater,
    arguments: Mapping[str, object],
) -> SurfaceResult:
    response = await TestClient(app).cli.call(
        ACTION_NAME,
        arguments,
        token=AUTH_TOKEN,
    )
    return normalize_action_payload(response.json())


def call_all_surfaces(
    app: Quater,
    module_target: str,
    arguments: Mapping[str, object],
    capsys: pytest.CaptureFixture[str],
) -> dict[str, SurfaceResult]:
    return {
        "http": run(call_http(app, arguments)),
        "mcp": run(call_mcp(app, arguments)),
        "local_cli": call_local_cli(module_target, arguments, capsys),
        "remote_cli": run(call_remote_cli(app, arguments)),
    }


def normalize_http(response: Any) -> SurfaceResult:
    body = parse_response_body(response)
    if response.status_code < 400:
        return SurfaceResult(ok=True, body=body)
    return SurfaceResult(ok=False, message=str(body))


def normalize_action_payload(payload: Mapping[str, object]) -> SurfaceResult:
    if payload.get("ok") is True:
        return SurfaceResult(ok=True, body=payload["body"])
    if "body" in payload:
        return SurfaceResult(ok=False, message=str(payload["body"]))

    error = payload["error"]
    assert isinstance(error, dict)
    return SurfaceResult(ok=False, message=str(error["message"]))


def parse_response_body(response: Any) -> object:
    try:
        return response.json()
    except Exception:
        return response.text


def parse_json_text(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _cli_argument_flags(arguments: Mapping[str, object]) -> list[str]:
    flags: list[str] = []
    ordered_names = [
        *ARGUMENT_ORDER,
        *sorted(set(arguments) - set(ARGUMENT_ORDER)),
    ]
    for name in ordered_names:
        if name not in arguments:
            continue
        flags.extend(
            [f"--{name.replace('_', '-')}", _cli_argument_value(arguments[name])]
        )
    return flags


def _query_value(value: object) -> QueryValue:
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _cli_argument_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, dict | list):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            valid_arguments(),
            {
                "item_id": 7,
                "payload": {"name": "chai", "quantity": 3},
                "active": True,
                "ratio": 2.5,
                "count": 4,
                "operator": "ops-1",
                "session_id": "sess-1",
                "note": None,
                "limit": 25,
            },
        ),
        (
            valid_arguments(note="fragile", limit=10),
            {
                "item_id": 7,
                "payload": {"name": "chai", "quantity": 3},
                "active": True,
                "ratio": 2.5,
                "count": 4,
                "operator": "ops-1",
                "session_id": "sess-1",
                "note": "fragile",
                "limit": 10,
            },
        ),
    ],
    ids=["defaults", "optional-values"],
)
def test_declared_inputs_bind_identically_across_surfaces(
    arguments: dict[str, object],
    expected: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app, calls = make_parity_app()
    module_target = register_app_module(monkeypatch, app)

    results = call_all_surfaces(app, module_target, arguments, capsys)

    assert results == {
        "http": SurfaceResult(ok=True, body=expected),
        "mcp": SurfaceResult(ok=True, body=expected),
        "local_cli": SurfaceResult(ok=True, body=expected),
        "remote_cli": SurfaceResult(ok=True, body=expected),
    }
    assert calls == [expected, expected, expected, expected]


@pytest.mark.parametrize("item_id", ["-5", "+7", "1_000", "١٢٣"])
def test_int_path_params_reject_non_canonical_values_across_surfaces(
    item_id: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app, calls = make_parity_app()
    module_target = register_app_module(monkeypatch, app)

    results = call_all_surfaces(
        app,
        module_target,
        valid_arguments(item_id=item_id),
        capsys,
    )

    assert {surface: result.ok for surface, result in results.items()} == {
        "http": False,
        "mcp": False,
        "local_cli": False,
        "remote_cli": False,
    }
    assert {surface: result.message for surface, result in results.items()} == {
        "http": f"Not found: /inventory/{item_id}",
        "mcp": "Invalid path argument: item_id",
        "local_cli": "Invalid path argument: item_id",
        "remote_cli": "Invalid path argument: item_id",
    }
    assert calls == []


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {
                key: value
                for key, value in valid_arguments().items()
                if key != "operator"
            },
            "Missing required header: X-Operator",
        ),
        (
            {
                key: value
                for key, value in valid_arguments().items()
                if key != "session_id"
            },
            "Missing required cookie: session_id",
        ),
        (
            {
                key: value
                for key, value in valid_arguments().items()
                if key != "payload"
            },
            "Missing required body parameter: payload",
        ),
        (
            valid_arguments(payload={"name": "chai"}),
            "Invalid JSON body for parameter: payload",
        ),
    ],
    ids=[
        "missing-header",
        "missing-cookie",
        "missing-body",
        "invalid-body",
    ],
)
def test_declared_input_errors_match_across_surfaces(
    arguments: dict[str, object],
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app, calls = make_parity_app()
    module_target = register_app_module(monkeypatch, app)

    results = call_all_surfaces(app, module_target, arguments, capsys)

    assert {surface: result.ok for surface, result in results.items()} == {
        "http": False,
        "mcp": False,
        "local_cli": False,
        "remote_cli": False,
    }
    assert {surface: result.message for surface, result in results.items()} == {
        "http": message,
        "mcp": message,
        "local_cli": message,
        "remote_cli": message,
    }
    assert calls == []


@pytest.mark.parametrize(
    ("arguments", "http_message", "agent_message"),
    [
        (
            {key: value for key, value in valid_arguments().items() if key != "active"},
            "Missing required query parameter: active",
            "Missing required parameter: active",
        ),
        (
            valid_arguments(count="many"),
            "Invalid integer query parameter: count",
            "Invalid integer parameter: count",
        ),
        (
            valid_arguments(ratio="wide"),
            "Invalid float query parameter: ratio",
            "Invalid float parameter: ratio",
        ),
        (
            valid_arguments(active="sometimes"),
            "Invalid boolean query parameter: active",
            "Invalid boolean parameter: active",
        ),
    ],
    ids=["missing-query", "invalid-int", "invalid-float", "invalid-bool"],
)
def test_query_param_errors_drop_query_vocabulary_off_http(
    arguments: dict[str, object],
    http_message: str,
    agent_message: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Scalar params bind from the query string, so HTTP keeps "query parameter",
    # but MCP and CLI callers have no query string — they get neutral "parameter".
    app, calls = make_parity_app()
    module_target = register_app_module(monkeypatch, app)

    results = call_all_surfaces(app, module_target, arguments, capsys)

    assert {surface: result.ok for surface, result in results.items()} == {
        "http": False,
        "mcp": False,
        "local_cli": False,
        "remote_cli": False,
    }
    assert {surface: result.message for surface, result in results.items()} == {
        "http": http_message,
        "mcp": agent_message,
        "local_cli": agent_message,
        "remote_cli": agent_message,
    }
    assert calls == []


def test_mapped_handler_errors_match_across_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app, calls = make_parity_app()
    module_target = register_app_module(monkeypatch, app)

    results = call_all_surfaces(
        app,
        module_target,
        valid_arguments(note="explode"),
        capsys,
    )

    assert {surface: result.ok for surface, result in results.items()} == {
        "http": False,
        "mcp": False,
        "local_cli": False,
        "remote_cli": False,
    }
    assert {surface: result.message for surface, result in results.items()} == {
        "http": "mapped handler error",
        "mcp": "mapped handler error",
        "local_cli": "mapped handler error",
        "remote_cli": "mapped handler error",
    }
    assert "database password" not in json.dumps(
        {surface: result.message for surface, result in results.items()}
    )
    assert calls == ["explode", "explode", "explode", "explode"]


def test_unknown_extras_follow_the_surface_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app, calls = make_parity_app()
    module_target = register_app_module(monkeypatch, app)
    expected_body = {
        "item_id": 7,
        "payload": {"name": "chai", "quantity": 3},
        "active": True,
        "ratio": 2.5,
        "count": 4,
        "operator": "ops-1",
        "session_id": "sess-1",
        "note": None,
        "limit": 25,
    }

    http_result = run(call_http(app, valid_arguments(), extra_request_values=True))
    action_arguments = valid_arguments(extra="reject-me")
    action_results = {
        "mcp": run(call_mcp(app, action_arguments)),
        "local_cli": call_local_cli(module_target, action_arguments, capsys),
        "remote_cli": run(call_remote_cli(app, action_arguments)),
    }

    assert http_result == SurfaceResult(ok=True, body=expected_body)
    assert {surface: result.message for surface, result in action_results.items()} == {
        "mcp": "Unknown action argument: extra",
        "local_cli": "Unknown action argument: extra",
        "remote_cli": "Unknown action argument: extra",
    }
    assert calls == [expected_body]
