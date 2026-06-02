from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from typing import Annotated, assert_type

from quater import Request, Resource


class Session:
    pass


def plain_provider() -> Session:
    return Session()


async def awaitable_provider() -> Session:
    return Session()


def generator_provider() -> Iterator[Session]:
    yield Session()


async def async_generator_provider() -> AsyncIterator[Session]:
    yield Session()


@contextmanager
def context_manager_provider() -> Iterator[Session]:
    yield Session()


@asynccontextmanager
async def async_context_manager_provider() -> AsyncIterator[Session]:
    yield Session()


plain_resource = Resource(plain_provider)
awaitable_resource = Resource(awaitable_provider)
generator_resource = Resource(generator_provider)
async_generator_resource = Resource(async_generator_provider)
context_manager_resource = Resource(context_manager_provider)
async_context_manager_resource = Resource(async_context_manager_provider)

SessionDep = Annotated[Session, plain_resource]

assert_type(plain_resource, Resource[Session])
assert_type(awaitable_resource, Resource[Session])
assert_type(generator_resource, Resource[Session])
assert_type(async_generator_resource, Resource[Session])
assert_type(context_manager_resource, Resource[Session])
assert_type(async_context_manager_resource, Resource[Session])


async def resolve_resources(request: Request, stack: AsyncExitStack) -> None:
    assert_type(await request.resolve(plain_resource), Session)
    assert_type(await request.resolve(awaitable_resource), Session)
    assert_type(await request.resolve(generator_resource), Session)
    assert_type(await request.resolve(async_generator_resource), Session)
    assert_type(await request.resolve(context_manager_resource), Session)
    assert_type(await request.resolve(async_context_manager_resource), Session)
    assert_type(await plain_resource.resolve(request, stack), Session)
    assert_type(await request.resolve(SessionDep), object)
