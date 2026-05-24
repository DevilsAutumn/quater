"""Typed application configuration for Quater."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from ipaddress import ip_network
from string import ascii_letters, digits
from typing import Literal, TypeAlias, TypedDict, cast

from quater.cors import CORSConfig
from quater.exceptions import ConfigurationError

SecurityMode: TypeAlias = Literal["strict", "relaxed", "off"]
MaxBodySize: TypeAlias = int | str
MaxSize: TypeAlias = int | str

DEFAULT_MAX_BODY_SIZE = 2 * 1024 * 1024
DEFAULT_MAX_FORM_PARTS = 1000
DEFAULT_MAX_FORM_FIELD_SIZE = 1024 * 1024
DEFAULT_MAX_FILE_SIZE = 2 * 1024 * 1024
DEFAULT_UPLOAD_SPOOL_SIZE = 1024 * 1024
DEFAULT_MAX_TOOL_RESPONSE_SIZE = 1024 * 1024
DEFAULT_MAX_ACTION_RESPONSE_SIZE = 1024 * 1024

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
_SIZE_ENV_FIELDS = {
    "QUATER_MAX_BODY_SIZE": "max_body_size",
    "QUATER_MAX_FORM_FIELD_SIZE": "max_form_field_size",
    "QUATER_MAX_FILE_SIZE": "max_file_size",
    "QUATER_UPLOAD_SPOOL_SIZE": "upload_spool_size",
    "QUATER_MAX_TOOL_RESPONSE_SIZE": "max_tool_response_size",
    "QUATER_MAX_ACTION_RESPONSE_SIZE": "max_action_response_size",
}
_COUNT_ENV_FIELDS = {
    "QUATER_MAX_FORM_PARTS": "max_form_parts",
}


class _Unset:
    __slots__ = ()


_UNSET = _Unset()


class _EnvironmentOverrides(TypedDict, total=False):
    max_body_size: int
    max_form_parts: int
    max_form_field_size: int
    max_file_size: int
    upload_spool_size: int
    max_tool_response_size: int
    max_action_response_size: int


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
    max_body_size: int = DEFAULT_MAX_BODY_SIZE
    max_form_parts: int = DEFAULT_MAX_FORM_PARTS
    max_form_field_size: int = DEFAULT_MAX_FORM_FIELD_SIZE
    max_file_size: int = DEFAULT_MAX_FILE_SIZE
    upload_spool_size: int = DEFAULT_UPLOAD_SPOOL_SIZE
    max_tool_response_size: int = DEFAULT_MAX_TOOL_RESPONSE_SIZE
    max_action_response_size: int = DEFAULT_MAX_ACTION_RESPONSE_SIZE
    cors: CORSConfig | None = None
    content_security_policy: str | None = None
    docs_path: str | None = "/docs"
    openapi_path: str | None = "/openapi.json"
    mcp_docs_path: str | None = "/mcp/docs"
    mcp_allowed_origins: tuple[str, ...] = ()
    request_id_header: str | None = "x-request-id"

    def __post_init__(self) -> None:
        allowed_hosts = _normalize_string_tuple(
            self.allowed_hosts,
            "allowed_hosts",
        )
        trusted_proxies = _normalize_string_tuple(
            self.trusted_proxies,
            "trusted_proxies",
        )
        mcp_allowed_origins = _normalize_string_tuple(
            self.mcp_allowed_origins,
            "mcp_allowed_origins",
        )
        if self.security not in {"strict", "relaxed", "off"}:
            raise ConfigurationError(f"Unsupported security mode: {self.security!r}")
        if self.max_body_size < 0:
            raise ConfigurationError("max_body_size must be greater than or equal to 0")
        if self.max_form_parts < 1:
            raise ConfigurationError("max_form_parts must be greater than 0")
        for field_name in (
            "max_form_field_size",
            "max_file_size",
            "upload_spool_size",
            "max_tool_response_size",
            "max_action_response_size",
        ):
            if getattr(self, field_name) < 0:
                raise ConfigurationError(
                    f"{field_name} must be greater than or equal to 0"
                )
        if any(not _is_valid_ip_network(proxy) for proxy in trusted_proxies):
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
        object.__setattr__(self, "allowed_hosts", allowed_hosts)
        object.__setattr__(self, "trusted_proxies", trusted_proxies)
        object.__setattr__(self, "mcp_allowed_origins", mcp_allowed_origins)
        self._validate_reserved_paths()

    @classmethod
    def from_environment(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> AppConfig:
        """Build config defaults from ``QUATER_*`` environment variables."""

        return cls(**_environment_overrides(os.environ if env is None else env))

    def _with_overrides(
        self,
        *,
        debug: bool | None = None,
        security: SecurityMode | None = None,
        allowed_hosts: Iterable[str] | None = None,
        trusted_proxies: Iterable[str] | None = None,
        max_body_size: MaxBodySize | None = None,
        max_form_parts: int | None = None,
        max_form_field_size: MaxSize | None = None,
        max_file_size: MaxSize | None = None,
        upload_spool_size: MaxSize | None = None,
        max_tool_response_size: MaxSize | None = None,
        max_action_response_size: MaxSize | None = None,
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
            max_form_parts=(
                self.max_form_parts
                if max_form_parts is None
                else parse_count(max_form_parts, field_name="max_form_parts")
            ),
            max_form_field_size=(
                self.max_form_field_size
                if max_form_field_size is None
                else parse_size(
                    max_form_field_size,
                    field_name="max_form_field_size",
                )
            ),
            max_file_size=(
                self.max_file_size
                if max_file_size is None
                else parse_size(max_file_size, field_name="max_file_size")
            ),
            upload_spool_size=(
                self.upload_spool_size
                if upload_spool_size is None
                else parse_size(upload_spool_size, field_name="upload_spool_size")
            ),
            max_tool_response_size=(
                self.max_tool_response_size
                if max_tool_response_size is None
                else parse_size(
                    max_tool_response_size,
                    field_name="max_tool_response_size",
                )
            ),
            max_action_response_size=(
                self.max_action_response_size
                if max_action_response_size is None
                else parse_size(
                    max_action_response_size,
                    field_name="max_action_response_size",
                )
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


def parse_count(value: int | str, *, field_name: str) -> int:
    """Parse positive integer count settings."""

    if isinstance(value, int):
        if value < 1:
            raise ConfigurationError(f"{field_name} must be greater than 0")
        return value

    normalized = value.strip()
    if not normalized:
        raise ConfigurationError(f"{field_name} must not be empty")
    if not normalized.isdigit() or normalized.startswith("0") and normalized != "0":
        raise ConfigurationError(f"{field_name} must be a positive integer")
    parsed = int(normalized)
    if parsed < 1:
        raise ConfigurationError(f"{field_name} must be greater than 0")
    return parsed


def _environment_overrides(env: Mapping[str, str]) -> _EnvironmentOverrides:
    overrides: dict[str, int] = {}
    for env_name, field_name in _SIZE_ENV_FIELDS.items():
        if env_name in env:
            overrides[field_name] = parse_size(env[env_name], field_name=env_name)
    for env_name, field_name in _COUNT_ENV_FIELDS.items():
        if env_name in env:
            overrides[field_name] = parse_count(env[env_name], field_name=env_name)
    return cast(_EnvironmentOverrides, overrides)


def _normalize_string_tuple(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise ConfigurationError(
            f"{field_name} must be an iterable of strings, not a single string"
        )
    if isinstance(values, (bytes, bytearray)):
        raise ConfigurationError(f"{field_name} must contain strings, not bytes")
    if isinstance(values, Mapping):
        raise ConfigurationError(f"{field_name} must be an iterable of strings")

    normalized = tuple(values)
    if any(not isinstance(value, str) for value in normalized):
        raise ConfigurationError(f"{field_name} must contain only strings")
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
