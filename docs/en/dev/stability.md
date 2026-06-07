---
title: Quater versions and stability
description: Understand Quater's version policy, public import boundary, internal modules, and compatibility expectations.
---

# Versions And Stability

This page explains how to pick and upgrade Quater versions.

## Prerequisites

Read [Public API](/en/dev/api). This page matters when you decide what to
import, wrap, or extend in application code.

## Current Promise

Quater is still moving quickly. Current versions are `0.x.x`, and any release
can potentially include breaking changes. Pin the exact Quater version that
works with your app, read the release notes before upgrading, and run your
tests after each upgrade.

The documented top-level imports are the API you should try first.

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
[Reference](/en/dev/reference/):

- application objects: `Quater`, `RouteGroup`, `AppConfig`, `CORSConfig`
- request and state: `Request`, `State`
- binding markers: `Path`, `Query`, `Body`, `Header`, `Cookie`
- responses: `Response`, `JSONResponse`, `TextResponse`, `HTMLResponse`,
  `BytesResponse`, `StreamResponse`, `RedirectResponse`, `EmptyResponse`
- auth and security: `AuthConfig`, `AuthContext`, `ApprovalRequest`,
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

Quater release notes live in [Changelog / Release Notes](/en/dev/changelog).
Pin the exact version you test:

```bash
python -m pip install "quater==0.1.0"
```

If you use [uv](https://docs.astral.sh/uv/), pin with
`uv add "quater==0.1.0"` instead.

Upgrade deliberately: read the release notes, update the pin, run your app's
tests, and make any needed code changes before deploying the new version.

## Documentation Builds

Quater keeps one documentation source tree in `docs/en/dev`. A release does not
copy that tree into a versioned folder. The Git tag freezes the source docs for
that package version.

The docs site has two published channels:

- `/en/stable/`: built from the latest released tag with
  `QUATER_DOCS_CHANNEL=stable`.
- `/en/dev/`: built from `main` for unreleased work.

Use the changelog for exact package release notes. Only add long-lived archived
docs if a future compatibility line needs different guides for real users.

## What Can Go Wrong

`Loaded object is not a Quater application`
: You pointed the CLI at an object that is not a `Quater` instance.

`App factory target is not callable`
: You passed `--factory`, but the import target is not a function.

`ConfigurationError still exists in quater.exceptions`
: Use `ImproperlyConfigured` in new app code. `ConfigurationError` remains for
  compatibility with older internal names.

## Also See

- [Public API](/en/dev/api): what application code should import.
- [Reference](/en/dev/reference/): exact signatures.
- [Known Limitations](/en/dev/known-limitations): current gaps.
- [Deployment](/en/dev/deployment): direct server risks and production checks.
