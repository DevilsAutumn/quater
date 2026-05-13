# Stability

Quater is still in alpha, so the rules here matter. They explain which parts of
the framework you can build on, and which parts are still free for Quater to
change while the internals settle.

## Public Import API

For application code, import from `quater`:

```python
from quater import AuthContext, AuthRequest, JSONResponse, Quater, Request
```

The names exported by `quater.__all__` are the public Python API. Those names are
what the [Reference](/en/latest/reference/) documents.

Quater also keeps a few compatibility modules public for advanced typing and
server integration:

| Module | Use it when |
| --- | --- |
| `quater.adapters` | You need an explicit `ASGIAdapter`, `RSGIAdapter`, or `WSGIAdapter`. Most apps use `app.asgi`, `app.rsgi`, or `app.wsgi` instead. |
| `quater.exceptions` | You need to catch a specific framework exception. |
| `quater.testing` | You prefer importing `TestClient` from the testing module instead of the top-level package. |
| `quater.typing` | You need hook aliases such as `Authenticate`, `LifespanHook`, or `RequestContext`. |
| `quater.types` | Backward-compatible typing aliases. Prefer `quater.typing` in new code. |

::: tip
If a guide or reference page imports a name from `quater`, that import path is
the one to copy into your app.
:::

## Internal Modules

Anything else under `quater.*` is internal unless a page says otherwise. That
includes modules such as `quater.app`, `quater.router`, `quater.actions`,
`quater.protocol`, `quater.docs`, and `quater.tools.registry`.

Those modules exist because the framework needs them, but they are not extension
points. They may move, change shape, or disappear before Quater reaches a stable
release.

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

Quater follows semantic versioning once it reaches `1.0.0`.

Before `1.0.0`, breaking changes can happen in minor or alpha releases, but they
should be called out in release notes and kept focused. The goal is to fix bad
names and weak contracts early, not to surprise people for no reason.

After `1.0.0`:

- patch releases fix bugs without breaking public APIs.
- minor releases add public APIs without breaking existing ones.
- major releases are the place for breaking changes.

## Experimental APIs

Quater does not currently expose experimental Python APIs as stable imports. If
an experimental API is added later, it should be documented as experimental and
kept out of the normal stability promise until it graduates.

Internal modules are not experimental APIs. They are private framework code.

## Command Line and Protocol Paths

The `quater` command is public user interface. Commands may grow new options,
but existing documented commands should stay compatible unless a release note
clearly says otherwise.

The remote action endpoints are implementation details of the Quater CLI:

- `/.well-known/quater-actions.json`
- `/__quater__/actions/call`

Use the CLI instead of writing third-party clients against those paths for now.
The protocol can become a formal public contract later, but it should not be
treated as one during the alpha.
