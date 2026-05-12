"""Small immutable data views used by requests and responses."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from http.cookies import SimpleCookie
from re import Pattern, compile
from string import ascii_letters, digits
from typing import TypeAlias
from urllib.parse import parse_qsl

from quater.exceptions import BadRequestError

HeaderValue: TypeAlias = str | bytes
HeaderItems: TypeAlias = Iterable[tuple[HeaderValue, HeaderValue]]
RawHeaderItem: TypeAlias = tuple[object, object]

_BAD_PERCENT_ESCAPE: Pattern[str] = compile(r"%(?![0-9A-Fa-f]{2})")
_HEADER_NAME_CHARS = frozenset(f"!#$%&'*+-.^_`|~{digits}{ascii_letters}")


class Headers(Mapping[str, str]):
    """Case-insensitive HTTP header mapping."""

    __slots__ = ("_items", "_lookup")

    def __init__(self, items: HeaderItems | Mapping[str, str] = ()) -> None:
        normalized = tuple(
            (_decode_header(name).lower(), _decode_header(value))
            for name, value in _iter_header_items(items)
        )
        self._items = normalized
        self._lookup = dict(normalized)

    def __getitem__(self, key: str) -> str:
        return self._lookup[key.lower()]

    def __iter__(self) -> Iterator[str]:
        return iter(self._lookup)

    def __len__(self) -> int:
        return len(self._lookup)

    @property
    def raw(self) -> tuple[tuple[str, str], ...]:
        return self._items

    def get_all(self, key: str) -> tuple[str, ...]:
        normalized = key.lower()
        return tuple(value for name, value in self._items if name == normalized)


class QueryParams(Mapping[str, str]):
    """Query string mapping with access to repeated values."""

    __slots__ = ("_items", "_lookup")

    def __init__(self, items: Iterable[tuple[str, str]]) -> None:
        normalized = tuple(items)
        self._items = normalized
        self._lookup = dict(normalized)

    @classmethod
    def from_query_string(cls, query_string: str | bytes) -> QueryParams:
        raw = _decode_query_string(query_string)
        if _BAD_PERCENT_ESCAPE.search(raw):
            raise BadRequestError("Malformed query string")

        try:
            parsed = parse_qsl(raw, keep_blank_values=True, errors="strict")
        except UnicodeDecodeError as exc:
            raise BadRequestError("Malformed query string") from exc

        return cls(parsed)

    def __getitem__(self, key: str) -> str:
        return self._lookup[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._lookup)

    def __len__(self) -> int:
        return len(self._lookup)

    @property
    def raw(self) -> tuple[tuple[str, str], ...]:
        return self._items

    def get_all(self, key: str) -> tuple[str, ...]:
        return tuple(value for name, value in self._items if name == key)


class Cookies(Mapping[str, str]):
    """Parsed request cookies."""

    __slots__ = ("_cookies",)

    def __init__(self, cookies: Mapping[str, str] | None = None) -> None:
        self._cookies = dict(cookies or {})

    @classmethod
    def from_cookie_header(cls, value: str | None) -> Cookies:
        if not value:
            return cls()

        parsed = SimpleCookie()
        parsed.load(value)
        return cls({key: morsel.value for key, morsel in parsed.items()})

    def __getitem__(self, key: str) -> str:
        return self._cookies[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._cookies)

    def __len__(self) -> int:
        return len(self._cookies)


def normalize_response_headers(
    headers: HeaderItems | Mapping[str, str] | None = None,
) -> tuple[tuple[str, str], ...]:
    if headers is None:
        return ()
    return tuple(
        _normalize_response_header(name, value)
        for name, value in _iter_header_items(headers)
    )


def _iter_header_items(
    items: HeaderItems | Mapping[str, str],
) -> Iterator[RawHeaderItem]:
    if isinstance(items, Mapping):
        yield from items.items()
        return
    yield from items


def _decode_header(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("latin-1")
    if isinstance(value, str):
        return value
    raise TypeError("Header names and values must be str or bytes")


def _normalize_response_header(
    name: object,
    value: object,
) -> tuple[str, str]:
    decoded_name = _decode_header(name).lower()
    decoded_value = _decode_header(value)
    _validate_response_header(decoded_name, decoded_value)
    return decoded_name, decoded_value


def _validate_response_header(name: str, value: str) -> None:
    if (
        not name
        or name.startswith(":")
        or any(char not in _HEADER_NAME_CHARS for char in name)
    ):
        raise ValueError("Invalid response header name")
    if any(_invalid_header_value_character(char) for char in value):
        raise ValueError("Invalid response header value")


def _invalid_header_value_character(char: str) -> bool:
    ordinal = ord(char)
    return ordinal > 255 or ordinal == 127 or (ordinal < 32 and char != "\t")


def _decode_query_string(value: str | bytes) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("ascii")
        except UnicodeDecodeError as exc:
            raise BadRequestError("Malformed query string") from exc
    return value
