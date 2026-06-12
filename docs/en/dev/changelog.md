---
title: Quater changelog
description: Read Quater release notes, including added features, fixes, behavior changes, and migration notes.
---

# Changelog / Release Notes

This page records public release notes for Quater.

## Prerequisites

Read [Stability](/en/dev/stability) before upgrading Quater versions.

## Latest

Unreleased changes on `main`. Renamed to the version number when the release is
cut.

### Changed

- Internal cleanup: removed unused internal helpers and added PUT route test
  coverage. No public API change.

### Fixed

- Documented WSGI as a compatibility-only interface and made it warn when
  lifespan hooks would be silently skipped. `on_startup`/`on_shutdown` run under
  RSGI and ASGI only; serving an app that has registered hooks through WSGI now
  logs a warning instead of dropping them silently.
  ([#87](https://github.com/DevilsAutumn/quater/issues/87))

- Fixed MCP and CLI validation errors that referred to a "query parameter" for
  scalar arguments, even though those surfaces have no query string. HTTP keeps
  the "query parameter" wording; MCP and CLI now say "parameter" (for example
  `Missing required parameter: name`). Header, cookie, and body wording is
  unchanged.

- Clarified that injecting `Request` directly into an MCP tool or CLI action
  handler yields the same synthetic request that `Header()`, `Cookie()`, and
  `Body()` markers produce — transport headers, cookies, and body are never
  visible to the handler. Updated `actions.md`, `mcp.md`, and the request
  reference accordingly, and added test coverage for both the CLI and MCP
  surfaces. ([#74](https://github.com/DevilsAutumn/quater/issues/74))

- Fixed intermittent CI failures in the router path-safety fuzz tests by
  disabling the Hypothesis 200 ms deadline, so a slow generated example no
  longer fails the run. Test-only; no public API change.
  ([#96](https://github.com/DevilsAutumn/quater/issues/96))

- Fixed `quater call` output. Remote `call` ignored the global `--json` flag and
  always printed the raw RPC envelope; it now honors `--json` and shares the local
  `call` formatter. Without `--json`, `call` renders the response body as JSON for
  both local and remote calls — local previously printed a Python `repr`
  (`{'id': 'ord_1001'}` now becomes `{"id": "ord_1001"}`) and remote previously
  printed the whole envelope. With `--json` it prints the full action envelope,
  and remote dry runs now show the same summary as local.
  ([#75](https://github.com/DevilsAutumn/quater/issues/75))

- Fixed request `Cookie` header parsing so cookies named after Set-Cookie
  attributes (`path`, `domain`, `expires`, `max-age`, `secure`, `httponly`,
  `samesite`, `version`, `comment`) are read correctly. The header is now parsed
  directly instead of with `SimpleCookie`, so a reserved-word cookie no longer
  drops itself or, when it leads the header, every cookie after it. Malformed
  segments are skipped instead of failing the request. The `TestClient` and the
  MCP/CLI action surfaces can now also send those reserved names, keeping cookie
  arguments at parity with HTTP.
  ([#107](https://github.com/DevilsAutumn/quater/issues/107))

## 0.1.0

### Fixed

- Fixed `:int` path parameters so only ASCII digit segments match integer
  routes. Signed values, underscore grouping, Unicode digits, and surrounding
  whitespace now fall through as non-matching paths instead of resolving to the
  same handler.
- Fixed MCP and CLI action calls for `:int` path parameters so they reject the
  same non-canonical values as HTTP instead of accepting Python `int()` aliases.
- Fixed RSGI request body limits so chunked uploads without `Content-Length`
  return `413 Payload Too Large` as soon as the stream crosses `max_body_size`.
- Fixed remote CLI action calls so handler `ValueError`s and streaming response
  failures return `500 action_failed` instead of being mistaken for
  `response_too_large`. ([#97](https://github.com/DevilsAutumn/quater/issues/97))
- Fixed route compilation so path parameter annotations must match route
  converters, preventing `{id}` handlers annotated as `int` from receiving
  strings at runtime. ([#89](https://github.com/DevilsAutumn/quater/issues/89))

## 0.1.0b1

This started Quater's beta release train for 0.1. It marked the HTTP/MCP/CLI
surface model, per-surface auth, resource lifecycle, and testing helpers as
ready for broader evaluation before the final `0.1.0` release.

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
- Added `scope="function"` for `Resource` providers that need to finish before
  the response is sent, such as transaction/unit-of-work providers that commit
  after `yield`. The default `scope="request"` remains streaming-safe, and
  request-scoped resources cannot depend on function-scoped resources.
  ([#83](https://github.com/DevilsAutumn/quater/issues/83))
- Added real-database integration tests for the resource lifecycle — async and
  sync sessions, transaction commit and rollback, and one session shared per
  request — across HTTP, MCP, and CLI, on a reusable SQLAlchemy/SQLite test
  harness. ([#57](https://github.com/DevilsAutumn/quater/issues/57))
- Added a `CliTestClient`, reachable as `client.cli` on the in-process
  `TestClient`, with `call()` and `manifest()` helpers for the CLI action
  surface. HTTP, MCP (`client.mcp`), and CLI now each have a first-class test
  helper. ([#57](https://github.com/DevilsAutumn/quater/issues/57))
- Added security regression coverage proving callers cannot spoof
  `request.context.source` or `request.context.entrypoint` through HTTP headers,
  request bodies, MCP metadata, or remote CLI action payloads. HTTP remains
  `api/server`, MCP remains `mcp/server`, remote CLI remains `cli/server`, and
  local CLI remains `cli/local`.
  ([#70](https://github.com/DevilsAutumn/quater/issues/70))
- Added a cross-surface parity test matrix that calls the same handler through
  HTTP, MCP `tools/call`, local CLI, and remote CLI, then checks declared
  inputs, defaults, optional values, validation failures, handler errors, and
  the documented unknown-extra argument policy.
  ([#68](https://github.com/DevilsAutumn/quater/issues/68))
- Added contributor documentation, GitHub issue and PR templates, and a
  required pre-commit setup so new contributors can follow the same basic
  checks used by CI.

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
  can call `await request.resolve(resource)` to open the same request-scoped
  resource that the handler injects through an `Annotated[T, resource]` alias.
  That resource shares the handler's scope, so a session auth opens to verify
  the caller is the same session the handler injects. `AuthContext` gained a
  typed `payload` slot to
  carry the loaded object (for example the `User`) so a handler reads it back
  through a resource with no second query. A surface covered by `AuthConfig`
  protects its exposed routes by default; routes opt out with `public=True`
  (every exposed surface) or `public=["mcp", ...]` (named surfaces). Remote CLI
  now reads the action name before auth, matching
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
- Changed empty required JSON body binding to fail as request validation with
  `Missing required body parameter: ...` across HTTP, MCP tools, local CLI, and
  remote CLI. Direct `await request.json()` still reports malformed JSON for an
  empty or invalid body. ([#68](https://github.com/DevilsAutumn/quater/issues/68))

### Fixed

- Fixed yield resource cleanup so handler/authentication errors are thrown into
  generator providers. Rollback branches now run on request failure, and cleanup
  failures during an existing error no longer hide the primary response.
  ([#83](https://github.com/DevilsAutumn/quater/issues/83))
- Fixed HTTP path parameter parity across RSGI, ASGI, and WSGI. ASGI now
  percent-decodes `raw_path` before route matching, so encoded slashes split
  path segments the same way they do on Quater's primary Granian/RSGI path;
  WSGI also recovers UTF-8 path bytes before dispatch. ([#78](https://github.com/DevilsAutumn/quater/issues/78))
- Fixed RSGI response cleanup to await response finalizers before the adapter
  returns, matching ASGI and WSGI cleanup behavior for regular and streaming
  responses. ([#77](https://github.com/DevilsAutumn/quater/issues/77))
- Fixed protected action approval hashes to use the bound and validated handler
  arguments, including defaults and normalized scalar values, instead of the raw
  caller payload. Request and resource values stay out of the hash, so approval
  tokens now map to the operation Quater will actually run.
  ([#72](https://github.com/DevilsAutumn/quater/issues/72))
- Isolated synthetic MCP and CLI action requests from the outer transport
  request. Route handlers now only receive `Header()` and `Cookie()` values
  that were passed as action arguments, plus framework-generated headers needed
  for the synthetic body. Transport auth, cookies, protocol headers, request
  ids, and content length stay on the MCP/CLI surface instead of leaking into
  handler binding. ([#64](https://github.com/DevilsAutumn/quater/issues/64))
- Fixed HTTP JSON body binding so an empty optional or defaulted `Body` is
  treated like missing input, matching MCP and CLI action calls. Required empty
  bodies still return `400 Missing required body parameter`; non-empty malformed
  JSON and typed JSON `null` are still rejected normally.
  ([#66](https://github.com/DevilsAutumn/quater/issues/66))

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
- Added malformed bracketed `Host` header validation before surface auth runs.
- Added response value validation before adapters write HTTP responses, so bad
  response bodies, status codes, and stream chunks fail safely.
- Changed ASGI request body reads to reject client disconnects instead of
  passing partial request bodies to handlers.
- Changed surface auth to run even when a request already has an auth context.
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
- [Stability](/en/dev/stability): version pinning and upgrade expectations.
- [Quickstart](/en/dev/quickstart): first working app.
