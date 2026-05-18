"""MCP Streamable HTTP JSON response path."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from quater._finalize import move_response_finalizers, run_response_finalizers
from quater.actions.approval import ApprovalDeniedError, ApprovalRequiredError
from quater.config import AppConfig
from quater.exceptions import BadRequestError, HTTPError, RequestJSONError
from quater.request import Request
from quater.response import (
    EmptyResponse,
    JSONResponse,
    Response,
    StreamResponse,
    TextResponse,
)
from quater.tools.audit import AuditHook, ToolAuditEvent, sanitize_arguments
from quater.tools.registry import ToolDefinition, ToolRegistry
from quater.typing import ActionApproval, Authenticate, RequestContext, RequestSource

JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION_HEADER = "mcp-protocol-version"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
MAX_TOOL_RESPONSE_BYTES = 1024 * 1024

_REQUEST_METHODS = frozenset({"initialize", "tools/list", "tools/call"})
_NOTIFICATION_METHODS = frozenset({"notifications/initialized"})


class _ToolResponseTooLarge(Exception):
    pass


class _AuditHookError(Exception):
    def __init__(self, cause: Exception) -> None:
        self.cause = cause
        super().__init__("Audit hook failed")


async def mcp_request_context(request: Request) -> RequestContext:
    try:
        payload = await request.json()
    except RequestJSONError:
        return _mcp_context(request)

    if not isinstance(payload, Mapping):
        return _mcp_context(request)
    if payload.get("method") != "tools/call":
        return _mcp_context(request)

    params = payload.get("params")
    if not isinstance(params, Mapping):
        return _mcp_context(request)

    name = params.get("name")
    tool_name = name if isinstance(name, str) else None
    return _mcp_context(
        request,
        tool_name=tool_name,
        action_name=tool_name,
    )


def _mcp_context(
    request: Request,
    *,
    source: RequestSource = "mcp",
    tool_name: str | None = None,
    action_name: str | None = None,
) -> RequestContext:
    return replace(
        request.context,
        source=source,
        tool_name=tool_name,
        action_name=action_name,
    )


def validate_mcp_origin(request: Request, config: AppConfig) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        return

    allowed = config.mcp_allowed_origins
    if "*" in allowed or origin in allowed:
        return
    if not allowed and config.cors is not None:
        allowed = tuple(
            allowed_origin
            for allowed_origin in config.cors.allowed_origins
            if allowed_origin != "*"
        )
        if origin in allowed:
            return

    raise HTTPError("Invalid MCP Origin", status_code=403)


async def handle_mcp_request(
    request: Request,
    registry: ToolRegistry,
    *,
    transport_auth: Authenticate | None = None,
    approval_hook: ActionApproval | None = None,
    audit_hook: AuditHook | None = None,
    debug: bool = False,
    max_response_size: int = MAX_TOOL_RESPONSE_BYTES,
) -> Response:
    if request.method != "POST":
        return TextResponse(
            "Method Not Allowed",
            status_code=405,
            headers={"allow": "POST"},
        )
    protocol_error = _validate_protocol_version_header(request)
    if protocol_error is not None:
        return protocol_error

    try:
        payload = await _json_rpc_payload(request)
    except _JSONRPCError as exc:
        return _json_rpc_error(exc.request_id, exc.code, exc.message)

    method = payload.get("method")
    if payload.get("jsonrpc") != JSONRPC_VERSION or not isinstance(method, str):
        return _json_rpc_error(payload.get("id"), -32600, "Invalid Request")

    if "id" not in payload:
        if method in _NOTIFICATION_METHODS:
            return EmptyResponse(status_code=202)
        if method in _REQUEST_METHODS:
            return _json_rpc_error(None, -32600, "Invalid Request")
        return EmptyResponse(status_code=202)

    request_id = payload.get("id")
    if not _is_request_id(request_id):
        return _json_rpc_error(None, -32600, "Invalid Request")

    if method == "initialize":
        try:
            result = _initialize_result(payload.get("params"))
        except _JSONRPCError as exc:
            return _json_rpc_error(request_id, exc.code, exc.message)
        return _json_rpc_result(request_id, result)
    if method == "tools/list":
        return _json_rpc_result(request_id, {"tools": registry.list_tools()})
    if method == "tools/call":
        return await _handle_tools_call(
            request,
            request_id,
            payload.get("params"),
            registry,
            transport_auth=transport_auth,
            approval_hook=approval_hook,
            audit_hook=audit_hook,
            debug=debug,
            max_response_size=max_response_size,
        )
    return _json_rpc_error(request_id, -32601, "Method not found")


async def _json_rpc_payload(request: Request) -> Mapping[str, object]:
    try:
        payload = await request.json()
    except RequestJSONError:
        raise _JSONRPCError(None, -32700, "Parse error") from None
    if not isinstance(payload, Mapping):
        raise _JSONRPCError(None, -32600, "Invalid Request")
    return cast(Mapping[str, object], payload)


def _validate_protocol_version_header(request: Request) -> Response | None:
    value = request.headers.get(MCP_PROTOCOL_VERSION_HEADER)
    if value is None or value in SUPPORTED_PROTOCOL_VERSIONS:
        return None
    return TextResponse("Unsupported MCP protocol version", status_code=400)


def _is_request_id(value: object) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, str | int)


def _initialize_result(params: object) -> dict[str, object]:
    if not isinstance(params, Mapping):
        raise _JSONRPCError(None, -32602, "Invalid params")

    requested_version = params.get("protocolVersion")
    client_capabilities = params.get("capabilities")
    client_info = params.get("clientInfo")
    if (
        not isinstance(requested_version, str)
        or not isinstance(client_capabilities, Mapping)
        or not isinstance(client_info, Mapping)
        or not isinstance(client_info.get("name"), str)
        or not isinstance(client_info.get("version"), str)
    ):
        raise _JSONRPCError(None, -32602, "Invalid params")

    return {
        "protocolVersion": _negotiate_protocol_version(requested_version),
        "capabilities": {"tools": {}},
        "serverInfo": _server_info(),
    }


def _negotiate_protocol_version(requested_version: str) -> str:
    if requested_version in SUPPORTED_PROTOCOL_VERSIONS:
        return requested_version
    return LATEST_PROTOCOL_VERSION


def _server_info() -> dict[str, str]:
    from quater import __version__

    return {
        "name": "quater",
        "title": "Quater",
        "version": __version__,
    }


async def _handle_tools_call(
    request: Request,
    request_id: object,
    params: object,
    registry: ToolRegistry,
    *,
    transport_auth: Authenticate | None,
    approval_hook: ActionApproval | None,
    audit_hook: AuditHook | None,
    debug: bool,
    max_response_size: int,
) -> Response:
    if not isinstance(params, Mapping):
        return _json_rpc_error(request_id, -32602, "Invalid params")

    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not isinstance(arguments, Mapping):
        return _json_rpc_error(request_id, -32602, "Invalid params")

    tool = registry.get(name)
    if tool is None:
        return _json_rpc_error(request_id, -32602, "Unknown tool")

    try:
        approval_token = _approval_token(params)
    except _JSONRPCError as exc:
        return _json_rpc_error(request_id, exc.code, exc.message)

    try:
        return await _call_tool_with_audit(
            request,
            request_id,
            name,
            arguments,
            tool,
            transport_auth=transport_auth,
            approval_hook=approval_hook,
            approval_token=approval_token,
            audit_hook=audit_hook,
            debug=debug,
            max_response_size=max_response_size,
        )
    except _AuditHookError as exc:
        return _json_rpc_error(
            request_id,
            -32603,
            _audit_hook_error_message(exc, debug=debug),
        )


async def _call_tool_with_audit(
    request: Request,
    request_id: object,
    name: str,
    arguments: Mapping[object, object],
    tool: ToolDefinition,
    *,
    transport_auth: Authenticate | None,
    approval_hook: ActionApproval | None,
    approval_token: str | None,
    audit_hook: AuditHook | None,
    debug: bool,
    max_response_size: int,
) -> Response:
    start = time.perf_counter()
    typed_arguments = cast(Mapping[str, object], arguments)
    response: Response | None = None
    try:
        response = await tool.call(
            request,
            typed_arguments,
            authenticated_by=transport_auth,
            approval_hook=approval_hook,
            approval_token=approval_token,
            debug=debug,
        )
    except BadRequestError as exc:
        await _audit(
            audit_hook,
            request,
            name,
            typed_arguments,
            success=False,
            start=start,
        )
        return _json_rpc_error(request_id, -32602, exc.detail)
    except ApprovalRequiredError as exc:
        await _audit(
            audit_hook,
            request,
            name,
            typed_arguments,
            success=False,
            start=start,
        )
        return _json_rpc_error(
            request_id,
            -32001,
            "Approval required",
            data={
                "code": "approval_required",
                "action": exc.action,
                "arguments_hash": exc.arguments_hash,
            },
        )
    except ApprovalDeniedError as exc:
        await _audit(
            audit_hook,
            request,
            name,
            typed_arguments,
            success=False,
            start=start,
        )
        return _json_rpc_error(
            request_id,
            -32002,
            "Approval denied",
            data={
                "code": "approval_denied",
                "action": exc.action,
                "arguments_hash": exc.arguments_hash,
            },
        )
    except HTTPError as exc:
        await _audit(
            audit_hook,
            request,
            name,
            typed_arguments,
            success=False,
            start=start,
        )
        return _json_rpc_result(request_id, _tool_result(exc.detail, is_error=True))
    except Exception as exc:
        await _audit(
            audit_hook,
            request,
            name,
            typed_arguments,
            success=False,
            start=start,
        )
        detail = f"{type(exc).__name__}: {exc}" if debug else "Tool call failed"
        return _json_rpc_result(request_id, _tool_result(detail, is_error=True))

    if response is None:
        return _json_rpc_error(request_id, -32603, "Tool call failed")

    success = response.status_code < 400
    try:
        result = await _tool_result_response(
            response,
            is_error=not success,
            max_response_size=max_response_size,
        )
    except _ToolResponseTooLarge:
        try:
            await _audit(
                audit_hook,
                request,
                name,
                typed_arguments,
                success=False,
                start=start,
            )
        except Exception:
            await run_response_finalizers(response)
            raise
        error_response = _json_rpc_result(
            request_id,
            _tool_result("Tool response too large", is_error=True),
        )
        return move_response_finalizers(response, error_response)

    try:
        await _audit(
            audit_hook,
            request,
            name,
            typed_arguments,
            success=success,
            start=start,
        )
    except Exception:
        await run_response_finalizers(response)
        raise

    return move_response_finalizers(response, _json_rpc_result(request_id, result))


def _approval_token(params: Mapping[str, object]) -> str | None:
    meta = params.get("_meta")
    if meta is None:
        return None
    if not isinstance(meta, Mapping):
        raise _JSONRPCError(None, -32602, "Invalid params")

    value = meta.get("approvalToken", meta.get("approval_token"))
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _JSONRPCError(None, -32602, "Invalid approval token")
    return value


async def _tool_result_response(
    response: Response,
    *,
    is_error: bool,
    max_response_size: int = MAX_TOOL_RESPONSE_BYTES,
) -> dict[str, object]:
    if isinstance(response, StreamResponse):
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.body_iterator:
            size += len(chunk)
            if size > max_response_size:
                raise _ToolResponseTooLarge
            chunks.append(chunk)
        text = b"".join(chunks).decode("utf-8", errors="replace")
    else:
        if len(response.body) > max_response_size:
            raise _ToolResponseTooLarge
        text = response.body.decode("utf-8", errors="replace")
    return _tool_result(text, is_error=is_error)


def _tool_result(text: str, *, is_error: bool) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


async def _audit(
    audit_hook: AuditHook | None,
    request: Request,
    tool_name: str,
    arguments: Mapping[str, object],
    *,
    success: bool,
    start: float,
) -> None:
    if audit_hook is None:
        return

    event = ToolAuditEvent(
        tool_name=tool_name,
        subject=request.auth.subject if request.auth is not None else None,
        success=success,
        duration_ms=(time.perf_counter() - start) * 1000,
        arguments=sanitize_arguments(arguments),
    )
    try:
        await audit_hook(event)
    except Exception as exc:
        raise _AuditHookError(exc) from exc


def _audit_hook_error_message(error: _AuditHookError, *, debug: bool) -> str:
    if not debug:
        return "Audit hook failed"
    return f"Audit hook failed: {type(error.cause).__name__}: {error.cause}"


def _json_rpc_result(request_id: object, result: object) -> JSONResponse:
    return JSONResponse(
        {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": result,
        }
    )


def _json_rpc_error(
    request_id: object,
    code: int,
    message: str,
    *,
    data: object | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JSONResponse(
        {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": error,
        }
    )


class _JSONRPCError(Exception):
    def __init__(self, request_id: object, code: int, message: str) -> None:
        self.request_id = request_id
        self.code = code
        self.message = message
        super().__init__(message)
