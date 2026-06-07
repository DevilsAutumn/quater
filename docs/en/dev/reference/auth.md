---
description: Reference for Quater auth hook types, approval hooks, framework errors, and signed cookies.
---

# Auth And Security Reference

This page documents auth hook types, approval hooks, framework errors, and
signed cookies.

## Prerequisites

Read [Security](/en/dev/security). Auth hooks are your application policy;
Quater only defines when they run and what they receive.

```python
from quater import (
    ActionApproval,
    ApprovalRequest,
    AuthConfig,
    AuthContext,
    HTTPError,
    ImproperlyConfigured,
    SignedCookieSigner,
)
```

## AuthConfig {#symbol-authconfig}

Added in `0.1.0b1`.

One authenticator bound to one or more request surfaces. Pass a list to
`Quater(auth=[...])`; exactly one runs per request, chosen by source.

```python
AuthConfig(authenticator: Authenticator, *, surfaces: Iterable[str], name: str | None = None)
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `authenticator` | [`Authenticator`](#symbol-authenticator) | required | Receives the `Request`; use `await request.resolve(resource)` after cheap checks when auth needs a resource. |
| `surfaces` | `Iterable[str]` | required | Surfaces this covers: any of `"api"`, `"mcp"`, `"cli"`. Each surface may be covered by at most one `AuthConfig`. |
| `name` | `str \| None` | `None` | Optional name used in diagnostics. |

```python
from quater import AuthConfig, AuthContext, Quater, Request


async def authenticate(request: Request) -> AuthContext | None:
    if request.headers.get("authorization") != "Bearer demo-token":
        return None
    return AuthContext(subject="user_123")


app = Quater(auth=[AuthConfig(authenticate, surfaces=["api", "mcp", "cli"])])
```

## AuthContext {#symbol-authcontext}

Added in `0.1.0a1`. `payload` added in `0.1.0b1`.

Authenticated identity returned by an authenticator.

```python
AuthContext(
    subject: str,
    metadata: Mapping[str, object] = {},
    payload: object = None,
)
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `subject` | `str` | required | Stable user, service, or agent id. |
| `metadata` | `Mapping[str, object]` | empty read-only mapping | Small request-scoped values your app wants to carry. |
| `payload` | `object` | `None` | An app object the authenticator already loaded (for example the `User` row), read back by a handler through a resource with no second query. Quater never inspects it. |

Example:

```python
from quater import AuthContext, Request


async def authenticate(request: Request) -> AuthContext | None:
    if request.headers.get("authorization") != "Bearer demo-token":
        return None
    return AuthContext(subject="user_123")
```

## ApprovalRequest {#symbol-approvalrequest}

Added in `0.1.0a1`.

Input passed to `action_approval` for protected MCP tools and CLI actions.

```python
ApprovalRequest(
    action: str,
    arguments_hash: str,
    token: str,
    auth: AuthContext | None = None,
    context: RequestContext = RequestContext(),
)
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `action` | `str` | required | Tool or CLI action name. |
| `arguments_hash` | `str` | required | SHA-256 hash of the action name and canonical bound arguments. |
| `token` | `str` | required | Submitted approval token. |
| `auth` | [`AuthContext`](#symbol-authcontext) \| None | `None` | Authenticated caller when available. |
| `context` | `RequestContext` | `RequestContext()` | Source and entrypoint metadata. |

## ActionApproval {#symbol-actionapproval}

Added in `0.1.0a1`.

Callable type for approval hooks.

```python
ActionApproval = Callable[[ApprovalRequest], Awaitable[bool]]
```

Return `True` to allow execution. Return `False` to deny it.

## Authenticator {#symbol-authenticator}

Added in `0.1.0b1`.

Callable type for an authenticator. It receives the `Request`; resource
parameters are rejected so no-token requests can fail before opening a database
session. Use `await request.resolve(resource)` after cheap checks when auth
needs a resource. Handlers can inject that same resource through
`Annotated[T, resource]`.

```python
Authenticator = Callable[[Request], Awaitable[AuthContext | None]]
```

Return `AuthContext` to allow the request. Return `None` to deny it (raising
`HTTPError` works too). Returning any other type is treated as unauthorized.

## HTTPError {#symbol-httperror}

Added in `0.1.0a1`.

Exception converted into an HTTP-style response.

```python
HTTPError(detail: str | None = None, *, status_code: int | None = None)
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `detail` | `str \| None` | `None` | Client-facing error text. Defaults to `"Internal Server Error"`. |
| `status_code` | `int \| None` | `None` | Response status. Defaults to `500`. |

Example:

```python
from quater import HTTPError


@app.get("/orders/{order_id}")
async def get_order(order_id: str) -> dict[str, str]:
    raise HTTPError("Order not found", status_code=404)
```

Expected response:

```text
404 Not Found
Order not found
```

## ImproperlyConfigured {#symbol-improperlyconfigured}

Added in `0.1.0a1`.

Framework setup error. Catch this when startup should fail loudly.

```python
raise ImproperlyConfigured("bad setup")
```

`ConfigurationError` remains in `quater.exceptions` as a compatibility subclass,
but new app code should use `ImproperlyConfigured`.

## SignedCookieSigner {#symbol-signedcookiesigner}

Added in `0.1.0a1`.

HMAC signer for small cookie values. It signs values; it does not encrypt them.

```python
SignedCookieSigner(
    secret: str | bytes,
    *,
    fallback_secrets: Iterable[str | bytes] = (),
    salt: str = "quater.cookie",
)
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `secret` | `str \| bytes` | required | Current signing secret. |
| `fallback_secrets` | `Iterable[str \| bytes]` | `()` | Old secrets accepted during rotation. |
| `salt` | `str` | `"quater.cookie"` | Purpose-specific signing salt. |

Methods:

| Method | Return | Description |
| --- | --- | --- |
| `sign(value)` | `str` | Returns a signed cookie value. |
| `verify(signed_value)` | `str \| None` | Returns original value or `None`. |

Raises `ImproperlyConfigured` if secrets are empty.

## What Can Go Wrong

`Unauthorized`
: An auth hook returned `None`.

`Approval required`
: A protected tool or action ran without a valid approval token.

`Approval denied`
: `action_approval` returned `False`.

`Signed cookie secrets must not be empty`
: Provide non-empty current and fallback secrets.

## Also See

- [Security](/en/dev/security): auth ordering across surfaces.
- [MCP](/en/dev/mcp#auth-layering): tool-call auth sequence.
- [Actions and CLI](/en/dev/actions#approval): dry-run and approval flow.
