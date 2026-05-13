"""CORS policy primitives."""

from __future__ import annotations

from dataclasses import dataclass

from quater.exceptions import ConfigurationError
from quater.request import Request
from quater.response import Response

_DEFAULT_METHODS = ("DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT")


@dataclass(slots=True, frozen=True)
class CORSConfig:
    """Validated browser CORS settings.

    CORS decides which browser origins may read responses from your app. It is
    not an authentication layer; protect routes, MCP tools, and CLI actions
    with their auth hooks.
    """

    allowed_origins: tuple[str, ...]
    allowed_methods: tuple[str, ...] = _DEFAULT_METHODS
    allowed_headers: tuple[str, ...] = ()
    expose_headers: tuple[str, ...] = ()
    allow_credentials: bool = False
    max_age: int | None = None

    def __post_init__(self) -> None:
        origins = _normalize_values(self.allowed_origins, "allowed_origins")
        methods = tuple(
            method.strip().upper()
            for method in _normalize_values(self.allowed_methods, "allowed_methods")
        )
        allowed_headers = _normalize_values(
            self.allowed_headers,
            "allowed_headers",
        )
        expose_headers = _normalize_values(self.expose_headers, "expose_headers")

        if "*" in origins and self.allow_credentials:
            raise ConfigurationError(
                "CORS wildcard origins cannot be used with credentials"
            )
        if self.max_age is not None and self.max_age < 0:
            raise ConfigurationError("CORS max_age must be greater than or equal to 0")

        object.__setattr__(self, "allowed_origins", origins)
        object.__setattr__(self, "allowed_methods", methods)
        object.__setattr__(self, "allowed_headers", allowed_headers)
        object.__setattr__(self, "expose_headers", expose_headers)


def add_cors_headers(
    response: Response,
    request: Request,
    config: CORSConfig,
) -> Response:
    origin = request.headers.get("origin")
    if origin is None:
        return response

    allowed_origin = _resolve_allowed_origin(origin, config)
    if allowed_origin is None:
        return response

    headers = response.headers
    headers = _set_header(headers, "access-control-allow-origin", allowed_origin)
    if allowed_origin != "*":
        headers = _append_vary(headers, "Origin")
    if config.allow_credentials:
        headers = _set_header(headers, "access-control-allow-credentials", "true")
    if config.expose_headers:
        headers = _set_header(
            headers,
            "access-control-expose-headers",
            ", ".join(config.expose_headers),
        )
    if _is_preflight(request):
        headers = _set_header(
            headers,
            "access-control-allow-methods",
            ", ".join(config.allowed_methods),
        )
        requested_headers = request.headers.get("access-control-request-headers")
        allow_headers = requested_headers or ", ".join(config.allowed_headers)
        if allow_headers:
            headers = _set_header(
                headers,
                "access-control-allow-headers",
                allow_headers,
            )
        if config.max_age is not None:
            headers = _set_header(
                headers,
                "access-control-max-age",
                str(config.max_age),
            )

    response.headers = headers
    return response


def is_cors_preflight(request: Request) -> bool:
    return (
        request.method == "OPTIONS"
        and request.headers.get("origin") is not None
        and request.headers.get("access-control-request-method") is not None
    )


def _resolve_allowed_origin(origin: str, config: CORSConfig) -> str | None:
    if "*" in config.allowed_origins:
        return "*"
    if origin in config.allowed_origins:
        return origin
    return None


def _is_preflight(request: Request) -> bool:
    return is_cors_preflight(request)


def _set_header(
    headers: tuple[tuple[str, str], ...],
    name: str,
    value: str,
) -> tuple[tuple[str, str], ...]:
    normalized = name.lower()
    filtered = tuple((key, val) for key, val in headers if key != normalized)
    return (*filtered, (normalized, value))


def _append_vary(
    headers: tuple[tuple[str, str], ...],
    value: str,
) -> tuple[tuple[str, str], ...]:
    for name, current in headers:
        if name != "vary":
            continue
        values = {item.strip().lower() for item in current.split(",")}
        if value.lower() in values:
            return headers
        return _set_header(headers, "vary", f"{current}, {value}")
    return (*headers, ("vary", value))


def _normalize_values(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        raise ConfigurationError(f"CORS {field_name} cannot contain empty values")
    return normalized
