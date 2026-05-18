"""Request security guards and response headers."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address, ip_network

from quater.config import AppConfig
from quater.exceptions import BadRequestError, PayloadTooLargeError
from quater.request import Request
from quater.response import Response

_LOCAL_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "::1", "testserver")


@dataclass(slots=True, frozen=True)
class RequestSecurityContext:
    """Normalized request metadata after trusted proxy handling."""

    host: str | None
    scheme: str
    client: str | None


def prepare_request_security(
    request: Request,
    config: AppConfig,
) -> RequestSecurityContext:
    request.max_body_size = config.max_body_size
    request.max_form_parts = config.max_form_parts
    request.max_form_field_size = config.max_form_field_size
    request.max_file_size = config.max_file_size
    request.upload_spool_size = config.upload_spool_size
    _validate_singleton_request_headers(request)
    _enforce_content_length(request, config.max_body_size)

    context = resolve_request_security_context(request, config)
    if config.security != "off":
        _validate_allowed_host(
            context.host,
            _effective_allowed_hosts(config),
            allow_missing=(
                context.client is None
                and not config.allowed_hosts
                and config.security == "strict"
            ),
        )
    return context


def resolve_request_security_context(
    request: Request,
    config: AppConfig,
) -> RequestSecurityContext:
    client = request.client
    trusted = client is not None and _client_is_trusted(client, config.trusted_proxies)
    host_header = request.headers.get("host") or request.headers.get(":authority")
    scheme = request.scheme.lower()

    if trusted:
        host_header = (
            _first_header_value(
                request.headers.get("x-forwarded-host"),
            )
            or host_header
        )
        scheme = _first_header_value(request.headers.get("x-forwarded-proto")) or scheme

    return RequestSecurityContext(
        host=_normalize_host(host_header),
        scheme=scheme,
        client=client,
    )


def add_security_headers(
    response: Response,
    context: RequestSecurityContext,
    config: AppConfig,
) -> Response:
    if config.security == "off":
        return response

    headers = response.headers
    headers = _set_default_header(headers, "x-content-type-options", "nosniff")
    headers = _set_default_header(headers, "referrer-policy", "same-origin")

    if config.security == "strict":
        headers = _set_default_header(headers, "x-frame-options", "DENY")
        if context.scheme == "https":
            headers = _set_default_header(
                headers,
                "strict-transport-security",
                "max-age=31536000; includeSubDomains",
            )

    if config.content_security_policy is not None:
        headers = _set_default_header(
            headers,
            "content-security-policy",
            config.content_security_policy,
        )

    response.headers = headers
    return response


def _enforce_content_length(request: Request, max_body_size: int) -> None:
    value = request.headers.get("content-length")
    if value is None:
        return

    try:
        content_length = int(value)
    except ValueError as exc:
        raise BadRequestError("Invalid Content-Length header") from exc

    if content_length < 0:
        raise BadRequestError("Invalid Content-Length header")
    if content_length > max_body_size:
        raise PayloadTooLargeError


def _validate_singleton_request_headers(request: Request) -> None:
    host_values = request.headers.get_all("host")
    authority_values = request.headers.get_all(":authority")

    if len(host_values) > 1 or len(authority_values) > 1:
        raise BadRequestError("Invalid Host header")

    if host_values and authority_values:
        host = _normalize_host(host_values[0])
        authority = _normalize_host(authority_values[0])
        if host != authority:
            raise BadRequestError("Invalid Host header")

    if len(request.headers.get_all("content-length")) > 1:
        raise BadRequestError("Invalid Content-Length header")


def _effective_allowed_hosts(config: AppConfig) -> tuple[str, ...]:
    if config.allowed_hosts:
        return config.allowed_hosts
    if config.security == "strict":
        return _LOCAL_ALLOWED_HOSTS
    return ()


def _validate_allowed_host(
    host: str | None,
    allowed_hosts: tuple[str, ...],
    *,
    allow_missing: bool = False,
) -> None:
    if not allowed_hosts:
        return
    if host is None:
        if allow_missing:
            return
        raise BadRequestError("Invalid Host header")

    for allowed in allowed_hosts:
        if _host_matches(host, allowed):
            return
    raise BadRequestError("Invalid Host header")


def _host_matches(host: str, allowed: str) -> bool:
    normalized_allowed = _normalize_host(allowed)
    if normalized_allowed == "*":
        return True
    if normalized_allowed is None:
        return False
    if normalized_allowed.startswith("*."):
        suffix = normalized_allowed[1:]
        return host.endswith(suffix) and host != normalized_allowed[2:]
    if normalized_allowed.startswith("."):
        root = normalized_allowed[1:]
        return host == root or host.endswith(normalized_allowed)
    return host == normalized_allowed


def _client_is_trusted(client: str, trusted_proxies: tuple[str, ...]) -> bool:
    if not trusted_proxies:
        return False

    try:
        client_ip = ip_address(client)
    except ValueError:
        return False

    return any(
        client_ip in ip_network(proxy, strict=False) for proxy in trusted_proxies
    )


def _first_header_value(value: str | None) -> str | None:
    if value is None:
        return None
    first = value.split(",", 1)[0].strip()
    return first or None


def _normalize_host(value: str | None) -> str | None:
    if value is None:
        return None

    host = value.strip().lower()
    if not host:
        return None
    if host.endswith("."):
        host = host[:-1]
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            return None
        return host[1:end]

    if host.count(":") == 1:
        name, port = host.rsplit(":", 1)
        if port.isdigit():
            return name
    return host


def _set_default_header(
    headers: tuple[tuple[str, str], ...],
    name: str,
    value: str,
) -> tuple[tuple[str, str], ...]:
    normalized = name.lower()
    if any(key == normalized for key, _ in headers):
        return headers
    return (*headers, (normalized, value))
