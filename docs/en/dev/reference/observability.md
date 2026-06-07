---
description: Reference for Quater access-log and MCP audit event types.
---

# Observability Reference

This page documents access-log and MCP audit event types.

## Prerequisites

Read [Security](/en/dev/security#request-ids-and-access-logs) and
[MCP](/en/dev/mcp#auditing). These hooks report framework events; they do
not replace auth or approval policy.

```python
from quater import AccessLogEvent, AccessLogHook, ToolAuditEvent
```

## AccessLogEvent {#symbol-accesslogevent}

Added in `0.1.0a1`.

Structured event emitted after Quater creates a response.

```python
AccessLogEvent(
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    source: RequestSource,
    entrypoint: RequestEntrypoint,
    scheme: str,
    client: str | None = None,
    tool_name: str | None = None,
    action_name: str | None = None,
)
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `request_id` | `str` | required | Correlation id. |
| `method` | `str` | required | HTTP method. |
| `path` | `str` | required | Request path. |
| `status_code` | `int` | required | Final response status. |
| `duration_ms` | `float` | required | Handler duration in milliseconds. |
| `source` | `"api" \| "mcp" \| "cli"` | required | Surface that reached Quater. |
| `entrypoint` | `"server" \| "local"` | required | Hosted or local CLI entrypoint. |
| `scheme` | `str` | required | Request scheme. |
| `client` | `str \| None` | `None` | Client address. |
| `tool_name` | `str \| None` | `None` | MCP tool name for tool calls. |
| `action_name` | `str \| None` | `None` | CLI action name for action calls. |

`to_dict()` returns a plain dictionary.

Example:

```python
from quater import AccessLogEvent, Quater


async def log_access(event: AccessLogEvent) -> None:
    print(event.to_dict())


app = Quater(access_logger=log_access)
```

Expected shape:

```json
{
  "request_id": "req_123",
  "method": "GET",
  "path": "/health",
  "status_code": 200,
  "duration_ms": 1.4,
  "source": "api",
  "entrypoint": "server",
  "scheme": "http",
  "client": "127.0.0.1",
  "tool_name": null,
  "action_name": null
}
```

## AccessLogHook {#symbol-accessloghook}

Added in `0.1.0a1`.

```python
AccessLogHook = Callable[[AccessLogEvent], Awaitable[None]]
```

If the hook raises, Quater suppresses the exception. Access logging should not
change the caller's response.

## ToolAuditEvent {#symbol-toolauditevent}

Added in `0.1.0a1`.

Structured event emitted for MCP tool calls.

```python
ToolAuditEvent(
    tool_name: str,
    subject: str | None,
    success: bool,
    duration_ms: float,
    arguments: Mapping[str, object],
)
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `tool_name` | `str` | required | Tool that was called. |
| `subject` | `str \| None` | required | Authenticated subject when present. |
| `success` | `bool` | required | Whether the call completed successfully. |
| `duration_ms` | `float` | required | Tool-call duration. |
| `arguments` | `Mapping[str, object]` | required | Redacted argument map. |

Example:

```python
from quater import ToolAuditEvent


async def audit_tool(event: ToolAuditEvent) -> None:
    print(event.tool_name, event.success)
```

If this hook raises, Quater returns a JSON-RPC internal error for that tool call.

## What Can Go Wrong

Access logs missing from local CLI
: `access_logger` is part of the server request path. Local CLI runs in process
  and does not represent a server access log.

MCP audit hook failure
: The tool call fails with a JSON-RPC internal error. Fix the audit hook or
  intentionally remove `mcp_audit`.

## Also See

- [Security](/en/dev/security): request ids and access logging.
- [MCP](/en/dev/mcp#auditing): MCP audit behavior.
- [Testing](/en/dev/testing): assert emitted events in app tests.
