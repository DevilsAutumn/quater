"""In-process testing helpers for Quater applications."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from http.cookies import SimpleCookie
from secrets import token_hex
from typing import Any, ClassVar, Literal, TypeAlias
from urllib.parse import urlencode

from quater._finalize import run_response_finalizers
from quater.datastructures import HeaderItems, Headers
from quater.request import Request
from quater.response import Response, StreamResponse

QueryPrimitive: TypeAlias = str | int | float | bool
QueryValue: TypeAlias = QueryPrimitive | Sequence[QueryPrimitive]
QueryPairs: TypeAlias = Sequence[tuple[str, QueryPrimitive]]
QueryParams: TypeAlias = Mapping[str, QueryValue] | QueryPairs
RequestContent: TypeAlias = bytes | bytearray | memoryview | str
FormValue: TypeAlias = QueryPrimitive | Sequence[QueryPrimitive]
FormDataInput: TypeAlias = Mapping[str, FormValue] | QueryPairs
FileContent: TypeAlias = bytes | bytearray | memoryview | str
FileValue: TypeAlias = (
    FileContent | tuple[str, FileContent] | tuple[str, FileContent, str]
)
FilesInput: TypeAlias = Mapping[str, FileValue] | Sequence[tuple[str, FileValue]]
JSONRPCID: TypeAlias = str | int

__all__ = ["MCPTestClient", "TestClient", "TestResponse"]

_MCP_PATH = "/mcp"
_MCP_PROTOCOL_VERSION = "2025-11-25"


class TestResponse:
    """Collected response returned by ``TestClient``.

    It stores status, headers, and the full body bytes. Streaming responses are
    consumed into ``body`` so tests can assert them without running a server.
    """

    __test__: ClassVar[bool] = False
    __slots__ = ("body", "headers", "status_code")

    def __init__(
        self,
        *,
        status_code: int,
        headers: HeaderItems,
        body: bytes,
    ) -> None:
        self.status_code = status_code
        self.headers = Headers(headers)
        self.body = body

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> Any:
        from quater.serialization import loads_json

        return loads_json(self.body)


class TestClient:
    """Async in-process client for testing a Quater app.

    Requests go through ``Quater.handle()`` without a socket, so tests exercise
    routing, middleware, auth, cookies, lifespan, response conversion, and MCP
    helpers quickly.
    """

    __test__: ClassVar[bool] = False
    __slots__ = (
        "app",
        "mcp",
        "_client",
        "_cookies",
        "_headers",
        "_host",
        "_scheme",
        "_started",
    )

    def __init__(
        self,
        app: object,
        *,
        host: str = "testserver",
        scheme: Literal["http", "https"] = "http",
        client: str = "127.0.0.1",
        headers: HeaderItems | Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
    ) -> None:
        from quater.app import Quater

        if not isinstance(app, Quater):
            raise TypeError("TestClient requires a Quater application")

        self.app = app
        self._host = host
        self._scheme = scheme
        self._client = client
        self._headers = tuple(Headers(headers or ()).raw)
        self._cookies = dict(cookies or {})
        self._started = False
        self.mcp = MCPTestClient(self)

    async def __aenter__(self) -> TestClient:
        await self.startup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        await self.shutdown()

    async def startup(self) -> None:
        if self._started:
            return
        await self.app.startup()
        self._started = True

    async def shutdown(self) -> None:
        if not self._started:
            return
        await self.app.shutdown()
        self._started = False

    def set_cookie(self, name: str, value: str) -> None:
        self._cookies[name] = value

    def clear_cookies(self) -> None:
        self._cookies.clear()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: HeaderItems | Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        json: object = None,
        content: RequestContent | None = None,
        data: FormDataInput | None = None,
        files: FilesInput | None = None,
    ) -> TestResponse:
        request_path, query_string = _request_target(path, params)
        body, content_type = _request_body(
            json=json,
            content=content,
            data=data,
            files=files,
        )
        request_headers = self._request_headers(
            headers,
            cookies=cookies,
            content_type=content_type,
        )
        response = await self.app.handle(
            Request(
                method=method,
                path=request_path,
                scheme=self._scheme,
                headers=request_headers,
                query_string=query_string,
                body=body,
                client=self._client,
            )
        )
        test_response = await _collect_response(response)
        self._store_response_cookies(test_response)
        return test_response

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: HeaderItems | Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
    ) -> TestResponse:
        return await self.request(
            "GET",
            path,
            params=params,
            headers=headers,
            cookies=cookies,
        )

    async def post(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: HeaderItems | Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        json: object = None,
        content: RequestContent | None = None,
        data: FormDataInput | None = None,
        files: FilesInput | None = None,
    ) -> TestResponse:
        return await self.request(
            "POST",
            path,
            params=params,
            headers=headers,
            cookies=cookies,
            json=json,
            content=content,
            data=data,
            files=files,
        )

    async def put(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: HeaderItems | Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        json: object = None,
        content: RequestContent | None = None,
        data: FormDataInput | None = None,
        files: FilesInput | None = None,
    ) -> TestResponse:
        return await self.request(
            "PUT",
            path,
            params=params,
            headers=headers,
            cookies=cookies,
            json=json,
            content=content,
            data=data,
            files=files,
        )

    async def patch(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: HeaderItems | Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        json: object = None,
        content: RequestContent | None = None,
        data: FormDataInput | None = None,
        files: FilesInput | None = None,
    ) -> TestResponse:
        return await self.request(
            "PATCH",
            path,
            params=params,
            headers=headers,
            cookies=cookies,
            json=json,
            content=content,
            data=data,
            files=files,
        )

    async def delete(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        headers: HeaderItems | Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        json: object = None,
        content: RequestContent | None = None,
        data: FormDataInput | None = None,
        files: FilesInput | None = None,
    ) -> TestResponse:
        return await self.request(
            "DELETE",
            path,
            params=params,
            headers=headers,
            cookies=cookies,
            json=json,
            content=content,
            data=data,
            files=files,
        )

    def _request_headers(
        self,
        headers: HeaderItems | Mapping[str, str] | None,
        *,
        cookies: Mapping[str, str] | None,
        content_type: str | None,
    ) -> tuple[tuple[str, str], ...]:
        merged: dict[str, str] = {"host": self._host}
        merged.update(self._headers)
        merged.update(Headers(headers or ()))
        if content_type is not None and "content-type" not in merged:
            merged["content-type"] = content_type

        if "cookie" not in merged:
            cookie_header = _cookie_header({**self._cookies, **dict(cookies or {})})
            if cookie_header:
                merged["cookie"] = cookie_header

        return tuple(merged.items())

    def _store_response_cookies(self, response: TestResponse) -> None:
        for header in response.headers.get_all("set-cookie"):
            parsed = SimpleCookie()
            parsed.load(header)
            for name, morsel in parsed.items():
                if morsel["max-age"] == "0":
                    self._cookies.pop(name, None)
                    continue
                self._cookies[name] = morsel.value


class MCPTestClient:
    """JSON-RPC helper for testing Quater MCP tools.

    Access it as ``client.mcp`` from ``TestClient``. It sends ``initialize``,
    ``tools/list``, ``tools/call``, and custom payloads through the same
    ``/mcp`` path as a real client.
    """

    __test__: ClassVar[bool] = False
    __slots__ = ("_client",)

    def __init__(self, client: TestClient) -> None:
        self._client = client

    async def initialize(
        self,
        *,
        request_id: JSONRPCID = 1,
        token: str | None = None,
        origin: str | None = None,
        protocol_version: str = _MCP_PROTOCOL_VERSION,
        client_name: str = "quater-test-client",
        client_version: str = "1.0.0",
        capabilities: Mapping[str, object] | None = None,
        headers: HeaderItems | Mapping[str, str] | None = None,
    ) -> TestResponse:
        return await self.request(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": protocol_version,
                    "capabilities": dict(capabilities or {}),
                    "clientInfo": {
                        "name": client_name,
                        "version": client_version,
                    },
                },
            },
            token=token,
            origin=origin,
            protocol_version=protocol_version,
            headers=headers,
        )

    async def tools_list(
        self,
        *,
        request_id: JSONRPCID = 1,
        token: str | None = None,
        origin: str | None = None,
        protocol_version: str = _MCP_PROTOCOL_VERSION,
        headers: HeaderItems | Mapping[str, str] | None = None,
    ) -> TestResponse:
        return await self.request(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/list",
            },
            token=token,
            origin=origin,
            protocol_version=protocol_version,
            headers=headers,
        )

    async def tools_call(
        self,
        name: str,
        arguments: Mapping[str, object] | None = None,
        *,
        request_id: JSONRPCID = 1,
        token: str | None = None,
        origin: str | None = None,
        approval_token: str | None = None,
        meta: Mapping[str, object] | None = None,
        protocol_version: str = _MCP_PROTOCOL_VERSION,
        headers: HeaderItems | Mapping[str, str] | None = None,
    ) -> TestResponse:
        params: dict[str, object] = {
            "name": name,
            "arguments": dict(arguments or {}),
        }
        meta_payload = dict(meta or {})
        if approval_token is not None:
            meta_payload["approvalToken"] = approval_token
        if meta_payload:
            params["_meta"] = meta_payload

        return await self.request(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": params,
            },
            token=token,
            origin=origin,
            protocol_version=protocol_version,
            headers=headers,
        )

    async def request(
        self,
        payload: Mapping[str, object],
        *,
        token: str | None = None,
        origin: str | None = None,
        protocol_version: str = _MCP_PROTOCOL_VERSION,
        headers: HeaderItems | Mapping[str, str] | None = None,
    ) -> TestResponse:
        request_headers: dict[str, str] = {
            "content-type": "application/json",
            "mcp-protocol-version": protocol_version,
        }
        if token is not None:
            request_headers["authorization"] = f"Bearer {token}"
        if origin is not None:
            request_headers["origin"] = origin
        request_headers.update(Headers(headers or ()))

        from quater.serialization import dumps_json

        return await self._client.post(
            _MCP_PATH,
            headers=request_headers,
            content=dumps_json(payload),
        )


def _request_target(path: str, params: QueryParams | None) -> tuple[str, str]:
    if "#" in path:
        raise ValueError("Test client paths must not include URL fragments")
    request_path, separator, inline_query = path.partition("?")
    if not request_path.startswith("/"):
        raise ValueError("Test client paths must start with '/'")

    query_parts = [inline_query] if separator and inline_query else []
    if params is not None:
        query_parts.append(_encode_query_params(params))
    return request_path, "&".join(part for part in query_parts if part)


def _encode_query_params(params: QueryParams) -> str:
    if isinstance(params, Mapping):
        return urlencode(_flatten_query_mapping(params))
    return urlencode(params)


def _flatten_query_mapping(
    params: Mapping[str, QueryValue],
) -> list[tuple[str, QueryPrimitive]]:
    items: list[tuple[str, QueryPrimitive]] = []
    for name, value in params.items():
        if isinstance(value, str):
            items.append((name, value))
            continue
        if isinstance(value, Sequence):
            for item in value:
                items.append((name, item))
            continue
        items.append((name, value))
    return items


def _request_body(
    *,
    json: object,
    content: RequestContent | None,
    data: FormDataInput | None,
    files: FilesInput | None,
) -> tuple[bytes, str | None]:
    if json is not None and content is not None:
        raise ValueError("Use either json or content, not both")
    provided = sum(value is not None for value in (json, content, data, files))
    if provided > 1 and not (data is not None and files is not None and provided == 2):
        raise ValueError("Use one request body style")
    if files is not None:
        return _multipart_body(data=data, files=files)
    if data is not None:
        return urlencode(_flatten_form_mapping(data)).encode("utf-8"), (
            "application/x-www-form-urlencoded"
        )
    if json is not None:
        from quater.serialization import dumps_json

        return dumps_json(json), "application/json"
    if content is None:
        return b"", None
    if isinstance(content, str):
        return content.encode("utf-8"), "text/plain; charset=utf-8"
    return bytes(content), None


def _flatten_form_mapping(
    data: FormDataInput,
) -> list[tuple[str, QueryPrimitive]]:
    if isinstance(data, Mapping):
        return _flatten_query_mapping(data)
    return list(data)


def _multipart_body(
    *,
    data: FormDataInput | None,
    files: FilesInput,
) -> tuple[bytes, str]:
    boundary = f"quater-{token_hex(16)}"
    chunks: list[bytes] = []
    for name, value in _flatten_form_mapping(data or ()):
        _append_multipart_field(chunks, boundary=boundary, name=name, value=value)
    for name, file_value in _iter_file_items(files):
        filename, content, content_type = _normalize_file_value(name, file_value)
        _append_multipart_file(
            chunks,
            boundary=boundary,
            name=name,
            filename=filename,
            content=content,
            content_type=content_type,
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _iter_file_items(files: FilesInput) -> Iterable[tuple[str, FileValue]]:
    if isinstance(files, Mapping):
        return files.items()
    return files


def _append_multipart_field(
    chunks: list[bytes],
    *,
    boundary: str,
    name: str,
    value: QueryPrimitive,
) -> None:
    chunks.append(f"--{boundary}\r\n".encode("ascii"))
    chunks.append(
        b'Content-Disposition: form-data; name="' + _header_value(name) + b'"\r\n\r\n'
    )
    chunks.append(str(value).encode("utf-8"))
    chunks.append(b"\r\n")


def _append_multipart_file(
    chunks: list[bytes],
    *,
    boundary: str,
    name: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    chunks.append(f"--{boundary}\r\n".encode("ascii"))
    chunks.append(
        b'Content-Disposition: form-data; name="'
        + _header_value(name)
        + b'"; filename="'
        + _header_value(filename)
        + b'"\r\n'
    )
    chunks.append(b"Content-Type: " + _header_value(content_type) + b"\r\n\r\n")
    chunks.append(content)
    chunks.append(b"\r\n")


def _normalize_file_value(name: str, value: FileValue) -> tuple[str, bytes, str]:
    if isinstance(value, tuple):
        if len(value) == 2:
            filename, content = value
            content_type = "application/octet-stream"
        elif len(value) == 3:
            filename, content, content_type = value
        else:
            raise ValueError("File tuples must contain 2 or 3 items")
        return filename, _content_bytes(content), content_type
    return name, _content_bytes(value), "application/octet-stream"


def _content_bytes(value: FileContent) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _header_value(value: str) -> bytes:
    if not value or any(_invalid_multipart_header_char(char) for char in value):
        raise ValueError("Multipart names and filenames must not be empty or unsafe")
    return value.encode("utf-8")


def _invalid_multipart_header_char(value: str) -> bool:
    ordinal = ord(value)
    return ordinal < 32 or ordinal == 127 or value in {'"', "\\"}


def _cookie_header(cookies: Mapping[str, str]) -> str:
    if not cookies:
        return ""

    parsed = SimpleCookie()
    for name, value in cookies.items():
        parsed[name] = value
    return "; ".join(f"{morsel.key}={morsel.coded_value}" for morsel in parsed.values())


async def _collect_response(response: Response) -> TestResponse:
    try:
        if isinstance(response, StreamResponse):
            chunks = [chunk async for chunk in response.body_iterator if chunk]
            body = b"".join(chunks)
        else:
            body = response.body
        return TestResponse(
            status_code=response.status_code,
            headers=response.headers,
            body=body,
        )
    finally:
        await run_response_finalizers(response)
