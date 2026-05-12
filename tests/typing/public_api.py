from __future__ import annotations

from typing import assert_type

from quater import Quater, RouteGroup, __version__

app = Quater()
group = RouteGroup(prefix="/api")

assert_type(app, Quater)
assert_type(group, RouteGroup)
assert_type(app.name, str | None)
assert_type(__version__, str)
