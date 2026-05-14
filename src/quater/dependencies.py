"""Request-scoped resources for handler injection."""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Callable, Generator, Mapping
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from dataclasses import dataclass, field
from typing import Literal, cast, get_type_hints

from quater.exceptions import ConfigurationError
from quater.request import Request

ResourceScope = Literal["request"]
ResourceProvider = Callable[..., object]
ResourceMap = Mapping[str, "Resource"]


@dataclass(frozen=True, slots=True)
class Resource:
    """A request-scoped value that Quater can inject into route handlers.

    Providers may return a value, an awaitable value, a context manager, an
    async context manager, or yield one value from a generator. Generator and
    context-manager providers are cleaned up after the handler finishes.
    """

    provider: ResourceProvider
    scope: ResourceScope = "request"
    name: str | None = None
    _request_parameter: str | None = field(init=False, repr=False, compare=False)
    _request_keyword_only: bool = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.scope != "request":
            raise ConfigurationError("Resource scope must be 'request'")
        if not callable(self.provider):
            raise TypeError("Resource provider must be callable")

        request_parameter, keyword_only = _provider_request_parameter(self.provider)
        object.__setattr__(self, "_request_parameter", request_parameter)
        object.__setattr__(self, "_request_keyword_only", keyword_only)

    async def resolve(
        self,
        request: Request,
        stack: AsyncExitStack,
    ) -> object:
        """Resolve the resource for one handler call."""

        result = self._call_provider(request)
        return await _resolve_provider_result(result, stack, name=self.display_name)

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        provider_name = getattr(self.provider, "__name__", None)
        return provider_name if isinstance(provider_name, str) else "resource"

    def _call_provider(self, request: Request) -> object:
        request_parameter = self._request_parameter
        if request_parameter is None:
            return self.provider()
        if self._request_keyword_only:
            return self.provider(**{request_parameter: request})
        return self.provider(request)


def _provider_request_parameter(
    provider: ResourceProvider,
) -> tuple[str | None, bool]:
    try:
        signature = inspect.signature(provider)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            "Resource provider signature could not be inspected"
        ) from exc

    parameters = tuple(signature.parameters.values())
    if any(
        parameter.kind
        in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        for parameter in parameters
    ):
        raise ConfigurationError("Resource providers cannot use *args or **kwargs")

    accepted = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }
    parameters = tuple(
        parameter for parameter in parameters if parameter.kind in accepted
    )
    if not parameters:
        return None, False
    if len(parameters) > 1:
        raise ConfigurationError(
            "Resource providers may accept only one parameter: request"
        )

    parameter = parameters[0]
    annotation = _provider_annotation(provider, parameter.name, parameter.annotation)
    if parameter.name != "request" and annotation is not Request:
        raise ConfigurationError(
            "Resource provider parameter must be named 'request' or typed as Request"
        )
    return parameter.name, parameter.kind is inspect.Parameter.KEYWORD_ONLY


def _provider_annotation(
    provider: ResourceProvider,
    name: str,
    fallback: object,
) -> object:
    try:
        return get_type_hints(provider).get(name, fallback)
    except (NameError, TypeError):
        annotations = getattr(provider, "__annotations__", {})
        if isinstance(annotations, Mapping):
            return annotations.get(name, fallback)
        return fallback


async def _resolve_provider_result(
    result: object,
    stack: AsyncExitStack,
    *,
    name: str,
) -> object:
    if inspect.isasyncgen(result):
        return await stack.enter_async_context(_async_generator_context(result, name))
    if inspect.isgenerator(result):
        return stack.enter_context(_generator_context(result, name))
    if _is_async_context_manager(result):
        async_manager = cast(AbstractAsyncContextManager[object], result)
        return await stack.enter_async_context(async_manager)
    if _is_context_manager(result):
        sync_manager = cast(AbstractContextManager[object], result)
        return stack.enter_context(sync_manager)
    if inspect.isawaitable(result):
        awaited = await result
        return await _resolve_provider_result(awaited, stack, name=name)
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
    except BaseException:
        await generator.aclose()
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
    except BaseException:
        generator.close()
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


__all__ = ["Resource", "ResourceMap", "ResourceProvider", "ResourceScope"]
