from __future__ import annotations

from typing import Any, assert_type

from quater import (
    Body,
    Cookie,
    File,
    Form,
    Header,
    Path,
    Quater,
    Query,
    Resource,
    RouteGroup,
    State,
    __version__,
)

app = Quater()
group = RouteGroup(prefix="/api")


async def load_resource() -> str:
    return "value"


resource = Resource(load_resource)

assert_type(app, Quater)
assert_type(group, RouteGroup)
assert_type(resource, Resource)
assert_type(app.name, str | None)
assert_type(app.state, State)
assert_type(Query(), Any)
assert_type(Path(), Any)
assert_type(Body(), Any)
assert_type(Form(), Any)
assert_type(File(), Any)
assert_type(Header(), Any)
assert_type(Cookie(), Any)
assert_type(__version__, str)
