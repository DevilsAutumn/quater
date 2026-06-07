---
name: quater-framework
description: Build, modify, test, document, or debug applications that use the Quater Python framework. Use when an agent needs to write Quater routes, configure Quater(), add MCP tools or CLI actions, use route auth, resources, state, middleware, form/file binding, OpenAPI docs, TestClient, deployment commands, or production settings.
---

# Quater Framework

Use this skill when writing or reviewing code for a Quater application. Quater is
a typed Python backend framework where selected route handlers can be reached as
HTTP endpoints, MCP tools, and CLI actions.

If the current agent does not support skills, treat this file and the linked
references as project instructions.

## Live Docs

Use these docs as the canonical framework reference:

- Overview: https://quater.devilsautumn.com/en/stable/
- Quickstart: https://quater.devilsautumn.com/en/stable/quickstart
- Routes and handlers: https://quater.devilsautumn.com/en/stable/routes-handlers
- HTTP, MCP, and CLI surfaces: https://quater.devilsautumn.com/en/stable/surfaces
- Resources and state: https://quater.devilsautumn.com/en/stable/resources
- Testing: https://quater.devilsautumn.com/en/stable/testing
- Deployment: https://quater.devilsautumn.com/en/stable/deployment
- API reference: https://quater.devilsautumn.com/en/stable/reference/

## Development Workflow

1. Inspect the existing app structure before changing code.
2. Keep the route handler as the source of application behavior.
3. Opt into MCP with `tool=True` and CLI with `cli=True`; never expose routes by
   default.
4. Use route/group `auth=` for handler protection. Use `mcp_auth` and
   `cli_auth` for surface protection.
5. Use `Resource` and `inject={...}` for request-scoped dependencies. Use
   `app.state` for long-lived objects created during startup.
6. Use `msgspec.Struct` for typed JSON bodies. Use `Form` and `File` only when
   clients need form posts or multipart uploads.
7. Test behavior through `TestClient` or `MCPTestClient` rather than calling
   private internals.
8. Run the repo's checks after meaningful changes.

## Core References

- `references/app-patterns.md`: app setup, routing, binding, responses, and
  config.
- `references/surfaces.md`: HTTP, MCP, CLI, auth layering, approval, and file
  exposure rules.
- `references/resources-testing.md`: `Resource`, `app.state`, lifespan hooks,
  and testing patterns.
- `references/deployment.md`: `quater dev`, `quater run`, RSGI, environment
  variables, and production safety.

Load only the reference needed for the current task.

## Code Style Rules

- Import public APIs from `quater`, not private modules.
- Keep handlers `async def`.
- Keep comments sparse and specific.
- Prefer explicit markers when a parameter source may be unclear:
  `Path`, `Query`, `Body`, `Form`, `File`, `Header`, and `Cookie`.
- Do not combine JSON `Body` parameters with `Form` or `File` parameters in one
  route.
- Do not expose `File` routes as MCP tools or CLI actions.
- Do not add global auth as a replacement for route/group auth.

## Validation

Use the project's own commands when available:

```bash
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync mypy src examples tests
uv run --no-sync pytest -q
npm run docs:build
```

When changing only an app outside the Quater repo, run that app's equivalent
tests and a small smoke request through the public surface.
