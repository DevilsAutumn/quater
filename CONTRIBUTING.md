# Contributing to Quater

Quater is an early-stage framework, but contributions should still follow a
clear process. This keeps reviews focused, avoids duplicate work, and makes it
easier for new contributors to land good changes.

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

If you cannot continue after claiming an issue, leave an update so someone else
can pick it up.

Small pull requests are preferred. A small PR with good tests is much easier to
review than a large PR that mixes behavior changes, docs, cleanup, and refactors.

## Local Setup

You need:

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Rust stable toolchain
- Node.js 20 and npm

Fork the repo on GitHub, then clone your fork:

```bash
git clone https://github.com/YOUR_USERNAME/quater.git
cd quater
git remote add upstream https://github.com/DevilsAutumn/quater.git
```

Install Python dependencies:

```bash
uv sync --frozen --group dev --group release
```

Install docs dependencies:

```bash
npm ci
```

Run the test suite:

```bash
uv run --no-sync pytest -q
```

## Pre-commit

Pre-commit is required for contributors.

Install it once:

```bash
uv run --no-sync pre-commit install
```

Run it before opening a PR:

```bash
uv run --no-sync pre-commit run --all-files
```

The pre-commit config runs the fast checks:

- `ruff format --check .`
- `ruff check .`
- `mypy src examples tests`

CI runs more than this. Passing pre-commit is not the same as passing the full
release gate, but it catches the most common issues before review.

## Choosing The Right Branch

Use this branch format:

```bash
git checkout -b issue_75
```

Use the issue number from GitHub. Do not put unrelated work on the same branch.
If you notice another problem while working, open a separate issue or PR.

## What Needs Discussion First

Please discuss these before writing code:

- Public API changes
- Handler binding behavior
- Auth, resources, middleware, MCP, or CLI action contracts
- Security-sensitive behavior
- New dependencies
- Large refactors
- Release or packaging changes

Quater is still moving quickly, so breaking API changes can happen in any
release. They should happen deliberately, with the contract written down before
the implementation lands.

## Code Expectations

Use the surrounding code as the style guide.

General rules:

- Keep public APIs small and explicit.
- Prefer typed code over clever dynamic code.
- Keep error messages short and useful.
- Do not expose internal modules as stable APIs without discussion.
- Do not mix unrelated cleanup into a bug fix.
- Add comments only when they explain non-obvious behavior.
- Keep examples using top-level imports from `quater`.

Quater has four important call paths:

- HTTP
- MCP
- local CLI
- remote CLI

If a change affects a shared handler contract, think through all four. Many
bugs in this project are not "one endpoint is broken" bugs. They are parity
bugs between surfaces.

## Tests

Most code changes need tests. Pick the narrowest useful test first, then add
integration coverage if the behavior crosses surfaces.

Use this guide:

- `tests/unit/`: binding, routing, small helpers, request/response behavior
- `tests/unit/cli/`: CLI parsing, remote config, CLI output, command behavior
- `tests/integration/test_mcp_tools_call.py`: MCP tool calls
- `tests/integration/test_action_protocol.py`: remote CLI action protocol
- `tests/integration/test_cross_surface_parity.py`: HTTP/MCP/CLI parity
- `tests/security/`: auth boundaries, spoofing, unsafe input, error safety
- `tests/typing/`: public typing expectations

Run focused tests while working. Before opening a non-trivial PR, run:

```bash
uv run --no-sync pytest -q
```

## Docs And Changelog

Update docs when users need to understand the change.

Common places:

- `README.md` for first impression and high-level examples
- `docs/en/dev/` for guides
- `docs/en/dev/reference/` for exact API behavior
- `docs/en/dev/changelog.md` for release notes

Add a changelog entry when the change affects users, public behavior, security,
compatibility, CLI output, docs process, or release process. Small internal
cleanup usually does not need a changelog entry.

If you update generated reference docs, use:

```bash
npm run docs:reference
```

To check docs:

```bash
npm run docs:build
```

`docs/en/dev` is the only docs source tree. Release docs are frozen by Git tag:
build that checkout with `npm run docs:build:stable` to publish it under
`/en/stable/`. Do not copy the docs into per-version folders for normal patch or
minor releases. To test the production shape without creating a tag, run
`npm run docs:build:site`; it builds both `/en/stable/` and `/en/dev/` from the
current checkout into one previewable `dist` directory.

## Checks Before Opening A PR

For a normal code PR:

```bash
uv run --no-sync pre-commit run --all-files
uv run --no-sync pytest -q
```

For security-sensitive changes:

```bash
uv run --no-sync bandit -q -c pyproject.toml -r src/quater
uv run --no-sync pip-audit
```

For Rust/router changes:

```bash
cargo test --locked
```

For packaging changes:

```bash
uv build
uv run --no-sync twine check dist/*
```

For docs changes:

```bash
npm run docs:build
```

Mention the checks you ran in the PR. If you skipped a relevant check, say why.

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

## Pull Requests

A good PR should have:

- A linked issue
- One clear purpose
- Tests for behavior changes
- Docs for user-facing changes
- Changelog entry when release-visible
- A short list of checks run locally

The PR does not need a long story. It should be clear what changed, why it
changed, and how it was checked.

## Review

Maintainers may ask for changes. That is normal.

If a PR changes a framework contract, review may take longer. Quater's value is
in having a small, predictable API across HTTP, MCP, and CLI. That kind of API
needs careful review.

Keep the discussion focused on the change. If the PR grows beyond the original
issue, split it.

## AI-assisted Contributions

AI tools are fine to use. The contributor is still responsible for the final
change.

Before opening a PR, review AI-generated code carefully, remove anything you do
not understand, and run the relevant checks. Do not submit code, docs, tests, or
examples that you cannot explain yourself.

If AI helped with a meaningful part of the PR, mention it briefly in the PR
description. This is not a problem; it just keeps review transparent.
