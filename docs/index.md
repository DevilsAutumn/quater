---
layout: home

hero:
  text: Typed Python APIs for people and agents.
  tagline: Declare an operation once, then expose it as HTTP, an MCP tool, or an operational CLI action with explicit auth and fast msgspec serialization.
  actions:
    - theme: brand
      text: Start Building
      link: /en/latest/quickstart
    - theme: alt
      text: Public API
      link: /en/latest/api

features:
  - title: One handler, many surfaces
    details: A route can stay a normal HTTP endpoint and, when you opt in, become an MCP tool or CLI action without duplicating the handler.
  - title: Auth stays visible
    details: HTTP routes use route-level auth. MCP and CLI actions add their own transport boundary, then reuse route auth inside the handler.
  - title: Actions for operations
    details: Expose selected routes to a local or remote CLI with compact discovery, dry-run, and approval hooks for sensitive workflows.
  - title: Built around speed
    details: "Quater keeps the hot path small: Granian on RSGI, msgspec for JSON, and a native router underneath."
  - title: Docs by default
    details: OpenAPI, Swagger UI, and MCP tool docs are generated from the route metadata you already wrote.
  - title: In-process tests
    details: Test routes and MCP tools without starting a server, while still exercising auth, binding, cookies, lifespan hooks, and response serialization.
---
