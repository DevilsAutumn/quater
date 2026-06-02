"""Request-scoped resources for handler injection."""

from __future__ import annotations

import inspect
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Generator,
    Iterator,
    Mapping,
)
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from dataclasses import dataclass, field
from typing import (
    Annotated,
    Any,
    Generic,
    Literal,
    TypeAlias,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from quater.exceptions import ConfigurationError
from quater.request import Request

ResourceScope = Literal["request"]
T = TypeVar("T")
_ResourceProviderResult: TypeAlias = (
    T
    | Awaitable[T]
    | Iterator[T]
    | AsyncIterator[T]
    | AbstractContextManager[T]
    | AbstractAsyncContextManager[T]
)
ResourceProvider: TypeAlias = Callable[..., _ResourceProviderResult[T]]
ResourceMap: TypeAlias = Mapping[str, "Resource[Any]"]
StackFactory = Callable[[], AsyncExitStack]

# Cache markers: a resource that has not been resolved, and one whose
# resolution is in progress (used to catch dependency cycles at resolve time).
_UNRESOLVED = object()
_RESOLVING = object()


@dataclass(frozen=True, slots=True)
class _ProviderParam:
    """One parameter of a resource provider: the request, or another resource."""

    name: str
    resource: Resource[Any] | None
    keyword_only: bool


@dataclass(frozen=True, slots=True, init=False)
class Resource(Generic[T]):
    """A request-scoped value that Quater can inject into route handlers.

    Providers may return a value, an awaitable value, a context manager, an
    async context manager, or yield one value from a generator. Generator and
    context-manager providers are cleaned up after the handler finishes.

    A provider may also depend on other resources: declare them as parameters
    annotated with ``Annotated[T, other_resource]``, exactly like a handler.
    Quater resolves those dependencies first — once, from the request's shared
    scope — and passes them in. The dependency graph is validated when routes
    compile, so cycles and unresolvable parameters fail at startup.
    """

    provider: ResourceProvider[T]
    scope: ResourceScope = "request"
    name: str | None = None
    _plan: tuple[_ProviderParam, ...] | None = field(
        init=False, repr=False, compare=False, default=None
    )
    _validated: bool = field(init=False, repr=False, compare=False, default=False)

    @overload
    def __init__(
        self,
        provider: Callable[..., Awaitable[T]],
        scope: ResourceScope = "request",
        name: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        provider: Callable[..., AsyncIterator[T]],
        scope: ResourceScope = "request",
        name: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        provider: Callable[..., Iterator[T]],
        scope: ResourceScope = "request",
        name: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        provider: Callable[..., AbstractAsyncContextManager[T]],
        scope: ResourceScope = "request",
        name: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        provider: Callable[..., AbstractContextManager[T]],
        scope: ResourceScope = "request",
        name: str | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        provider: Callable[..., T],
        scope: ResourceScope = "request",
        name: str | None = None,
    ) -> None: ...

    def __init__(
        self,
        provider: Callable[..., object],
        scope: ResourceScope = "request",
        name: str | None = None,
    ) -> None:
        object.__setattr__(self, "provider", cast(ResourceProvider[T], provider))
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "_plan", None)
        object.__setattr__(self, "_validated", False)
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.scope != "request":
            raise ConfigurationError("Resource scope must be 'request'")
        if not callable(self.provider):
            raise TypeError("Resource provider must be callable")
        _reject_variadic_parameters(self.provider)

    async def resolve(
        self,
        request: Request,
        stack: AsyncExitStack,
    ) -> T:
        """Resolve the resource once, entering cleanup into the given stack.

        Each call uses a fresh dependency cache. Handler binding goes through
        :func:`resolve_resource` with the request's shared cache instead, so a
        resource reused across a request resolves exactly once.
        """

        return await resolve_resource(self, request, {}, lambda: stack)

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        provider_name = getattr(self.provider, "__name__", None)
        return provider_name if isinstance(provider_name, str) else "resource"


def _reject_variadic_parameters(provider: Callable[..., object]) -> None:
    try:
        signature = inspect.signature(provider)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            "Resource provider signature could not be inspected"
        ) from exc
    for parameter in signature.parameters.values():
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise ConfigurationError("Resource providers cannot use *args or **kwargs")


def _provider_hints(provider: Callable[..., object]) -> Mapping[str, object]:
    try:
        return get_type_hints(provider, include_extras=True)
    except (NameError, TypeError):
        return {}


def _resource_from_annotation(annotation: object) -> Resource[Any] | None:
    if get_origin(annotation) is not Annotated:
        return None
    found: Resource[Any] | None = None
    for metadata in get_args(annotation)[1:]:
        if isinstance(metadata, Resource):
            if found is not None:
                raise ConfigurationError(
                    "Only one resource is supported in a type annotation"
                )
            found = metadata
    return found


def _build_plan(resource: Resource[Any]) -> tuple[_ProviderParam, ...]:
    provider = resource.provider
    signature = inspect.signature(provider)
    hints = _provider_hints(provider)
    plan: list[_ProviderParam] = []
    seen_request = False
    # Variadic parameters are already rejected when the Resource is constructed.
    for parameter in signature.parameters.values():
        annotation = hints.get(parameter.name, parameter.annotation)
        dependency = _resource_from_annotation(annotation)
        is_request = parameter.name == "request" or annotation is Request
        keyword_only = parameter.kind is inspect.Parameter.KEYWORD_ONLY
        if dependency is not None:
            if is_request:
                raise ConfigurationError(
                    f"Resource provider parameter {parameter.name!r} cannot be both "
                    "the request and a resource"
                )
            plan.append(_ProviderParam(parameter.name, dependency, keyword_only))
        elif is_request:
            if seen_request:
                raise ConfigurationError(
                    "Resource providers may accept the request only once"
                )
            seen_request = True
            plan.append(_ProviderParam(parameter.name, None, keyword_only))
        else:
            raise ConfigurationError(
                f"Resource provider {resource.display_name!r} parameter "
                f"{parameter.name!r} could not be resolved: name it 'request' or "
                "annotate it with Annotated[T, resource]"
            )
    return tuple(plan)


def _ensure_plan(resource: Resource[Any]) -> tuple[_ProviderParam, ...]:
    plan = resource._plan
    if plan is None:
        plan = _build_plan(resource)
        object.__setattr__(resource, "_plan", plan)
    return plan


def validate_resource(
    resource: Resource[Any],
    _path: list[Resource[Any]] | None = None,
) -> None:
    """Validate a resource and its dependencies at route compile time.

    Builds each provider's plan (rejecting unresolvable parameters) and walks
    the dependency graph depth-first to reject cycles before the first request.
    """

    if resource._validated:
        return
    if _path is None:
        _path = []
    for index, entry in enumerate(_path):
        if entry is resource:
            chain = [*_path[index:], resource]
            names = " -> ".join(item.display_name for item in chain)
            raise ConfigurationError(f"Resource dependency cycle detected: {names}")
    _path.append(resource)
    for parameter in _ensure_plan(resource):
        if parameter.resource is not None:
            validate_resource(parameter.resource, _path)
    _path.pop()
    object.__setattr__(resource, "_validated", True)


async def resolve_resource(
    resource: Resource[T],
    request: Request,
    cache: dict[int, object],
    get_stack: StackFactory,
) -> T:
    """Resolve a resource and its dependencies, caching by resource identity.

    Dependencies resolve first and share ``cache``, so a resource reused across
    a request is built once. ``get_stack`` is called only when a value actually
    needs cleanup, so resolving plain values opens no exit stack.
    """

    key = id(resource)
    cached = cache.get(key, _UNRESOLVED)
    if cached is _RESOLVING:
        raise ConfigurationError(
            f"Resource dependency cycle detected at {resource.display_name!r}"
        )
    if cached is not _UNRESOLVED:
        return cast(T, cached)
    cache[key] = _RESOLVING
    try:
        args: list[object] = []
        kwargs: dict[str, object] = {}
        for parameter in _ensure_plan(resource):
            if parameter.resource is None:
                value: object = request
            else:
                value = await resolve_resource(
                    parameter.resource, request, cache, get_stack
                )
            if parameter.keyword_only:
                kwargs[parameter.name] = value
            else:
                args.append(value)
        result = resource.provider(*args, **kwargs)
        resolved = cast(
            T,
            await _resolve_provider_result(
                result, get_stack, name=resource.display_name
            ),
        )
    except BaseException:
        cache.pop(key, None)
        raise
    cache[key] = resolved
    return resolved


async def _resolve_provider_result(
    result: object,
    get_stack: StackFactory,
    *,
    name: str,
) -> object:
    if inspect.isasyncgen(result):
        return await get_stack().enter_async_context(
            _async_generator_context(result, name)
        )
    if inspect.isgenerator(result):
        return get_stack().enter_context(_generator_context(result, name))
    if _is_async_context_manager(result):
        async_manager = cast(AbstractAsyncContextManager[object], result)
        return await get_stack().enter_async_context(async_manager)
    if _is_context_manager(result):
        sync_manager = cast(AbstractContextManager[object], result)
        return get_stack().enter_context(sync_manager)
    if inspect.isawaitable(result):
        awaited = await result
        return await _resolve_provider_result(awaited, get_stack, name=name)
    return result


@asynccontextmanager
async def _async_generator_context(
    generator: AsyncGenerator[object, None],
    name: str,
) -> AsyncGenerator[object, None]:
    try:
        value = await generator.__anext__()
    except StopAsyncIteration as exc:
        raise RuntimeError(f"Resource provider {name!r} did not yield a value") from exc

    try:
        yield value
    except BaseException as exc:
        try:
            await generator.athrow(type(exc), exc, exc.__traceback__)
        except StopAsyncIteration:
            pass
        except BaseException as thrown:
            if thrown is not exc:
                raise
        else:
            raise RuntimeError(f"Resource provider {name!r} yielded more than once")
        raise
    else:
        try:
            await generator.__anext__()
        except StopAsyncIteration:
            return
        raise RuntimeError(f"Resource provider {name!r} yielded more than once")


@contextmanager
def _generator_context(
    generator: Generator[object, None, None],
    name: str,
) -> Generator[object, None, None]:
    try:
        value = next(generator)
    except StopIteration as exc:
        raise RuntimeError(f"Resource provider {name!r} did not yield a value") from exc

    try:
        yield value
    except BaseException as exc:
        try:
            generator.throw(type(exc), exc, exc.__traceback__)
        except StopIteration:
            pass
        except BaseException as thrown:
            if thrown is not exc:
                raise
        else:
            raise RuntimeError(f"Resource provider {name!r} yielded more than once")
        raise
    else:
        try:
            next(generator)
        except StopIteration:
            return
        raise RuntimeError(f"Resource provider {name!r} yielded more than once")


def _is_async_context_manager(
    value: object,
) -> bool:
    return isinstance(value, AbstractAsyncContextManager) or (
        hasattr(value, "__aenter__") and hasattr(value, "__aexit__")
    )


def _is_context_manager(value: object) -> bool:
    return isinstance(value, AbstractContextManager) or (
        hasattr(value, "__enter__") and hasattr(value, "__exit__")
    )


__all__ = [
    "Resource",
    "ResourceMap",
    "ResourceProvider",
    "ResourceScope",
    "resolve_resource",
    "validate_resource",
]
