# Changelog / Release Notes

This page records public release notes for Quater.

## Prerequisites

Read [Stability](/en/latest/stability) before depending on the pre-release API.

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

- [Known Limitations](/en/latest/known-limitations): current gaps.
- [Stability](/en/latest/stability): public API expectations before 1.0.
- [Quickstart](/en/latest/quickstart): first working app.
