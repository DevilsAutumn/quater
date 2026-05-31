---
title: Quater changelog
description: Read Quater release notes, including added features, fixes, behavior changes, and migration notes.
---

# Changelog / Release Notes

This page records public release notes for Quater.

## Prerequisites

Read [Stability](/en/dev/stability) before depending on the pre-release API.

## 0.1.0a3

### Added

- Added support for declaring a `Resource` in a parameter's `Annotated[...]`
  type metadata (for example `session: Annotated[Session, db_session]`) as an
  alternative to the decorator `inject={...}` map. This allows reusable
  `Annotated` aliases shared across handlers, type-checks with no cast, and
  produces the same binding — excluded from caller-facing schemas — as `inject`.
  Declaring a parameter's resource in both places, or as a parameter default, is
  rejected during route compilation.
  ([#48](https://github.com/DevilsAutumn/quater/issues/48))
- Added support for resources that depend on other resources. A `Resource`
  provider can now declare parameters annotated with `Annotated[T, other]`, the
  same way a handler does; Quater resolves each dependency first, once, from the
  request's shared scope, and passes it in. Dependencies stay private to the
  provider — they never appear in OpenAPI, MCP, or CLI schemas. The dependency
  graph is validated when routes compile: dependency cycles and provider
  parameters that are neither the request nor a resource fail at startup.
  ([#53](https://github.com/DevilsAutumn/quater/issues/53))
- Added real-database integration tests for the resource lifecycle — async and
  sync sessions, transaction commit and rollback, and one session shared per
  request — across HTTP, MCP, and CLI, on a reusable SQLAlchemy/SQLite test
  harness. ([#57](https://github.com/DevilsAutumn/quater/issues/57))
- Added a `CliTestClient`, reachable as `client.cli` on the in-process
  `TestClient`, with `call()` and `manifest()` helpers for the CLI action
  surface. HTTP, MCP (`client.mcp`), and CLI now each have a first-class test
  helper. ([#57](https://github.com/DevilsAutumn/quater/issues/57))

### Changed

- Changed request handling to resolve every injected `Resource` through a
  single per-request scope. The same `Resource` now opens once per request — one
  database session serves the whole request — and is torn down once, in reverse
  order, even when a resource fails to open partway through. The scope is lazy:
  a request that injects nothing never allocates one, and nothing opened for one
  request is ever visible to another. The MCP and CLI paths now share that one
  scope between authentication and the handler instead of building separate
  request objects. ([#52](https://github.com/DevilsAutumn/quater/issues/52))
- Reworked authentication into per-surface `AuthConfig` objects. An app is configured
  with `Quater(auth=[AuthConfig(fn, surfaces=["api", "mcp", "cli"])])`, and exactly one
  authenticator runs per request, chosen by `request.context.source`. The
  authenticator receives the real `Request`; after cheap header/token checks it
  can call `await request.resolve(SessionDep)` to open the same request-scoped
  resource alias that the handler injects. That resource shares the handler's
  scope, so a session auth opens to verify the caller is the same session the
  handler injects. `AuthContext` gained a typed `payload` slot to
  carry the loaded object (for example the `User`) so a handler reads it back
  through a resource with no second query. Routes are protected by default and
  opt out with `public=True` (every exposed surface) or `public=["mcp", ...]`
  (named surfaces). Remote CLI now reads the action name before auth, matching
  MCP. ([#54](https://github.com/DevilsAutumn/quater/issues/54))
- Changed global middleware and exception handlers to wrap the real route
  handler on HTTP, MCP tools, and CLI actions. MCP `tools/call` and CLI action
  calls now run global `before`, `around`, `after`, and exception handlers
  around the handler response before Quater creates the JSON-RPC or action RPC
  envelope. Remote CLI no longer runs global middleware on the outer RPC wrapper,
  avoiding double execution. **Migration note:** HTTP-shaped global middleware
  such as cookies, redirects, HTML pages, or browser-only headers should check
  `request.context.source` and skip `"mcp"`/`"cli"` when needed.
  ([#55](https://github.com/DevilsAutumn/quater/issues/55))

### Removed

- **Breaking:** removed the `mcp_auth=` and `cli_auth=` constructor hooks, the
  per-route and per-group `auth=` argument, the `AuthRequest` type, and the
  `Authenticate` alias. Migrate by moving each authenticator into the matching
  surface's `AuthConfig` and switching authenticators to take the real `Request`;
  routes that were public drop `auth=` and add `public=` only where an `AuthConfig`
  now covers their surface. See [Auth Model](/en/dev/auth-model#migrating-from-surface-hooks).

## 0.1.0a2

This alpha tightens fail-fast validation around auth headers, CORS,
production-facing config, and adapter response safety.

### Fixed

- Added duplicate `Authorization` and `Proxy-Authorization` header validation
  before auth hooks run.
- Added CORS `allowed_methods` validation during configuration and included
  `HEAD` in the default CORS method set.
- Added validation for single-string, bytes, mapping, and non-string values in
  CORS list-like config fields before app startup.
- Changed ASGI path extraction to preserve encoded path segments from
  `raw_path` when servers provide it.
- Added validation for single-string and non-string values in list-like config
  fields before app startup.
- Added validation for non-string optional config fields and boolean or
  non-numeric limit settings before app startup.
- Added malformed `Cookie` header handling that returns `400 Bad Request`.
- Added malformed bracketed `Host` header validation before route auth runs.
- Added response value validation before adapters write HTTP responses, so bad
  response bodies, status codes, and stream chunks fail safely.
- Changed ASGI request body reads to reject client disconnects instead of
  passing partial request bodies to handlers.
- Changed route auth to run even when a request already has an auth context.
- Changed request body reads to cache read and size-limit failures instead of
  invoking the body reader again.
- Changed shutdown hook failures to mark lifespan as failed instead of started.
- Changed tool and action registry access to compile dirty routes once and keep
  the HTTP router current.
- Removed duplicate request security-context resolution from the HTTP hot path.
- Changed size-string parsing to reject whitespace between the number and unit.
- Changed remote CLI config to store only connection details and fetch action
  discovery on demand instead of persisting remote manifests.

## 0.1.0a1

This is the first alpha release shape for evaluation.

### Added

- `Quater` application object with RSGI, ASGI, and WSGI adapters.
- Typed route decorators for `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, and custom
  methods.
- Path, query, header, cookie, and JSON body binding.
- `msgspec` JSON serialization and validation.
- Route-level auth with `auth=`.
- MCP tools with `tool=True`, `mcp_auth`, `tools/list`, and `tools/call`.
- Human-readable MCP docs at `/mcp/docs`.
- CLI actions with `cli=True`, local execution, remote execution, dry-run, and
  approval hooks.
- Generated OpenAPI JSON and Swagger UI.
- `Resource` injection and `app.state`.
- Route groups that flatten at startup.
- In-process `TestClient` and `MCPTestClient`.
- CORS, allowed-host checks, body limits, security headers, request IDs, signed
  cookies, and production safety checks.

### Breaking

No previous public release exists, so there are no migration steps.

### Fixed

No previous public release exists.

### Deprecated

No public API is deprecated in this alpha.

## What Can Go Wrong

`No matching distribution found for quater==0.1.0a1`
: Check whether you are installing from the intended package index. Early alpha
  testing may use TestPyPI before the package is published to PyPI.

## Also See

- [Known Limitations](/en/dev/known-limitations): current gaps.
- [Stability](/en/dev/stability): public API expectations before 1.0.
- [Quickstart](/en/dev/quickstart): first working app.
