"""Per-surface authentication.

An app is handed a list of :class:`AuthConfig` objects, each covering one or more
surfaces (``api``/``mcp``/``cli``). Exactly one runs per request, chosen by
``request.context.source``. The authenticator receives the real
:class:`~quater.request.Request` and returns an :class:`AuthContext`.

Auth resources are intentionally lazy: do cheap request checks first, then call
``await request.resolve(SessionDep)`` only when a database/session/resource is
actually needed. ``SessionDep`` is the same ``Annotated[T, resource]`` alias the
handler injects. The resolved value shares the same request scope that handler
injection uses, so the handler can inject the same resource later without a
second open.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Annotated, get_args, get_origin, get_type_hints

from quater.exceptions import ConfigurationError, UnauthorizedError
from quater.request import Request
from quater.typing import SURFACES, AuthContext, Authenticator, RequestSource

_SURFACE_SET: frozenset[RequestSource] = frozenset(SURFACES)


class AuthConfig:
    """One authenticator bound to one or more request surfaces.

    ``surfaces`` lists the surfaces this authenticator covers; each surface may
    be covered by at most one ``AuthConfig`` across the whole app. A single
    ``AuthConfig`` shared across surfaces still runs at most once per request.
    """

    __slots__ = ("authenticator", "name", "surfaces")

    def __init__(
        self,
        authenticator: Authenticator,
        *,
        surfaces: Iterable[str],
        name: str | None = None,
    ) -> None:
        if not callable(authenticator):
            raise TypeError("AuthConfig authenticator must be callable")
        self.authenticator = authenticator
        self.surfaces: tuple[RequestSource, ...] = _normalize_surfaces(surfaces)
        self.name = name

    @property
    def display_name(self) -> str:
        return self.name or self._authenticator_name()

    def _authenticator_name(self) -> str:
        provider_name = getattr(self.authenticator, "__name__", None)
        return provider_name if isinstance(provider_name, str) else "authenticator"

    def __repr__(self) -> str:
        return f"AuthConfig({self.display_name!r}, surfaces={list(self.surfaces)!r})"


def build_auth_map(
    auths: Iterable[AuthConfig] | None,
) -> dict[RequestSource, AuthConfig]:
    """Map each surface to the single ``AuthConfig`` that covers it.

    Raises if a surface is covered more than once. The map is the request-time
    lookup that keeps authentication to exactly one authenticator per surface.
    """

    mapping: dict[RequestSource, AuthConfig] = {}
    for auth in auths or ():
        if not isinstance(auth, AuthConfig):
            raise ConfigurationError("auth must be a list of AuthConfig objects")
        for surface in auth.surfaces:
            existing = mapping.get(surface)
            if existing is not None:
                raise ConfigurationError(
                    f"Surface {surface!r} is covered by more than one AuthConfig "
                    f"({existing.display_name!r} and {auth.display_name!r}). "
                    "Cover each surface with exactly one AuthConfig; compose multiple "
                    "checks inside a single authenticator."
                )
            mapping[surface] = auth
    return mapping


def validate_auth(auth: AuthConfig) -> None:
    """Validate the authenticator contract at route compile time."""

    _validate_authenticator_signature(auth)


async def run_authenticator(auth: AuthConfig, request: Request) -> AuthContext:
    """Run the authenticator once for the request surface.

    The result is set on ``request.auth`` and returned. Anything other than an
    :class:`AuthContext` (including ``None``) denies the request — auth stays
    fail-closed.
    """

    result = auth.authenticator(request)
    resolved = await result if inspect.isawaitable(result) else result
    if not isinstance(resolved, AuthContext):
        raise UnauthorizedError
    request.auth = resolved
    return resolved


def _validate_authenticator_signature(auth: AuthConfig) -> None:
    try:
        signature = inspect.signature(auth.authenticator)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"AuthConfig authenticator {auth.display_name!r} signature "
            "could not be inspected"
        ) from exc

    hints = _authenticator_hints(auth.authenticator, signature)

    request_params = 0
    for parameter in signature.parameters.values():
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise ConfigurationError(
                f"AuthConfig authenticator {auth.display_name!r} cannot use "
                "*args or **kwargs"
            )

        annotation = hints.get(parameter.name, parameter.annotation)
        if _annotation_has_resource(annotation):
            raise ConfigurationError(
                f"AuthConfig authenticator {auth.display_name!r} cannot declare "
                "resource parameters; do cheap checks first, then use "
                "await request.resolve(SessionDep)"
            )
        if parameter.name == "request" or _annotation_base(annotation) is Request:
            request_params += 1
            continue
        raise ConfigurationError(
            f"AuthConfig authenticator {auth.display_name!r} may only accept "
            "the request parameter"
        )

    if request_params != 1:
        raise ConfigurationError(
            f"AuthConfig authenticator {auth.display_name!r} must accept exactly "
            "one request parameter"
        )


def _annotation_base(annotation: object) -> object:
    if get_origin(annotation) is Annotated:
        return get_args(annotation)[0]
    return annotation


def _annotation_has_resource(annotation: object) -> bool:
    if get_origin(annotation) is not Annotated:
        return False
    from quater.dependencies import Resource

    return any(isinstance(metadata, Resource) for metadata in get_args(annotation)[1:])


def _authenticator_hints(
    authenticator: Authenticator,
    signature: inspect.Signature,
) -> dict[str, object]:
    try:
        return get_type_hints(authenticator, include_extras=True)
    except (NameError, TypeError):
        return _parameter_hints(authenticator, signature)


def _parameter_hints(
    authenticator: Authenticator,
    signature: inspect.Signature,
) -> dict[str, object]:
    globalns = _callable_globalns(authenticator)
    hints: dict[str, object] = {}
    for parameter in signature.parameters.values():
        annotation = parameter.annotation
        if annotation is inspect.Signature.empty:
            continue
        proxy = _AnnotationProxy()
        proxy.__annotations__ = {parameter.name: annotation}
        try:
            hints.update(
                get_type_hints(
                    proxy,
                    globalns=globalns,
                    localns=globalns,
                    include_extras=True,
                )
            )
        except (NameError, TypeError):
            hints[parameter.name] = annotation
    return hints


def _callable_globalns(authenticator: Authenticator) -> dict[str, object]:
    target = inspect.unwrap(authenticator)
    function = getattr(target, "__func__", target)
    globalns = getattr(function, "__globals__", None)
    if isinstance(globalns, dict):
        return globalns

    if not callable(target):
        return {}
    call = target.__call__
    function = getattr(call, "__func__", call)
    globalns = getattr(function, "__globals__", None)
    if isinstance(globalns, dict):
        return globalns
    return {}


class _AnnotationProxy:
    __annotations__: dict[str, object]


def _normalize_surfaces(
    surfaces: Iterable[str],
) -> tuple[RequestSource, ...]:
    if isinstance(surfaces, str):
        raise ConfigurationError(
            "AuthConfig surfaces must be a list of surface names, not a string"
        )
    normalized: list[RequestSource] = []
    seen: set[str] = set()
    for surface in surfaces:
        if surface not in _SURFACE_SET:
            raise ConfigurationError(
                f"Unknown auth surface {surface!r}; expected one of "
                f"{', '.join(SURFACES)}"
            )
        if surface in seen:
            raise ConfigurationError(
                f"AuthConfig lists surface {surface!r} more than once"
            )
        seen.add(surface)
        normalized.append(surface)
    if not normalized:
        raise ConfigurationError("AuthConfig must cover at least one surface")
    return tuple(normalized)


__all__ = [
    "AuthConfig",
    "build_auth_map",
    "run_authenticator",
    "validate_auth",
]
