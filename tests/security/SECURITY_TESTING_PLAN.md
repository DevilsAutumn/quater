# Quater Security Testing Plan

This plan tracks the security tests Quater needs before the first public release.
It focuses on proving that the framework fails closed across HTTP, MCP tools, and
CLI actions without adding a built-in auth system.

## Current Architecture Summary

Quater has one application object, `Quater`, that owns configuration, route
metadata, middleware, lifespan hooks, app state, and transport adapters.

The normal request path is:

1. The server adapter turns RSGI, ASGI, or WSGI input into a `Request`.
2. `Quater.handle()` applies request security checks: host validation,
   singleton header validation, content length limits, request id handling, and
   security headers.
3. The native router matches method and path.
4. Route auth runs when the matched route declares `auth=`.
5. Middleware and resource injection run around the handler.
6. Handler output becomes a `Response`.
7. CORS, security headers, request id headers, access logging, and finalizers run.

MCP requests enter through `/mcp`. Quater authenticates the MCP transport with
`mcp_auth`, parses JSON-RPC, then calls the same route-backed action executor for
`tools/call`.

Remote CLI requests enter through `/.well-known/quater-actions.json` and
`/__quater__/actions/call`. Quater authenticates those endpoints with `cli_auth`.
Local CLI calls import the app in process and authenticate through `cli_auth`
before they call the route-backed action executor.

Route groups are compile-time only. Quater flattens prefixes, inherited auth,
middleware, metadata, and resources before request dispatch.

## Security-Critical Modules

- `src/quater/app.py`: central dispatcher, route compilation, built-in routes,
  MCP and remote CLI entrypoints, auth ordering, response finalization.
- `src/quater/auth.py`: `AuthRequest` construction and auth hook result handling.
- `src/quater/router.py` and `native/router/src/lib.rs`: route matching, method
  mismatch handling, path normalization, converter enforcement.
- `src/quater/params.py`: handler binding, request source selection, body/query/
  header/cookie conversion, resource binding.
- `src/quater/request.py`: body caching, JSON parsing, max body size enforcement.
- `src/quater/response.py` and `src/quater/datastructures.py`: response
  serialization and response header validation.
- `src/quater/middleware.py`: exception handling and production/debug error
  response behavior.
- `src/quater/security.py`: allowed hosts, trusted proxies, content length, and
  default security headers.
- `src/quater/tools/mcp.py`: MCP JSON-RPC validation, auth flow, audit behavior,
  error shaping, response size caps.
- `src/quater/actions/executor.py`: shared MCP/CLI action preparation, auth
  ordering, argument normalization, header/cookie argument safety.
- `src/quater/protocol/actions.py`: remote CLI manifest, response wrapping, and
  response size caps.
- `src/quater/cli/*`: local CLI auth, remote config storage, remote calls, and
  machine-readable output.

## Highest-Value Tests Implemented First

These tests live in `tests/security/`:

- Auth cannot be bypassed by returning malformed auth results.
- Auth denial and auth exceptions never call protected handlers.
- HTTP, MCP, and remote CLI calls enforce the same route auth gate.
- MCP and CLI discovery only expose explicitly opted-in routes.
- Tool and action schemas do not expose framework/private handler parameters.
- Route matching cannot confuse static routes, method mismatches, encoded slash
  payloads, dot segments, unicode segments, or very long segments.
- Malformed request data fails safely and does not leak stack traces or secrets.
- Response serialization failures fail safely.
- Request context and request state stay isolated under concurrent calls.
- Hypothesis fuzzing covers route path confusion and query parsing failures.

## Current Contract and Security Notes

- Plain HTTP routes are public unless the route declares `auth=`.
- `tool=True` requires `mcp_auth` at app construction or route compilation.
- `cli=True` requires `cli_auth` at app construction or route compilation.
- `needs_approval=True` requires `tool=True` or `cli=True`, and requires an
  `action_approval` hook.
- Quater does not provide a permission DSL yet. Permission checks must live in
  user auth hooks, middleware, resources, or handlers. This is a documented MVP
  limitation, but it should be revisited before 1.0.

## Remaining Security Test Backlog

P0 before public release:

- Adapter malformed input tests for RSGI, ASGI, and WSGI, especially unusual
  header shapes and body reader failures.
- Local CLI security tests that assert `QUATER_TOKEN`, `--token`, and `--header`
  behavior across list, search, describe, dry run, and call.
- Audit hook failure tests for MCP and any future CLI audit hook.
- Debug error redaction policy. Production responses are already expected to be
  generic, but debug-mode secret redaction needs an explicit contract.

P1 before 1.0:

- Permission metadata or policy hook tests if Quater adds a central permission
  concept.
- Deep JSON nesting and pathological input benchmarks with explicit max limits.
- More Hypothesis coverage for headers, cookies, action arguments, and JSON-RPC
  payload shape.
- Security tests for app state and resources under cancellation.

P2 after 1.0:

- WebSocket auth tests if WebSockets are added.
- Static file traversal tests if static files are added.
- Upload filename and size-limit tests if file upload support is added.
- Plugin trust-boundary tests if a plugin system is added.

## CI Security Checks

The CI should keep these gates:

- `ruff format --check .`
- `ruff check .`
- `mypy src examples tests`
- `pytest`
- `cargo test --locked`
- `uv build`
- `twine check dist/*`
- `bandit -c pyproject.toml -r src/quater`
- `pip-audit`
- docs build and npm audit

Coverage should run in CI as a visibility gate. A hard threshold should wait
until the security suite stabilizes, otherwise developers will fight the number
instead of improving the tests.
