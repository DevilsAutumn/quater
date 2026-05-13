# Stability

Quater is in pre-release phase. That does not mean every piece is experimental,
but it does mean the project is still young enough to fix names, defaults, and
contracts before they become hard to change.

This page explains what to rely on today, and what to avoid building against.

## What To Import

For normal application code, import from `quater`:

```python
from quater import AuthContext, AuthRequest, Quater, Request
```

The [Public API](/en/latest/api) page is the source of truth for the documented
import surface. If a guide imports a name from `quater`, that is the path you
should copy into your app.

Some compatibility modules are also documented for specific cases:

- `quater.adapters` for explicit ASGI, RSGI, or WSGI adapter classes.
- `quater.exceptions` when you need to catch a framework exception.
- `quater.testing` if you prefer importing test clients from the testing module.
- `quater.typing` for hook aliases and request context types.

Those modules are okay to use when the docs point you there. For everyday app
code, the top-level package should be enough.

## What Is Internal

Most modules under `quater.*` are framework internals. Examples include
`quater.app`, `quater.router`, `quater.actions`, `quater.protocol`,
`quater.docs`, and `quater.tools.registry`.

They exist because Quater needs structure internally, not because they are meant
to be extension points. They may move or change while the framework settles.

Use this:

```python
from quater import Quater, Request
```

Not this:

```python
from quater.app import Quater
from quater.request import Request
```

## Versioning

For now, pin the Quater version you are using and read the release notes before
upgrading. Breaking changes should be rare and intentional, but they are still
possible while the API is being shaped.

After `1.0`, version numbers should mean the usual thing: patch releases fix
bugs, minor releases add compatible features, and major releases carry breaking
changes.

## CLI And Remote Protocol

The `quater` command is user-facing. Documented commands should stay familiar,
even if new options are added over time.

The remote action endpoints are different:

- `/.well-known/quater-actions.json`
- `/__quater__/actions/call`

They are used by the Quater CLI, but they are not yet a standalone public
protocol for third-party clients. Use `quater actions ...` and `quater call ...`
instead of writing directly against those URLs.

## Practical Rule

If it appears in a guide, the public API page, or the reference, it is something
you can try in application code today. If you had to discover it by opening an
internal module, treat it as private.
