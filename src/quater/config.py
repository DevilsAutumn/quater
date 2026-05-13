"""Typed application configuration for Quater."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from ipaddress import ip_network
from string import ascii_letters, digits
from typing import Literal, TypeAlias, cast

from quater.cors import CORSConfig
from quater.exceptions import ConfigurationError

SecurityMode: TypeAlias = Literal["strict", "relaxed", "off"]
MaxBodySize: TypeAlias = int | str

_SIZE_UNITS = {
    "b": 1,
    "kb": 1024,
    "mb": 1024 * 1024,
    "gb": 1024 * 1024 * 1024,
}

_DOCS_ASSETS = (
    "swagger-ui.css",
    "swagger-ui-bundle.js",
    "swagger-ui-standalone-preset.js",
    "swagger-initializer.js",
    "favicon-32x32.png",
)
_HEADER_NAME_CHARS = frozenset(f"!#$%&'*+-.^_`|~{digits}{ascii_letters}")


class _Unset:
    __slots__ = ()


_UNSET = _Unset()


@dataclass(slots=True, frozen=True)
class AppConfig:
    """Immutable configuration shared by a Quater app.

    Most apps pass keyword options to ``Quater(...)`` directly. Use
    ``AppConfig`` when several app instances should start from the same
    validated defaults, or when tests need an explicit config object.
    """

    debug: bool = False
    security: SecurityMode = "strict"
    allowed_hosts: tuple[str, ...] = ()
    trusted_proxies: tuple[str, ...] = ()
    max_body_size: int = 2 * 1024 * 1024
    cors: CORSConfig | None = None
    content_security_policy: str | None = None
    docs_path: str | None = "/docs"
    openapi_path: str | None = "/openapi.json"
    mcp_docs_path: str | None = "/mcp/docs"
    mcp_allowed_origins: tuple[str, ...] = ()
    request_id_header: str | None = "x-request-id"

    def __post_init__(self) -> None:
        if self.security not in {"strict", "relaxed", "off"}:
            raise ConfigurationError(f"Unsupported security mode: {self.security!r}")
        if self.max_body_size < 0:
            raise ConfigurationError("max_body_size must be greater than or equal to 0")
        if any(not _is_valid_ip_network(proxy) for proxy in self.trusted_proxies):
            raise ConfigurationError(
                "trusted_proxies must contain IP addresses or CIDR networks"
            )
        if (
            self.content_security_policy is not None
            and not self.content_security_policy.strip()
        ):
            raise ConfigurationError("content_security_policy must not be empty")
        _validate_optional_path(self.docs_path, "docs_path")
        _validate_optional_path(self.openapi_path, "openapi_path")
        _validate_optional_path(self.mcp_docs_path, "mcp_docs_path")
        _validate_optional_header_name(self.request_id_header, "request_id_header")
        if self.docs_path is not None and self.openapi_path is None:
            raise ConfigurationError("docs_path requires openapi_path")
        self._validate_reserved_paths()

    def _with_overrides(
        self,
        *,
        debug: bool | None = None,
        security: SecurityMode | None = None,
        allowed_hosts: Iterable[str] | None = None,
        trusted_proxies: Iterable[str] | None = None,
        max_body_size: MaxBodySize | None = None,
        cors: CORSConfig | None = None,
        content_security_policy: str | None = None,
        docs_path: str | None | _Unset = _UNSET,
        openapi_path: str | None | _Unset = _UNSET,
        mcp_docs_path: str | None | _Unset = _UNSET,
        mcp_allowed_origins: Iterable[str] | None = None,
        request_id_header: str | None | _Unset = _UNSET,
    ) -> AppConfig:
        """Return a new config with explicit constructor overrides applied."""

        return replace(
            self,
            debug=self.debug if debug is None else debug,
            security=self.security if security is None else security,
            allowed_hosts=(
                self.allowed_hosts
                if allowed_hosts is None
                else _normalize_string_tuple(allowed_hosts, "allowed_hosts")
            ),
            trusted_proxies=(
                self.trusted_proxies
                if trusted_proxies is None
                else _normalize_string_tuple(trusted_proxies, "trusted_proxies")
            ),
            max_body_size=(
                self.max_body_size
                if max_body_size is None
                else parse_size(max_body_size, field_name="max_body_size")
            ),
            cors=self.cors if cors is None else cors,
            content_security_policy=(
                self.content_security_policy
                if content_security_policy is None
                else content_security_policy
            ),
            docs_path=_override_path(self.docs_path, docs_path),
            openapi_path=_override_path(self.openapi_path, openapi_path),
            mcp_docs_path=_override_path(self.mcp_docs_path, mcp_docs_path),
            mcp_allowed_origins=(
                self.mcp_allowed_origins
                if mcp_allowed_origins is None
                else _normalize_string_tuple(
                    mcp_allowed_origins,
                    "mcp_allowed_origins",
                )
            ),
            request_id_header=_override_pathless_value(
                self.request_id_header,
                request_id_header,
            ),
        )

    def _validate_reserved_paths(self) -> None:
        enabled_paths: dict[str, str] = {}
        if self.openapi_path is not None:
            enabled_paths["openapi_path"] = self.openapi_path
        if self.docs_path is not None:
            enabled_paths["docs_path"] = self.docs_path
            for asset_name, path in docs_asset_paths(self.docs_path).items():
                enabled_paths[f"docs asset {asset_name}"] = path
        enabled_paths["mcp_endpoint"] = "/mcp"
        if self.mcp_docs_path is not None:
            enabled_paths["mcp_docs_path"] = self.mcp_docs_path

        seen: dict[str, str] = {}
        for field_name, path in enabled_paths.items():
            if path in seen:
                raise ConfigurationError(
                    f"{field_name} conflicts with {seen[path]}: {path!r}"
                )
            seen[path] = field_name


def parse_size(value: MaxBodySize, *, field_name: str) -> int:
    """Parse byte sizes such as ``"2mb"`` into integer bytes."""

    if isinstance(value, int):
        if value < 0:
            raise ConfigurationError(f"{field_name} must be greater than or equal to 0")
        return value

    normalized = value.strip().lower()
    if not normalized:
        raise ConfigurationError(f"{field_name} must not be empty")

    digits = "".join(char for char in normalized if char.isdigit())
    unit = normalized[len(digits) :].strip()
    if not digits or unit not in _SIZE_UNITS:
        allowed = ", ".join(sorted(_SIZE_UNITS))
        raise ConfigurationError(
            f"{field_name} must be bytes or a string like '2mb' ({allowed})"
        )

    return int(digits) * _SIZE_UNITS[unit]


def _normalize_string_tuple(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    normalized = tuple(values)
    if any(not value for value in normalized):
        raise ConfigurationError(f"{field_name} cannot contain empty values")
    return normalized


def _override_path(
    current: str | None,
    value: str | None | _Unset,
) -> str | None:
    if value is _UNSET:
        return current
    return cast(str | None, value)


def _validate_path(value: str, field_name: str) -> None:
    if not value.startswith("/"):
        raise ConfigurationError(f"{field_name} must start with '/'")
    if "?" in value or "#" in value:
        raise ConfigurationError(
            f"{field_name} must not include query strings or fragments"
        )


def _validate_optional_path(value: str | None, field_name: str) -> None:
    if value is not None:
        _validate_path(value, field_name)


def _validate_header_name(value: str, field_name: str) -> None:
    if not value:
        raise ConfigurationError(f"{field_name} must not be empty")
    if value.startswith(":") or any(char not in _HEADER_NAME_CHARS for char in value):
        raise ConfigurationError(f"{field_name} must be a valid HTTP header name")


def _validate_optional_header_name(value: str | None, field_name: str) -> None:
    if value is not None:
        _validate_header_name(value, field_name)


def _override_pathless_value(
    current: str | None,
    value: str | None | _Unset,
) -> str | None:
    if value is _UNSET:
        return current
    return cast(str | None, value)


def docs_asset_paths(docs_path: str) -> dict[str, str]:
    return {asset_name: join_path(docs_path, asset_name) for asset_name in _DOCS_ASSETS}


def join_path(base_path: str, child: str) -> str:
    base = base_path.rstrip("/")
    if not base:
        return f"/{child}"
    return f"{base}/{child}"


def _is_valid_ip_network(value: str) -> bool:
    try:
        ip_network(value, strict=False)
    except ValueError:
        return False
    return True
