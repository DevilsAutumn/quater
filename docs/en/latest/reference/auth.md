# Auth And Security Reference

This page documents auth hook types, approval hooks, framework errors, and
signed cookies.

## Prerequisites

Read [Security](/en/latest/security). Auth hooks are your application policy;
Quater only defines when they run and what they receive.

```python
from quater import (
    ActionApproval,
    ApprovalRequest,
    AuthContext,
    AuthRequest,
    HTTPError,
    ImproperlyConfigured,
    SignedCookieSigner,
)
```

## AuthRequest {#symbol-authrequest}

Added in `0.1.0a1`.

Input passed to auth hooks.

```python
AuthRequest(
    method: str,
    path: str,
    headers: Mapping[str, str] = {},
    context: RequestContext = RequestContext(),
)
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `method` | `str` | required | Method being accessed. |
| `path` | `str` | required | Path being accessed. |
| `headers` | `Mapping[str, str]` | empty mapping | Normalized headers. |
| `context` | `RequestContext` | `RequestContext()` | Source, entrypoint, request id, tool, and action metadata. |

## AuthContext {#symbol-authcontext}

Added in `0.1.0a1`.

Authenticated identity returned by auth hooks.

```python
AuthContext(subject: str, metadata: Mapping[str, object] = {})
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `subject` | `str` | required | Stable user, service, or agent id. |
| `metadata` | `Mapping[str, object]` | empty mapping | Small request-scoped values your app wants to carry. |

Example:

```python
from quater import AuthContext, AuthRequest


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer demo-token":
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
| `arguments_hash` | `str` | required | SHA-256 hash of action name and canonical JSON arguments. |
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

- [Security](/en/latest/security): auth ordering across surfaces.
- [MCP](/en/latest/mcp#auth-layering): tool-call auth sequence.
- [Actions and CLI](/en/latest/actions#approval): dry-run and approval flow.
