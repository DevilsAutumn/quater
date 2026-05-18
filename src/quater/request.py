"""Request primitives."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from quater._state import State
from quater.datastructures import Cookies, HeaderItems, Headers, QueryParams
from quater.exceptions import PayloadTooLargeError
from quater.typing import AuthContext, RequestContext

if TYPE_CHECKING:
    from quater.app import Quater
    from quater.formdata import FormData

BodyReader: TypeAlias = Callable[[], Awaitable[bytes]]
RequestBody: TypeAlias = bytes | BodyReader | None

_UNSET = object()


class Request:
    """Normalized request data passed to handlers.

    Quater creates this object after server, MCP, or CLI input has entered the
    framework. Use it when a handler needs headers, cookies, raw body access,
    auth context, or call-source metadata.
    """

    __slots__ = (
        "app",
        "client",
        "context",
        "max_body_size",
        "max_file_size",
        "max_form_field_size",
        "max_form_parts",
        "method",
        "path",
        "scheme",
        "upload_spool_size",
        "_auth",
        "_body_cache",
        "_body_reader",
        "_cookies",
        "_finalizers",
        "_form_cache",
        "_headers",
        "_json_cache",
        "_raw_headers",
        "_raw_query_string",
        "_query",
        "_state",
    )

    def __init__(
        self,
        *,
        method: str,
        path: str,
        scheme: str = "http",
        headers: HeaderItems | Mapping[str, str] = (),
        query_string: str | bytes = "",
        body: RequestBody = None,
        auth: AuthContext | None = None,
        client: str | None = None,
        context: RequestContext | None = None,
        app: Quater | None = None,
        max_body_size: int | None = None,
        max_form_parts: int | None = None,
        max_form_field_size: int | None = None,
        max_file_size: int | None = None,
        upload_spool_size: int | None = None,
    ) -> None:
        self.method = method.upper()
        self.path = path
        self.scheme = scheme.lower()
        self.app = app
        self.client = client
        self.context = context or RequestContext()
        self.max_body_size = max_body_size
        self.max_form_parts = max_form_parts
        self.max_form_field_size = max_form_field_size
        self.max_file_size = max_file_size
        self.upload_spool_size = upload_spool_size
        self._raw_headers = headers
        self._raw_query_string = query_string
        self._body_reader = _coerce_body_reader(body)
        self._auth = auth
        self._headers: Headers | None = None
        self._query: QueryParams | None = None
        self._cookies: Cookies | None = None
        self._finalizers: list[Callable[[], Awaitable[None]]] | None = None
        self._body_cache: bytes | object = _UNSET
        self._json_cache: Any = _UNSET
        self._form_cache: FormData | object = _UNSET
        self._state: State | None = None

    @property
    def headers(self) -> Headers:
        if self._headers is None:
            self._headers = Headers(self._raw_headers)
        return self._headers

    @property
    def query(self) -> QueryParams:
        if self._query is None:
            self._query = QueryParams.from_query_string(self._raw_query_string)
        return self._query

    @property
    def cookies(self) -> Cookies:
        if self._cookies is None:
            self._cookies = Cookies.from_cookie_header(self.headers.get("cookie"))
        return self._cookies

    @property
    def auth(self) -> AuthContext | None:
        return self._auth

    @auth.setter
    def auth(self, value: AuthContext | None) -> None:
        self._auth = value

    @property
    def state(self) -> State:
        state = self._state
        if state is None:
            state = State()
            self._state = state
        return state

    async def body(self) -> bytes:
        if self._body_cache is _UNSET:
            data = await self._body_reader()
            if self.max_body_size is not None and len(data) > self.max_body_size:
                raise PayloadTooLargeError
            self._body_cache = data
        return cast(bytes, self._body_cache)

    async def json(self) -> Any:
        if self._json_cache is _UNSET:
            from quater.serialization import loads_json

            self._json_cache = loads_json(await self.body())
        return self._json_cache

    async def form(self) -> FormData:
        if self._form_cache is _UNSET:
            from quater._finalize import add_request_finalizer
            from quater.formdata import parse_form_data

            form = parse_form_data(
                content_type=self.headers.get("content-type"),
                body=await self.body(),
                max_parts=self.max_form_parts,
                max_field_size=self.max_form_field_size,
                max_file_size=self.max_file_size,
                upload_spool_size=self.upload_spool_size,
            )
            if form.files:
                for _name, upload in form.files:
                    add_request_finalizer(self, upload.close)
            self._form_cache = form
        return cast("FormData", self._form_cache)


def _coerce_body_reader(body: RequestBody) -> BodyReader:
    if body is None:

        async def read_empty() -> bytes:
            return b""

        return read_empty

    if isinstance(body, bytes):

        async def read_bytes() -> bytes:
            return body

        return read_bytes

    return body
