# Known Limitations

This page lists the current limits of Quater so you can decide whether it fits
your project today.

## Prerequisites

Read [Why Quater Exists](/en/latest/why-quater) first. This page is about the
current pre-release framework, not the long-term ambition.

## Current Limits

Quater is pre-release. It is useful for evaluating the human-and-agent backend
model, but it does not yet cover every feature a mature production framework
usually provides.

| Area | Current state | What to do today |
| --- | --- | --- |
| WebSockets | No framework-level WebSocket API yet. | Use a separate ASGI app or wait for Quater support. |
| ORM and migrations | Quater does not ship a database layer. | Use SQLAlchemy, SQLModel, Piccolo, or another library. |
| Background jobs | No built-in task queue. | Use a separate worker system. |
| Rate limiting | No framework-level limiter yet. | Put rate limiting at a proxy or middleware layer. |
| Static files | Not a primary framework feature. | Serve static assets from your frontend host or edge layer. |
| MCP streaming | `initialize`, `tools/list`, and `tools/call` are supported. Streaming progress is not. | Keep tools short-running or report progress through your app today. |
| Remote action protocol | The Quater CLI uses it, but it is not a stable third-party protocol yet. | Treat it as Quater-owned until the framework stabilizes. |
| OpenAPI depth | Core schemas are generated, but OpenAPI polish is still younger than FastAPI. | Check generated docs before publishing a public API. |

## Why These Limits Exist

Quater is trying to get the core model right first: one backend operation,
normal API access, safe agent access, safe operator access, typed binding,
explicit auth, resources, tests, and production checks.

Adding every feature too early would make the public surface harder to change
before the first stable release.

## What Can Go Wrong

`WebSocket support is not available`
: Quater does not expose a public WebSocket API yet. Do not depend on private
adapter internals for this.

`OpenAPI output does not describe a complex type the way you expected`
: Check the generated `/openapi.json` before treating it as a stable public
contract.

## Also See

- [Stability](/en/latest/stability): what is public before the first stable
  release.
- [Changelog / Release Notes](/en/latest/changelog): what changed in each
  release.
- [Deployment](/en/latest/deployment): what Quater does and does not check for
  production.
