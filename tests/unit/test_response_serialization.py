from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

import msgspec
import pytest

from quater.exceptions import ResponseConversionError
from quater.response import (
    BytesResponse,
    EmptyResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamResponse,
    TextResponse,
    normalize_response,
    validate_response,
)


class UserOut(msgspec.Struct):
    id: int
    name: str


@dataclass(frozen=True)
class DataclassOut:
    ok: bool


def test_response_preserves_explicit_content_type_without_duplicate() -> None:
    response = JSONResponse(
        {"ok": True},
        headers={"Content-Type": "application/custom"},
    )

    assert response.body == b'{"ok":true}'
    assert response.headers == (("content-type", "application/custom"),)


def test_msgspec_struct_serializes_as_json() -> None:
    response = JSONResponse(UserOut(id=1, name="Ada"))

    assert response.body == b'{"id":1,"name":"Ada"}'
    assert response.headers == (("content-type", "application/json"),)


def test_dataclass_return_value_serializes_as_json() -> None:
    response = normalize_response(DataclassOut(ok=True))

    assert isinstance(response, JSONResponse)
    assert response.body == b'{"ok":true}'


def test_bytes_fast_path_does_not_use_json_encoding() -> None:
    response = normalize_response(b'{"already":"encoded"}')

    assert isinstance(response, BytesResponse)
    assert response.body == b'{"already":"encoded"}'
    assert response.headers == (("content-type", "application/octet-stream"),)


def test_common_return_values_normalize_to_responses() -> None:
    explicit = Response(b"ready", status_code=202)

    assert normalize_response(explicit) is explicit
    assert isinstance(normalize_response({"ok": True}), JSONResponse)
    assert isinstance(normalize_response([1, 2]), JSONResponse)
    assert isinstance(normalize_response((1, 2)), JSONResponse)
    assert isinstance(normalize_response("hello"), TextResponse)
    assert isinstance(normalize_response(None), EmptyResponse)


def test_explicit_response_rejects_invalid_body_type() -> None:
    with pytest.raises(ResponseConversionError, match="Response body"):
        Response(cast(bytes, "not bytes"))


@pytest.mark.parametrize("status_code", [cast(int, "200"), True, 99, 600])
def test_explicit_response_rejects_invalid_status_code(status_code: int) -> None:
    with pytest.raises(ResponseConversionError, match="Response status_code"):
        Response(b"ok", status_code=status_code)


def test_explicit_response_accepts_bytes_like_body_when_validated() -> None:
    response = Response(b"ok")
    response.body = cast(bytes, bytearray(b"mutated"))

    validate_response(response)

    assert response.body == b"mutated"


def test_redirect_response_sets_location_header() -> None:
    response = RedirectResponse("/login", status_code=302)

    assert response.status_code == 302
    assert response.headers == (("location", "/login"),)
    assert response.body == b""


@pytest.mark.asyncio
async def test_stream_response_does_not_consume_iterator_at_construction() -> None:
    consumed: list[bytes] = []

    async def chunks() -> AsyncIterator[bytes]:
        consumed.append(b"first")
        yield b"first"

    response = StreamResponse(chunks())

    assert response.is_streaming is True
    assert consumed == []
    assert [chunk async for chunk in response.body_iterator] == [b"first"]
    assert consumed == [b"first"]


def test_unsupported_return_value_raises_clear_error() -> None:
    class Unsupported:
        pass

    with pytest.raises(ResponseConversionError):
        normalize_response(Unsupported())
