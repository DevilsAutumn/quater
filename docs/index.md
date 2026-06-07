---
layout: home
title: Quater - Build applications for Humans and AI agents.
description: Build Python backend APIs that humans can use through HTTP and AI agents can operate through MCP tools or CLI actions.

hero:
  text: Build applications for people, MCP clients, and AI agents.
  tagline: A Python backend framework for the agent era.
  actions:
    - theme: brand
      text: Start Building
      link: /en/dev/quickstart

features:
  - title: One route, three surfaces
    details: Write the handler once, then opt it into MCP tools or CLI actions when agents should use it directly.
  - title: Know who called
    details: Every request carries its source, so your handler can tell whether it came from HTTP, MCP, local CLI, or remote CLI.
  - title: Agent access has gates
    details: MCP auth, CLI auth, surface-wide opt-outs, audits, and approvals stay separate, so direct access still follows your rules.
  - title: Fast path by default
    details: Granian/RSGI, msgspec, and the native router keep the framework layer small.
---

## Start Here

Quater starts from a simple belief: AI agents need a better interface to
software than screens meant for humans. The answer is not to bypass your
backend. The answer is to expose the right backend views directly, with
clear inputs and real safety boundaries.

This site documents Quater's current 0.x API. If you are evaluating the
framework, start with the [Quickstart](/en/dev/quickstart), then read the
[Manual](/en/dev/) to understand how HTTP, MCP, and CLI access fit together.

Prerequisites: Python 3.11 or newer, async Python basics, and enough HTTP
knowledge to read request and response examples.

## One View, Three Ways To Call It

```python
from quater import AuthConfig, AuthContext, Quater, Request


async def authenticate(request: Request) -> AuthContext | None:
    if request.headers.get("authorization") != "Bearer demo-token":
        return None
    return AuthContext(subject="demo-user")


app = Quater(auth=[AuthConfig(authenticate, surfaces=["api", "mcp", "cli"])])


@app.get(
    "/orders/{order_id}",
    tool=True,
    cli=True,
    description="Fetch one order by id.",
)
async def get_order(order_id: str, request: Request) -> dict[str, object]:
    assert request.auth is not None
    return {
        "order_id": order_id,
        "subject": request.auth.subject,
        "source": request.context.source,
    }
```

Run it:

```bash
python -m pip install quater
quater dev main.py
```

If you use [uv](https://docs.astral.sh/uv/), install with `uv add quater`
instead.

Expected server output:

```text
[INFO] Starting granian
[INFO] Listening at: http://127.0.0.1:8000
```

1. Call it as HTTP:

```bash
curl -H "Authorization: Bearer demo-token" \
  http://127.0.0.1:8000/orders/ord_1001
```

2. Call it as an MCP tool:

```bash
curl http://127.0.0.1:8000/mcp \
  -H "Authorization: Bearer demo-token" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_order","arguments":{"order_id":"ord_1001"}}}'
```

3. Call it from the CLI:

```bash
export QUATER_APP=main:app
export QUATER_TOKEN=demo-token
quater call get_order --order-id ord_1001
```

All three calls reach the same handler. The `source` value tells you which
surface called it: `api`, `cli`, or `mcp`.


## Also See

- [Quickstart](/en/dev/quickstart): first working app.
- [Why Quater Exists](/en/dev/why-quater): the problem behind the framework.
- [HTTP, MCP, and CLI Surfaces](/en/dev/surfaces): how the three access paths
  fit together.
- [Public API](/en/dev/api): full public surface.
- [Deployment](/en/dev/deployment): production setup and checks.
