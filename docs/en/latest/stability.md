# Stability

This page explains which Quater APIs you can rely on during the pre-release
period.

## Prerequisites

Read [Public API](/en/latest/api). This page matters when you decide what to
import, wrap, or extend in application code.

## Current Promise

Quater is pre-release. The project can still fix names, defaults, and contracts
before they become stable. The documented top-level imports are the API you
should try first.

```python
from quater import Quater, Request, Resource, RouteGroup
```

Prefer that style over importing implementation modules:

```python
from quater.app import Quater
```

The second form may work today, but it is not the path the docs promise for
application code.

## Public Import Boundary

Use names exported from `quater` and documented in the
[Reference](/en/latest/reference/):

- application objects: `Quater`, `RouteGroup`, `AppConfig`, `CORSConfig`
- request and state: `Request`, `State`
- binding markers: `Path`, `Query`, `Body`, `Header`, `Cookie`
- responses: `Response`, `JSONResponse`, `TextResponse`, `HTMLResponse`,
  `BytesResponse`, `StreamResponse`, `RedirectResponse`, `EmptyResponse`
- auth and security: `AuthRequest`, `AuthContext`, `ApprovalRequest`,
  `ActionApproval`, `HTTPError`, `ImproperlyConfigured`, `SignedCookieSigner`
- resources: `Resource`
- observability: `AccessLogEvent`, `AccessLogHook`, `ToolAuditEvent`
- testing: `TestClient`, `MCPTestClient`, `TestResponse`

Some compatibility modules exist for advanced cases, but the top-level import
should be enough for normal apps.

## Internal Modules

Treat these as internal unless a guide points you there:

- `quater.app`
- `quater.router`
- `quater.actions`
- `quater.protocol`
- `quater.docs`
- `quater.tools.registry`
- `quater.params`
- `quater.datastructures`

They exist so Quater can keep its implementation structured. They are not stable
extension points yet.

## Remote Action Protocol

The CLI uses:

- `/.well-known/quater-actions.json`
- `/__quater__/actions/call`

Those endpoints exist for the Quater CLI. Do not build third-party clients
directly on them yet. Use `quater actions ...` and `quater call ...`.

## Changelog And Migration

Quater release notes live in [Changelog / Release Notes](/en/latest/changelog).
While the project is pre-release, pin the exact version you test:

```bash
uv add "quater==0.1.0a1"
```

When a release contains a breaking change, the release note should include a
before-and-after snippet.

## What Can Go Wrong

`Loaded object is not a Quater application`
: You pointed the CLI at an object that is not a `Quater` instance.

`App factory target is not callable`
: You passed `--factory`, but the import target is not a function.

`ConfigurationError still exists in quater.exceptions`
: Use `ImproperlyConfigured` in new app code. `ConfigurationError` remains for
  compatibility with older internal names.

## Also See

- [Public API](/en/latest/api): what application code should import.
- [Reference](/en/latest/reference/): exact signatures.
- [Known Limitations](/en/latest/known-limitations): current pre-release gaps.
- [Deployment](/en/latest/deployment): direct server risks and production checks.
