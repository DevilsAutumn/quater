from __future__ import annotations

from typing import Any, assert_type

from quater import Body, Cookie, Header, Path, Quater, Query, RouteGroup, __version__

app = Quater()
group = RouteGroup(prefix="/api")

assert_type(app, Quater)
assert_type(group, RouteGroup)
assert_type(app.name, str | None)
assert_type(Query(), Any)
assert_type(Path(), Any)
assert_type(Body(), Any)
assert_type(Header(), Any)
assert_type(Cookie(), Any)
assert_type(__version__, str)
