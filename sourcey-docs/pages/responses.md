---
description: Reference for Quater response conversion and the explicit response classes for status codes, headers, redirects, and streams.
---

# Responses Reference

This page documents Quater response conversion and explicit response classes.

## Prerequisites

Read [Public API](/en/dev/api#responses). Most handlers can return plain
Python values; use response classes when you need status, headers, redirects, or
streams.

```python
from quater import JSONResponse, RedirectResponse, Response, StreamResponse
```

## Automatic Return Values

| Handler returns | Quater sends |
| --- | --- |
| `dict`, `list`, `tuple`, dataclass, `msgspec.Struct` | `JSONResponse` |
| `str` | `TextResponse` |
| `bytes`, `bytearray`, `memoryview` | `BytesResponse` |
| `None` | `EmptyResponse(status_code=204)` |
| `Response` instance | Sent as-is |

If Quater cannot convert the value, it raises `ResponseConversionError` and
returns a `500 Internal Server Error`.

## Response {#symbol-response}

Added in `0.1.0a1`.

```python
Response(
    body: bytes = b"",
    *,
    status_code: int = 200,
    headers: HeaderItems | Mapping[str, str] | None = None,
    content_type: str | None = None,
) -> None
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `body` | `bytes` | `b""` | Raw response body. |
| `status_code` | `int` | `200` | HTTP status code. |
| `headers` | `HeaderItems \| Mapping[str, str] \| None` | `None` | Response headers. |
| `content_type` | `str \| None` | `None` | Content type added when no header exists. |

## JSONResponse {#symbol-jsonresponse}

```python
JSONResponse(content: object, *, status_code: int = 200, headers: HeaderItems | Mapping[str, str] | None = None)
```

Serializes `content` with Quater's msgspec JSON encoder.

## TextResponse {#symbol-textresponse}

```python
TextResponse(
    content: str,
    *,
    status_code: int = 200,
    headers: HeaderItems | Mapping[str, str] | None = None,
    content_type: str = "text/plain; charset=utf-8",
)
```

## HTMLResponse {#symbol-htmlresponse}

```python
HTMLResponse(content: str, *, status_code: int = 200, headers: HeaderItems | Mapping[str, str] | None = None)
```

Sets `content-type: text/html; charset=utf-8`.

## BytesResponse {#symbol-bytesresponse}

```python
BytesResponse(
    content: bytes | bytearray | memoryview,
    *,
    status_code: int = 200,
    headers: HeaderItems | Mapping[str, str] | None = None,
    content_type: str = "application/octet-stream",
)
```

## StreamResponse {#symbol-streamresponse}

```python
StreamResponse(
    body_iterator: AsyncIterable[bytes],
    *,
    status_code: int = 200,
    headers: HeaderItems | Mapping[str, str] | None = None,
    content_type: str = "application/octet-stream",
)
```

Use this for async byte streams. Resource finalizers stay attached until the
adapter finishes consuming the stream.

## RedirectResponse {#symbol-redirectresponse}

```python
RedirectResponse(
    location: str,
    *,
    status_code: int = 307,
    headers: HeaderItems | Mapping[str, str] | None = None,
)
```

Default `307` preserves the HTTP method.

## EmptyResponse {#symbol-emptyresponse}

```python
EmptyResponse(*, status_code: int = 204, headers: HeaderItems | Mapping[str, str] | None = None)
```

## Cookie helpers {#symbol-set-cookie}

Both helpers are available on every response class.

### `set_cookie`

```python
response.set_cookie(
    key: str,
    value: str = "",
    *,
    max_age: int | None = None,
    expires: int | None = None,
    path: str | None = "/",
    domain: str | None = None,
    secure: bool = False,
    httponly: bool = False,
    samesite: Literal["lax", "strict", "none"] | None = "lax",
) -> None
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `key` | `str` | — | Cookie name. Must be a valid RFC 6265 token. |
| `value` | `str` | `""` | Cookie value. Must be a valid RFC 6265 cookie-octet string. |
| `max_age` | `int \| None` | `None` | Max age in seconds. |
| `expires` | `int \| None` | `None` | Expiry as a Unix timestamp. |
| `path` | `str \| None` | `"/"` | Cookie path. |
| `domain` | `str \| None` | `None` | Cookie domain. |
| `secure` | `bool` | `False` | Set the `Secure` flag. |
| `httponly` | `bool` | `False` | Set the `HttpOnly` flag. |
| `samesite` | `Literal["lax", "strict", "none"] \| None` | `"lax"` | SameSite policy. `"none"` requires `secure=True`. |

### `delete_cookie`

```python
response.delete_cookie(
    key: str,
    *,
    path: str | None = "/",
    domain: str | None = None,
    secure: bool = False,
    httponly: bool = False,
    samesite: Literal["lax", "strict", "none"] | None = "lax",
) -> None
```

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `key` | `str` | — | Cookie name to delete. |
| `path` | `str \| None` | `"/"` | Must match the path used when the cookie was set. |
| `domain` | `str \| None` | `None` | Must match the domain used when the cookie was set. |
| `secure` | `bool` | `False` | Required for `__Secure-` and `__Host-` prefixed cookies. |
| `httponly` | `bool` | `False` | Set the `HttpOnly` flag. |
| `samesite` | `Literal["lax", "strict", "none"] \| None` | `"lax"` | Required when the deletion response is sent cross-site. `"none"` requires `secure=True`. |

## Complete Example

```python
from quater import JSONResponse, Quater, RedirectResponse

app = Quater()


@app.post("/orders")
async def create_order() -> JSONResponse:
    return JSONResponse({"id": "ord_1001"}, status_code=201)


@app.get("/orders/latest")
async def latest_order() -> RedirectResponse:
    return RedirectResponse("/orders/ord_1001")
```

Expected create response:

```json
{
  "id": "ord_1001"
}
```

## What Can Go Wrong

`Cannot convert 'set' into a response`
: Return a supported value or create a `Response` explicitly.

`Invalid response header name`
: Header names must be valid HTTP token names.

`Invalid response header value`
: Header values cannot contain unsafe control characters.

## Also See

- [Public API](/en/dev/api#responses): when to use explicit responses.
- [Testing](/en/dev/testing#streams): stream response tests.
- [Request Reference](./request): header item type used by responses.
