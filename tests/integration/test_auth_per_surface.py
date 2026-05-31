"""Per-surface ``AuthConfig``: one authenticator per request, sharing the scope.

These cover the contract introduced with per-surface authentication: exactly
one authenticator runs per request (picked by source), it shares the request's
resource scope with the handler, it carries the loaded object in
``AuthContext.payload``, ``public`` opts a route out uniformly per surface, and
the security invariants (framework-set source, reject-before-session,
fail-closed, no leaks) hold.

This module intentionally does not use ``from __future__ import annotations``:
some handler parameters use ``Annotated[T, resource]`` aliases built from
per-test ``Resource`` objects, which only resolve when the annotation is a live
object rather than a deferred string.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any, cast

import pytest

from quater import (
    AuthConfig,
    AuthContext,
    HTTPError,
    Quater,
    Request,
    Resource,
    TestClient,
)
from quater.exceptions import ConfigurationError


class Ledger:
    def __init__(self) -> None:
        self.opens = 0
        self.queries = 0
        self.closes = 0


class Session:
    """A stand-in request resource that counts opens, closes, and queries."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.closed = False
        ledger.opens += 1

    def query_user(self) -> dict[str, str]:
        self.ledger.queries += 1
        return {"id": "u1"}


def _session_resource(ledger: Ledger) -> Resource:
    async def provider(request: Request) -> AsyncIterator[Session]:
        session = Session(ledger)
        try:
            yield session
        finally:
            session.closed = True
            ledger.closes += 1

    return Resource(provider, name="session")


# --------------------------------------------------------------------------- #
# one authenticator per request, by source                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_one_authenticator_runs_once_per_request_on_every_surface() -> None:
    calls: list[str] = []

    async def authenticate(request: Request) -> AuthContext:
        calls.append(request.context.source)
        return AuthContext(subject="u1")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api", "mcp", "cli"])])

    @app.get("/thing", tool=True, cli=True, description="Read a thing.")
    async def thing(request: Request) -> dict[str, str]:
        return {"source": request.context.source}

    async with TestClient(app) as client:
        await client.get("/thing")
        assert calls == ["api"]
        await client.mcp.tools_call("thing", {})
        assert calls == ["api", "mcp"]
        await client.cli.call("thing", {})
        assert calls == ["api", "mcp", "cli"]


# --------------------------------------------------------------------------- #
# the authenticator shares the handler's session (the #52/#53 payoff)         #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["api", "mcp", "cli"])
async def test_authenticator_and_handler_share_one_session(surface: str) -> None:
    ledger = Ledger()
    session_resource = _session_resource(ledger)
    SessionDep = Annotated[Session, session_resource]

    seen: dict[str, int] = {}

    async def authenticate(request: Request) -> AuthContext:
        session = await request.resolve(SessionDep)
        seen["auth_session"] = id(session)
        return AuthContext(subject="u1")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api", "mcp", "cli"])])

    @app.get("/orders", tool=True, cli=True, description="List orders.")
    async def orders(session: SessionDep) -> dict[str, bool]:
        return {"same": id(session) == seen["auth_session"]}

    async with TestClient(app) as client:
        if surface == "api":
            body = (await client.get("/orders")).json()
        elif surface == "mcp":
            res = (await client.mcp.tools_call("orders", {})).json()["result"]
            body = json.loads(res["content"][0]["text"])
        else:
            body = (await client.cli.call("orders", {})).json()["body"]

    assert body["same"] is True
    assert ledger.opens == 1  # one session for auth + handler, not two
    assert ledger.closes == 1  # and it is torn down exactly once


# --------------------------------------------------------------------------- #
# payload carries the loaded object; CurrentUser reads it back, no requery     #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_payload_is_read_back_without_a_second_query() -> None:
    ledger = Ledger()
    session_resource = _session_resource(ledger)
    SessionDep = Annotated[Session, session_resource]

    async def authenticate(request: Request) -> AuthContext:
        session = await request.resolve(SessionDep)
        user = session.query_user()
        return AuthContext(subject=user["id"], payload=user)

    async def current_user(request: Request) -> dict[str, str]:
        assert request.auth is not None
        return cast(dict[str, str], request.auth.payload)

    CurrentUser = Annotated[dict[str, str], Resource(current_user)]

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/me")
    async def me(user: CurrentUser) -> dict[str, str]:
        return {"id": user["id"]}

    async with TestClient(app) as client:
        body = (await client.get("/me")).json()

    assert body == {"id": "u1"}
    assert ledger.queries == 1  # loaded once in auth, reused by the handler


# --------------------------------------------------------------------------- #
# public opts out, uniformly, per surface                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_public_true_opens_every_exposed_surface() -> None:
    async def deny(request: Request) -> AuthContext | None:
        return None

    app = Quater(auth=[AuthConfig(deny, surfaces=["api", "mcp", "cli"])])

    @app.get("/open", tool=True, cli=True, public=True, description="Open thing.")
    async def open_thing() -> dict[str, bool]:
        return {"ok": True}

    async with TestClient(app) as client:
        assert (await client.get("/open")).status_code == 200
        mcp = (await client.mcp.tools_call("open_thing", {})).json()
        assert mcp["result"]["isError"] is False
        assert (await client.cli.call("open_thing", {})).status_code == 200


@pytest.mark.asyncio
async def test_public_list_opts_out_named_surfaces_only() -> None:
    async def auth(request: Request) -> AuthContext | None:
        if request.headers.get("authorization") == "Bearer t":
            return AuthContext(subject="u1")
        return None

    app = Quater(auth=[AuthConfig(auth, surfaces=["api", "mcp", "cli"])])

    @app.get(
        "/mixed",
        tool=True,
        cli=True,
        public=["mcp"],
        description="Mixed exposure.",
    )
    async def mixed() -> dict[str, bool]:
        return {"ok": True}

    async with TestClient(app) as client:
        # mcp is public
        mcp = (await client.mcp.tools_call("mixed", {})).json()
        assert mcp["result"]["isError"] is False
        # api + cli still protected
        assert (await client.get("/mixed")).status_code == 401
        assert (await client.cli.call("mixed", {})).status_code == 401


# --------------------------------------------------------------------------- #
# security: source is framework-set, sessions stay closed, fail-closed         #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_source_is_framework_set_and_not_spoofable_by_a_header() -> None:
    seen: list[str] = []

    async def api_auth(request: Request) -> AuthContext | None:
        seen.append("api")
        if request.headers.get("authorization") == "Bearer api":
            return AuthContext(subject="api-user")
        return None

    async def cli_auth(request: Request) -> AuthContext:
        seen.append("cli")
        return AuthContext(subject="cli-user")

    app = Quater(
        auth=[
            AuthConfig(api_auth, surfaces=["api"]),
            AuthConfig(cli_auth, surfaces=["cli"]),
        ]
    )

    @app.get("/thing", cli=True, description="Read a thing.")
    async def thing(request: Request) -> dict[str, str]:
        return {"source": request.context.source}

    async with TestClient(app) as client:
        # A header claiming a different source cannot downgrade to the cli
        # authenticator; the HTTP entry path stays the 'api' surface.
        response = await client.get(
            "/thing",
            headers={"x-quater-source": "cli", "source": "cli"},
        )

    assert response.status_code == 401
    assert seen == ["api"]


@pytest.mark.asyncio
async def test_denied_request_never_opens_handler_resources() -> None:
    ledger = Ledger()
    session_resource = _session_resource(ledger)
    SessionDep = Annotated[Session, session_resource]

    async def authenticate(request: Request) -> AuthContext:
        # A cheap header check, with no session parameter of its own, so an
        # obviously-bad request is rejected before any pool resource is opened.
        if request.headers.get("authorization") != "Bearer t":
            raise HTTPError("Unauthorized", status_code=401)
        return AuthContext(subject="u1")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/me")
    async def me(session: SessionDep) -> dict[str, bool]:
        session.query_user()
        return {"ok": True}

    async with TestClient(app) as client:
        denied = await client.get("/me")

    assert denied.status_code == 401
    assert ledger.opens == 0  # the handler, and its session, never ran


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["api", "mcp", "cli"])
async def test_bad_token_never_opens_auth_resource_on_any_surface(
    surface: str,
) -> None:
    ledger = Ledger()
    session_resource = _session_resource(ledger)
    SessionDep = Annotated[Session, session_resource]

    async def authenticate(request: Request) -> AuthContext:
        if request.headers.get("authorization") != "Bearer valid":
            raise HTTPError("Unauthorized", status_code=401)
        session = await request.resolve(SessionDep)
        user = session.query_user()
        return AuthContext(subject=user["id"], payload=user)

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api", "mcp", "cli"])])

    @app.get("/me", tool=True, cli=True, description="Read the authenticated user.")
    async def me(session: SessionDep) -> dict[str, str]:
        assert session.ledger is ledger
        return {"id": "u1"}

    async with TestClient(app) as client:
        if surface == "api":
            denied = await client.get("/me", headers={"authorization": "Bearer bad"})
        elif surface == "mcp":
            denied = await client.mcp.tools_call("me", {}, token="bad")
        else:
            denied = await client.cli.call("me", {}, token="bad")

    assert denied.status_code == 401
    assert ledger.opens == 0
    assert ledger.queries == 0
    assert ledger.closes == 0


# --------------------------------------------------------------------------- #
# startup validation + teardown on discovery                                  #
# --------------------------------------------------------------------------- #


def test_a_surface_covered_twice_is_a_startup_error() -> None:
    async def a(request: Request) -> AuthContext | None:
        return None

    async def b(request: Request) -> AuthContext | None:
        return None

    with pytest.raises(ConfigurationError, match="covered by more than one AuthConfig"):
        Quater(
            auth=[
                AuthConfig(a, surfaces=["api"]),
                AuthConfig(b, surfaces=["api", "mcp"]),
            ]
        )


@pytest.mark.parametrize(
    ("surface", "tool", "cli"),
    [("api", False, False), ("mcp", True, False), ("cli", False, True)],
)
def test_an_uncovered_surface_warns_but_is_allowed(
    surface: str,
    tool: bool,
    cli: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Every surface behaves the same: no AuthConfig means its routes are open, which
    # is allowed but logged loudly — there is no mandatory-auth error, not even
    # for tools and actions.
    app = Quater()

    @app.get("/thing", tool=tool, cli=cli, description="A thing.")
    async def thing() -> dict[str, bool]:
        return {"ok": True}

    with caplog.at_level(logging.WARNING, logger="quater"):
        app.compile_routes()

    assert any(f"{surface!r} surface" in record.message for record in caplog.records)


def test_authenticator_resource_parameters_are_a_startup_error() -> None:
    ledger = Ledger()
    session_resource = _session_resource(ledger)
    SessionDep = Annotated[Session, session_resource]

    async def authenticate(request: Request, session: SessionDep) -> AuthContext:
        return AuthContext(subject=session.query_user()["id"])

    bad_authenticator = cast(Any, authenticate)
    app = Quater(auth=[AuthConfig(bad_authenticator, surfaces=["api"])])

    @app.get("/me")
    async def me() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(
        ConfigurationError,
        match="cannot declare resource parameters",
    ):
        app.compile_routes()
    assert ledger.opens == 0


@pytest.mark.parametrize(
    "source",
    [
        # an unresolved RETURN hint forces the per-parameter hint fallback
        (
            "from __future__ import annotations\n"
            "from quater import AuthContext, Request\n"
            "async def authenticate(ctx: Request) -> MissingReturn:\n"
            "    return AuthContext(subject='u1')\n"
        ),
        # a class-based (callable-instance) authenticator, resolved via __call__
        (
            "from __future__ import annotations\n"
            "from quater import AuthContext, Request\n"
            "class Policy:\n"
            "    async def __call__(self, request: Request) -> MissingReturn:\n"
            "        return AuthContext(subject='u1')\n"
            "authenticate = Policy()\n"
        ),
        # an unannotated request parameter is recognised by name in the fallback
        (
            "from __future__ import annotations\n"
            "from quater import AuthContext\n"
            "async def authenticate(request) -> MissingReturn:\n"
            "    return AuthContext(subject='u1')\n"
        ),
        # an unresolvable annotation on the request parameter is tolerated
        (
            "from __future__ import annotations\n"
            "from quater import AuthContext\n"
            "async def authenticate(request: MissingType) -> AuthContext:\n"
            "    return AuthContext(subject='u1')\n"
        ),
        # the request may be supplied under an alias via Annotated metadata
        (
            "from typing import Annotated\n"
            "from quater import AuthContext, Request\n"
            "async def authenticate(ctx: Annotated[Request, 'meta']) -> AuthContext:\n"
            "    return AuthContext(subject='u1')\n"
        ),
    ],
    ids=["unresolved-return", "callable-instance", "unannotated", "bad-param", "alias"],
)
def test_authenticator_request_parameter_recognised_across_forms(source: str) -> None:
    namespace: dict[str, object] = {}
    exec(source, namespace)
    authenticate = cast(Any, namespace["authenticate"])
    app = Quater(auth=[AuthConfig(authenticate, surfaces=["api"])])

    @app.get("/me")
    async def me() -> dict[str, bool]:
        return {"ok": True}

    app.compile_routes()


def test_authconfig_rejects_non_callable_authenticator() -> None:
    with pytest.raises(TypeError, match="must be callable"):
        AuthConfig(cast(Any, object()), surfaces=["api"])


@pytest.mark.parametrize(
    ("surfaces", "match"),
    [
        ("api", "must be a list of surface names"),
        (["bogus"], "Unknown auth surface"),
        (["api", "api"], "more than once"),
        ([], "must cover at least one surface"),
    ],
    ids=["string", "unknown", "duplicate", "empty"],
)
def test_authconfig_rejects_invalid_surfaces(surfaces: Any, match: str) -> None:
    async def authenticate(request: Request) -> AuthContext:
        return AuthContext(subject="u1")

    with pytest.raises(ConfigurationError, match=match):
        AuthConfig(authenticate, surfaces=surfaces)


def test_auth_must_be_a_list_of_authconfig_objects() -> None:
    async def authenticate(request: Request) -> AuthContext:
        return AuthContext(subject="u1")

    with pytest.raises(ConfigurationError, match="auth must be a list of AuthConfig"):
        Quater(auth=cast(Any, [authenticate]))


def test_authenticator_signature_must_be_one_request_parameter() -> None:
    async def varargs(*args: object) -> AuthContext:
        return AuthContext(subject="u1")

    async def no_params() -> AuthContext:
        return AuthContext(subject="u1")

    async def extra(request: Request, other: int) -> AuthContext:
        return AuthContext(subject="u1")

    cases: list[tuple[Any, str]] = [
        (varargs, "cannot use"),
        (no_params, "must accept exactly one request parameter"),
        (extra, "may only accept the request parameter"),
        # a builtin whose signature cannot be introspected fails clearly
        (dict.update, "could not be inspected"),
    ]
    for authenticator, match in cases:
        with pytest.raises(ConfigurationError, match=match):
            Quater(auth=[AuthConfig(authenticator, surfaces=["api"])]).compile_routes()


def test_authconfig_display_name_and_repr() -> None:
    async def authenticate(request: Request) -> AuthContext:
        return AuthContext(subject="u1")

    unnamed = AuthConfig(authenticate, surfaces=["api", "mcp"])
    named = AuthConfig(authenticate, surfaces=["cli"], name="bearer")

    assert unnamed.display_name == "authenticate"
    assert named.display_name == "bearer"
    assert repr(unnamed) == "AuthConfig('authenticate', surfaces=['api', 'mcp'])"
    assert repr(named) == "AuthConfig('bearer', surfaces=['cli'])"


@pytest.mark.parametrize(
    ("public", "tool", "match"),
    [
        ("api", False, "must be a bool or a list"),
        (["bogus"], False, "Unknown public surface"),
        (["mcp"], False, "is not exposed on that surface"),
    ],
    ids=["string", "unknown", "not-exposed"],
)
def test_public_value_is_validated_at_route_definition(
    public: Any, tool: bool, match: str
) -> None:
    app = Quater()

    async def handler() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(ConfigurationError, match=match):
        app.get("/r", tool=tool, public=public, description="r")(handler)


def test_public_list_deduplicates_repeated_surfaces() -> None:
    app = Quater()

    @app.get("/t", tool=True, public=["mcp", "mcp"], description="t")
    async def t() -> dict[str, bool]:
        return {"ok": True}

    assert app._routes[-1].public == ("mcp",)


@pytest.mark.asyncio
async def test_resources_opened_for_discovery_auth_are_torn_down() -> None:
    ledger = Ledger()
    session_resource = _session_resource(ledger)
    SessionDep = Annotated[Session, session_resource]

    async def authenticate(request: Request) -> AuthContext:
        session = await request.resolve(SessionDep)
        session.query_user()
        return AuthContext(subject="u1")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["mcp"])])

    @app.get("/thing", tool=True, description="Read a thing.")
    async def thing() -> dict[str, bool]:
        return {"ok": True}

    async with TestClient(app) as client:
        listed = await client.mcp.tools_list(token="anything")

    assert listed.status_code == 200
    # tools/list never runs a handler, but auth opened a session — it must still
    # be torn down exactly once.
    assert ledger.opens == 1
    assert ledger.closes == 1
