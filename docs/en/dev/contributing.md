---
title: Contributing to Quater
description: Learn the Quater contribution process, local setup, checks, commit style, and pull request expectations.
---

# Contributing

Quater is still early, but the contribution process should be serious from the
start. The goal is not to add process for its own sake. The goal is to make it
clear how someone can pick up an issue, make a good change, and get it reviewed
without confusion.

## Contribution Flow

The normal path for contributing is:

1. Pick an open issue marked `accepted`.
2. Check that the issue is not assigned and nobody else has already claimed it.
3. Leave a comment before starting work.
4. Fork the repository.
5. Create a branch named `issue_{issue_number}`.
6. Make a focused change for that issue.
7. Run the relevant checks.
8. Open a pull request and link the issue.

The `accepted` tag means a maintainer has agreed that the issue is valid and
ready for contribution. If an issue is not marked `accepted`, treat it as a
discussion and do not start coding it yet.

If you need to stop after claiming an issue, leave an update so someone else can
pick it up.

## Local Setup

Requirements:

- Python 3.11+
- uv
- Rust stable, including a native linker
- Node.js 20 and npm

Quater builds a Rust router extension through `maturin` during local setup, so
Rust is required before running `uv sync`, even for Python-only changes. On
Windows, install the Visual Studio Build Tools C++ workload so `link.exe` is
available.

Fork the repo on GitHub, then clone your fork:

```bash
git clone https://github.com/YOUR_USERNAME/quater.git
cd quater
git remote add upstream https://github.com/DevilsAutumn/quater.git
```

Install everything:

```bash
uv sync --frozen --group dev --group release
npm ci
```

Run tests:

```bash
uv run --no-sync pytest -q
```

Run docs locally:

```bash
npm run docs:dev
```

Build docs:

```bash
npm run docs:build
```

## Pre-commit

Pre-commit is required for contributors.

Install it once:

```bash
uv run --no-sync pre-commit install
```

Run all hooks:

```bash
uv run --no-sync pre-commit run --all-files
```

The hooks run Ruff format check, Ruff lint, and mypy. These are the fast checks
contributors should run before opening a PR. CI runs additional checks.

## What Needs Design Discussion

Some changes should not start with code. Open or discuss the issue first when
the change touches:

- Public API shape
- Handler binding rules
- Auth behavior
- Resource lifecycle
- Middleware behavior
- MCP tool semantics
- Local or remote CLI action semantics
- Security behavior
- New dependencies
- Release or packaging flow

Quater's main promise is one backend handler that can safely serve HTTP, MCP,
and CLI. Any change to that contract needs extra care.

## Branch Convention

Use this branch format:

```bash
git checkout -b issue_75
```

The number should match the GitHub issue. Keep unrelated work out of the branch.

## Code Style

Follow nearby code.

Important rules:

- Keep public APIs small.
- Prefer explicit typed code.
- Keep errors readable.
- Avoid unrelated refactors.
- Do not turn internal modules into public APIs without discussion.
- Keep examples using imports from `quater`.
- Add comments only for behavior that is not obvious from the code.

## Testing Strategy

Choose tests based on the behavior being changed.

| Area | Test location |
| --- | --- |
| Small helpers, binding, router behavior | `tests/unit/` |
| CLI parsing, output, config | `tests/unit/cli/` |
| MCP tool calls | `tests/integration/test_mcp_tools_call.py` |
| Remote CLI protocol | `tests/integration/test_action_protocol.py` |
| HTTP/MCP/CLI parity | `tests/integration/test_cross_surface_parity.py` |
| Security boundaries | `tests/security/` |
| Public typing | `tests/typing/` |

For shared behavior, test more than one surface. A fix that works for HTTP but
breaks MCP or CLI is usually not complete.

## Docs And Release Notes

Update docs for user-facing behavior.

Use:

- `README.md` for the project overview
- `docs/en/dev/` for guides
- `docs/en/dev/reference/` for exact behavior and signatures
- `docs/en/dev/changelog.md` for release-visible changes

Use the changelog when the change affects public behavior, CLI output, docs
process, compatibility, security posture, or the release process.

## Checks

For most code PRs:

```bash
uv run --no-sync pre-commit run --all-files
uv run --no-sync pytest -q
```

For docs:

```bash
npm run docs:build
```

For packaging:

```bash
uv build
uv run --no-sync twine check dist/*
```

For Rust:

```bash
cargo test --locked
```

For security-sensitive changes:

```bash
uv run --no-sync bandit -q -c pyproject.toml -r src/quater
uv run --no-sync pip-audit
```

List the checks you ran in the pull request.

## Commit Messages

Use this format:

```text
Fixed #{issue_number} -- {short summary of changes in past tense}.
```

Example:

```text
Fixed #75 -- Made remote CLI output respect --json.
```

For non-issue work:

```text
Added contributing guidelines.
```

The message should end with a full stop.

## Pull Request Expectations

A pull request should be easy to review.

It should include:

- The issue it belongs to
- What changed
- Why it changed
- Tests or docs added
- Checks run locally

Avoid mixing multiple unrelated changes. If a PR becomes bigger than expected,
split it.

## Review

Review may be quick for small fixes. It may take longer for framework contract
changes. That is expected.

Quater should stay small, predictable, and safe across HTTP, MCP, and CLI. The
review process exists to protect that shape.

## AI-assisted Contributions

AI tools are allowed. The contributor still owns the final change.

Review AI-generated code carefully, remove anything you do not understand, and
run the relevant checks before opening a PR. Do not submit code, docs, tests, or
examples that you cannot explain yourself.

If AI helped with a meaningful part of the PR, mention it briefly in the PR
description so review stays transparent.
