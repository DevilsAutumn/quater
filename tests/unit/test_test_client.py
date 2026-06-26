from __future__ import annotations

from collections.abc import AsyncIterator
from http.cookies import SimpleCookie

import pytest

from quater import (
    AuthConfig,
    JSONResponse,
    Quater,
    Request,
    Response,
    StreamResponse,
    TestClient,
)
from quater.testing import (
    _cookie_domain_for_request,
    _cookie_is_expired,
    _normalize_cookie_host,
)
from quater.typing import AuthContext


@pytest.mark.asyncio
async def test_test_client_sends_query_headers_and_default_host() -> None:
    app = Quater(allowed_hosts=["testserver"])

    @app.get("/items")
    async def items(page: int, request: Request) -> dict[str, object]:
        return {
            "page": page,
            "tags": request.query.get_all("tag"),
            "host": request.headers["host"],
            "agent": request.headers["x-test-agent"],
        }

    client = TestClient(app)
    response = await client.get(
        "/items",
        params={"page": 2, "tag": ["red", "blue"]},
        headers={"x-test-agent": "unit"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "page": 2,
        "tags": ["red", "blue"],
        "host": "testserver",
        "agent": "unit",
    }
    assert response.headers["content-type"] == "application/json"
    assert response.is_success is True


@pytest.mark.asyncio
async def test_test_client_accepts_query_pairs_for_repeated_keys() -> None:
    app = Quater()

    @app.get("/items")
    async def items(request: Request) -> dict[str, object]:
        return {
            "page": request.query["page"],
            "tags": request.query.get_all("tag"),
        }

    response = await TestClient(app).get(
        "/items",
        params=[("page", "2"), ("tag", "red"), ("tag", "blue")],
    )

    assert response.status_code == 200
    assert response.json() == {"page": "2", "tags": ["red", "blue"]}


@pytest.mark.asyncio
async def test_test_client_posts_json_body() -> None:
    app = Quater()

    @app.post("/echo")
    async def echo(payload: dict[str, object], request: Request) -> dict[str, object]:
        return {
            "payload": payload,
            "content_type": request.headers["content-type"],
        }

    response = await TestClient(app).post("/echo", json={"name": "Ada"})

    assert response.status_code == 200
    assert response.json() == {
        "payload": {"name": "Ada"},
        "content_type": "application/json",
    }


@pytest.mark.asyncio
async def test_test_client_puts_json_body() -> None:
    app = Quater()

    @app.put("/items/{item_id:int}")
    async def replace(item_id: int, payload: dict[str, object]) -> dict[str, object]:
        return {"item_id": item_id, "payload": payload}

    response = await TestClient(app).put("/items/7", json={"name": "Ada"})

    assert response.status_code == 200
    assert response.json() == {"item_id": 7, "payload": {"name": "Ada"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["request", "post", "put", "patch", "delete"])
async def test_test_client_sends_explicit_json_null(method: str) -> None:
    app = Quater()

    @app.post("/echo")
    @app.put("/echo")
    @app.patch("/echo")
    @app.delete("/echo")
    async def echo(request: Request) -> dict[str, object]:
        return {
            "payload": await request.json(),
            "content_type": request.headers["content-type"],
        }

    client = TestClient(app)
    if method == "request":
        response = await client.request("POST", "/echo", json=None)
    else:
        response = await getattr(client, method)("/echo", json=None)

    assert response.status_code == 200
    assert response.json() == {
        "payload": None,
        "content_type": "application/json",
    }


@pytest.mark.asyncio
async def test_test_client_posts_form_and_file_bodies() -> None:
    app = Quater()

    @app.post("/inspect")
    async def inspect(request: Request) -> dict[str, object]:
        form = await request.form()
        file = form.get_file("avatar")
        assert file is not None
        return {
            "name": form["name"],
            "filename": file.filename,
            "content": (await file.read()).decode("utf-8"),
            "content_type": request.headers["content-type"].split(";", 1)[0],
        }

    response = await TestClient(app).post(
        "/inspect",
        data={"name": "Ada"},
        files={"avatar": ("avatar.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "Ada",
        "filename": "avatar.txt",
        "content": "hello",
        "content_type": "multipart/form-data",
    }


@pytest.mark.asyncio
async def test_test_client_rejects_ambiguous_body_arguments() -> None:
    client = TestClient(Quater())

    with pytest.raises(ValueError, match="Use either json or content"):
        await client.post("/echo", json={"name": "Ada"}, content=b"{}")
    with pytest.raises(ValueError, match="Use one request body style"):
        await client.post("/echo", json={"name": "Ada"}, data={"name": "Ada"})


@pytest.mark.asyncio
async def test_test_client_rejects_invalid_request_targets() -> None:
    client = TestClient(Quater())

    with pytest.raises(ValueError, match="must start with '/'"):
        await client.get("health")
    with pytest.raises(ValueError, match="must not include URL fragments"):
        await client.get("/health#local")


@pytest.mark.asyncio
async def test_test_client_context_manager_runs_lifespan() -> None:
    app = Quater()
    events: list[str] = []

    @app.on_startup
    async def startup() -> None:
        events.append("startup")

    @app.on_shutdown
    async def shutdown() -> None:
        events.append("shutdown")

    async with TestClient(app):
        assert events == ["startup"]

    assert events == ["startup", "shutdown"]


@pytest.mark.asyncio
async def test_test_client_cookie_jar_persists_response_cookies() -> None:
    app = Quater()

    @app.get("/login")
    async def login() -> Response:
        return JSONResponse(
            {"ok": True},
            headers={"set-cookie": "session=abc123; HttpOnly"},
        )

    @app.get("/me")
    async def me(request: Request) -> dict[str, str | None]:
        return {"session": request.cookies.get("session")}

    client = TestClient(app)
    login_response = await client.get("/login")
    me_response = await client.get("/me")

    assert login_response.status_code == 200
    assert me_response.json() == {"session": "abc123"}


@pytest.mark.asyncio
async def test_test_client_cookie_jar_respects_set_cookie_path() -> None:
    app = Quater()

    @app.get("/admin/login")
    async def login() -> Response:
        return JSONResponse(
            {"ok": True},
            headers=[
                ("set-cookie", "session=admin; Path=/admin"),
                ("set-cookie", "implicit=admin"),
            ],
        )

    @app.get("/admin/me")
    async def admin_me(request: Request) -> dict[str, str | None]:
        return {
            "implicit": request.cookies.get("implicit"),
            "session": request.cookies.get("session"),
        }

    @app.get("/admin")
    async def admin_index(request: Request) -> dict[str, str | None]:
        return {
            "implicit": request.cookies.get("implicit"),
            "session": request.cookies.get("session"),
        }

    @app.get("/public/check")
    async def public_check(request: Request) -> dict[str, str | None]:
        return {
            "implicit": request.cookies.get("implicit"),
            "session": request.cookies.get("session"),
        }

    @app.get("/administrator")
    async def administrator(request: Request) -> dict[str, str | None]:
        return {
            "implicit": request.cookies.get("implicit"),
            "session": request.cookies.get("session"),
        }

    client = TestClient(app)
    await client.get("/admin/login")
    admin_response = await client.get("/admin/me")
    admin_index_response = await client.get("/admin")
    public_response = await client.get("/public/check")
    prefix_response = await client.get("/administrator")

    assert admin_response.json() == {"implicit": "admin", "session": "admin"}
    assert admin_index_response.json() == {"implicit": "admin", "session": "admin"}
    assert public_response.json() == {"implicit": None, "session": None}
    assert prefix_response.json() == {"implicit": None, "session": None}


@pytest.mark.asyncio
async def test_test_client_cookie_jar_root_path_matches_every_route() -> None:
    app = Quater()

    @app.get("/login")
    async def login() -> Response:
        return JSONResponse(
            {"ok": True},
            headers={"set-cookie": "session=root; Path=/"},
        )

    @app.get("/public/check")
    async def public_check(request: Request) -> dict[str, str | None]:
        return {"session": request.cookies.get("session")}

    client = TestClient(app)
    await client.get("/login")
    response = await client.get("/public/check")

    assert response.json() == {"session": "root"}


@pytest.mark.asyncio
async def test_test_client_cookie_jar_sends_matching_paths_longest_first() -> None:
    app = Quater()

    @app.get("/login")
    async def login() -> Response:
        return JSONResponse(
            {"ok": True},
            headers=[
                ("set-cookie", "session=admin; Path=/admin"),
                ("set-cookie", "session=root; Path=/"),
            ],
        )

    @app.get("/admin/me")
    async def admin_me(request: Request) -> dict[str, str | None]:
        return {"cookie": request.headers.get("cookie")}

    @app.get("/public/check")
    async def public_check(request: Request) -> dict[str, str | None]:
        return {"cookie": request.headers.get("cookie")}

    client = TestClient(app)
    await client.get("/login")
    admin_response = await client.get("/admin/me")
    public_response = await client.get("/public/check")

    assert admin_response.json() == {"cookie": "session=admin; session=root"}
    assert public_response.json() == {"cookie": "session=root"}


@pytest.mark.asyncio
async def test_test_client_cookie_jar_deletes_matching_path_only() -> None:
    app = Quater()

    @app.get("/login")
    async def login() -> Response:
        return JSONResponse(
            {"ok": True},
            headers=[
                ("set-cookie", "session=root; Path=/"),
                ("set-cookie", "session=admin; Path=/admin"),
                ("set-cookie", "negative=live; Path=/"),
                ("set-cookie", "expired=live; Path=/"),
                ("set-cookie", "invalid-age=live; Path=/"),
                ("set-cookie", "invalid-expires=live; Path=/"),
            ],
        )

    @app.get("/admin/logout")
    async def logout() -> Response:
        return JSONResponse(
            {"ok": True},
            headers=[
                ("set-cookie", "session=; Max-Age=0; Path=/admin"),
                ("set-cookie", "negative=; Max-Age=-1; Path=/"),
                (
                    "set-cookie",
                    "expired=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/",
                ),
                (
                    "set-cookie",
                    "invalid-age=; Max-Age=nope; "
                    "Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/",
                ),
                (
                    "set-cookie",
                    "invalid-expires=kept; Expires=not-a-date; Path=/",
                ),
            ],
        )

    @app.get("/admin/me")
    async def admin_me(request: Request) -> dict[str, str | None]:
        return {
            "expired": request.cookies.get("expired"),
            "invalid_age": request.cookies.get("invalid-age"),
            "invalid_expires": request.cookies.get("invalid-expires"),
            "negative": request.cookies.get("negative"),
            "session": request.cookies.get("session"),
        }

    @app.get("/public/check")
    async def public_check(request: Request) -> dict[str, str | None]:
        return {
            "expired": request.cookies.get("expired"),
            "invalid_age": request.cookies.get("invalid-age"),
            "invalid_expires": request.cookies.get("invalid-expires"),
            "negative": request.cookies.get("negative"),
            "session": request.cookies.get("session"),
        }

    client = TestClient(app)
    await client.get("/login")
    await client.get("/admin/logout")
    admin_response = await client.get("/admin/me")
    public_response = await client.get("/public/check")

    assert admin_response.json() == {
        "expired": None,
        "invalid_age": None,
        "invalid_expires": "kept",
        "negative": None,
        "session": "root",
    }
    assert public_response.json() == {
        "expired": None,
        "invalid_age": None,
        "invalid_expires": "kept",
        "negative": None,
        "session": "root",
    }


@pytest.mark.asyncio
async def test_test_client_cookie_jar_respects_secure_cookies() -> None:
    app = Quater()

    @app.get("/login")
    async def login() -> Response:
        return JSONResponse(
            {"ok": True},
            headers={"set-cookie": "secure_token=s; Secure; Path=/"},
        )

    @app.get("/me")
    async def me(request: Request) -> dict[str, str | None]:
        return {"secure_token": request.cookies.get("secure_token")}

    http_client = TestClient(app, scheme="http")
    await http_client.get("/login")
    http_response = await http_client.get("/me")

    https_client = TestClient(app, scheme="https")
    await https_client.get("/login")
    https_response = await https_client.get("/me")

    assert http_response.json() == {"secure_token": None}
    assert https_response.json() == {"secure_token": "s"}


@pytest.mark.asyncio
async def test_test_client_cookie_jar_respects_domain_cookies() -> None:
    app = Quater(allowed_hosts=["testserver", "api.example.com"])

    @app.get("/login")
    async def login() -> Response:
        return JSONResponse(
            {"ok": True},
            headers={"set-cookie": "domain_token=d; Domain=example.com; Path=/"},
        )

    @app.get("/logout")
    async def logout() -> Response:
        return JSONResponse(
            {"ok": True},
            headers={
                "set-cookie": "domain_token=; Max-Age=0; Domain=example.com; Path=/"
            },
        )

    @app.get("/me")
    async def me(request: Request) -> dict[str, str | None]:
        return {"domain_token": request.cookies.get("domain_token")}

    mismatched_client = TestClient(app, host="testserver")
    await mismatched_client.get("/login")
    mismatched_response = await mismatched_client.get("/me")

    matched_client = TestClient(app, host="api.example.com")
    await matched_client.get("/login")
    matched_response = await matched_client.get("/me")
    await matched_client.get("/logout")
    deleted_response = await matched_client.get("/me")

    assert mismatched_response.json() == {"domain_token": None}
    assert matched_response.json() == {"domain_token": "d"}
    assert deleted_response.json() == {"domain_token": None}


@pytest.mark.asyncio
async def test_test_client_cookie_jar_uses_effective_host_header() -> None:
    app = Quater(allowed_hosts=["api.example.com", "other.example.com"])

    @app.get("/login")
    async def login() -> Response:
        return JSONResponse(
            {"ok": True},
            headers={"set-cookie": "session=host-only; Path=/"},
        )

    @app.get("/me")
    async def me(request: Request) -> dict[str, str | None]:
        return {"session": request.cookies.get("session")}

    client = TestClient(app, host="api.example.com")
    await client.get("/login")
    same_host_response = await client.get("/me")
    other_host_response = await client.get(
        "/me",
        headers={"host": "other.example.com"},
    )

    assert same_host_response.json() == {"session": "host-only"}
    assert other_host_response.json() == {"session": None}


@pytest.mark.parametrize(
    ("cookie_domain", "request_host", "expected"),
    [
        ("", "Example.COM:443", ("example.com", True)),
        (".", "example.com", None),
        ("example.com", "api.example.com", ("example.com", False)),
        (".example.com", "example.com", ("example.com", False)),
        ("example.com", "badexample.com", None),
        ("example.com", "testserver", None),
    ],
)
def test_cookie_domain_for_request_normalizes_and_matches_hosts(
    cookie_domain: str,
    request_host: str,
    expected: tuple[str, bool] | None,
) -> None:
    normalized_host = _normalize_cookie_host(request_host)

    assert _cookie_domain_for_request(cookie_domain, normalized_host) == expected


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("[::1]:8443", "::1"),
        ("[::1", "[::1"),
    ],
)
def test_cookie_host_normalization_handles_bracketed_hosts(
    host: str,
    expected: str,
) -> None:
    assert _normalize_cookie_host(host) == expected


@pytest.mark.parametrize(
    ("expires", "is_expired"),
    [
        ("Thu, 01 Jan 1970 00:00:00", True),
        ("Tue, 01 Jan 2999 00:00:00", False),
    ],
)
def test_cookie_expiry_handles_timezone_less_expires(
    expires: str,
    is_expired: bool,
) -> None:
    cookie = SimpleCookie("session=value")
    cookie["session"]["expires"] = expires

    assert _cookie_is_expired(cookie["session"]) is is_expired


@pytest.mark.asyncio
async def test_test_client_per_request_cookie_overrides_cookie_jar() -> None:
    app = Quater()

    @app.get("/me")
    async def me(request: Request) -> dict[str, str | None]:
        return {"session": request.cookies.get("session")}

    client = TestClient(app)
    client.set_cookie("session", "jar")
    response = await client.get("/me", cookies={"session": "request"})
    header_response = await client.get(
        "/me",
        headers={"cookie": "session=header"},
        cookies={"session": "request"},
    )
    client.clear_cookies()
    cleared_response = await client.get("/me")

    assert response.json() == {"session": "request"}
    assert header_response.json() == {"session": "header"}
    assert cleared_response.json() == {"session": None}


@pytest.mark.asyncio
async def test_test_client_per_request_cookie_overrides_path_scoped_jar() -> None:
    app = Quater()

    @app.get("/admin/login")
    async def login() -> Response:
        return JSONResponse(
            {"ok": True},
            headers={"set-cookie": "session=admin; Path=/admin"},
        )

    @app.get("/public/check")
    async def public_check(request: Request) -> dict[str, str | None]:
        return {"session": request.cookies.get("session")}

    client = TestClient(app)
    await client.get("/admin/login")
    response = await client.get("/public/check", cookies={"session": "request"})

    assert response.json() == {"session": "request"}


@pytest.mark.asyncio
async def test_test_client_sends_reserved_name_and_spaced_cookies() -> None:
    app = Quater()

    @app.get("/cookies")
    async def cookies(request: Request) -> dict[str, str | None]:
        return {name: request.cookies.get(name) for name in ("path", "session")}

    # "path" is a Set-Cookie attribute word; the test client must still be able
    # to send it, and a value with a space must round-trip unchanged.
    client = TestClient(app, cookies={"path": "/admin", "session": "a b"})
    response = await client.get("/cookies")

    assert response.json() == {"path": "/admin", "session": "a b"}


@pytest.mark.asyncio
async def test_test_client_collects_streaming_responses() -> None:
    app = Quater()

    async def chunks() -> AsyncIterator[bytes]:
        yield b"hello"
        yield b" "
        yield b"world"

    @app.get("/stream")
    async def stream() -> StreamResponse:
        return StreamResponse(chunks(), content_type="text/plain")

    response = await TestClient(app).get("/stream")

    assert response.status_code == 200
    assert response.body == b"hello world"
    assert response.text == "hello world"


@pytest.mark.asyncio
async def test_test_client_mcp_helpers_cover_initialize_list_and_call() -> None:
    async def authenticate(ctx: Request) -> AuthContext | None:
        if ctx.headers.get("authorization") != "Bearer mcp-token":
            return None
        return AuthContext(subject="mcp")

    app = Quater(
        auth=[AuthConfig(authenticate, surfaces=["mcp"])],
        mcp_allowed_origins=["https://client.example"],
    )

    @app.get("/users/{id:int}", tool=True, description="Fetch one user.")
    async def get_user(id: int, request: Request) -> dict[str, object]:
        assert request.auth is not None
        return {"id": id, "subject": request.auth.subject}

    client = TestClient(app)
    initialize = await client.mcp.initialize(
        token="mcp-token",
        origin="https://client.example",
    )
    tools = await client.mcp.tools_list(
        token="mcp-token",
        origin="https://client.example",
    )
    call = await client.mcp.tools_call(
        "get_user",
        {"id": 7},
        token="mcp-token",
        origin="https://client.example",
    )

    assert initialize.status_code == 200
    assert initialize.json()["result"]["serverInfo"]["name"] == "quater"
    assert tools.json()["result"]["tools"][0]["name"] == "get_user"
    assert call.json()["result"] == {
        "content": [{"type": "text", "text": '{"id":7,"subject":"mcp"}'}],
        "isError": False,
    }


@pytest.mark.asyncio
async def test_test_client_cli_helpers_cover_call_dry_run_and_manifest() -> None:
    handler_calls = 0

    async def authenticate(ctx: Request) -> AuthContext | None:
        if ctx.headers.get("authorization") != "Bearer cli-token":
            return None
        return AuthContext(subject="cli")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["cli"])])

    @app.get("/users/{id:int}", cli=True, description="Fetch one user.")
    async def get_user(id: int, request: Request) -> dict[str, object]:
        nonlocal handler_calls
        handler_calls += 1
        assert request.auth is not None
        return {"id": id, "subject": request.auth.subject}

    client = TestClient(app)

    # AuthConfig runs before the handler: an unauthenticated call is rejected.
    unauthorized = await client.cli.call("get_user", {"id": 7})
    assert unauthorized.status_code == 401
    assert handler_calls == 0

    # An authenticated call runs the handler and returns the action envelope.
    call = await client.cli.call("get_user", {"id": 7}, token="cli-token")
    assert call.status_code == 200
    envelope = call.json()
    assert envelope["ok"] is True
    assert envelope["status_code"] == 200
    assert envelope["body"] == {"id": 7, "subject": "cli"}
    assert handler_calls == 1

    # A dry run validates without running the handler.
    dry_run = await client.cli.call(
        "get_user", {"id": 7}, token="cli-token", dry_run=True
    )
    preflight = dry_run.json()
    assert preflight["ok"] is True
    assert preflight["dry_run"] is True
    assert preflight["action"] == "get_user"
    assert handler_calls == 1

    # The manifest lists the CLI action.
    manifest = await client.cli.manifest(token="cli-token")
    assert manifest.status_code == 200
    assert [action["name"] for action in manifest.json()["actions"]] == ["get_user"]


@pytest.mark.asyncio
async def test_test_client_mcp_helper_preserves_origin_rejection() -> None:
    async def authenticate(ctx: Request) -> AuthContext | None:
        return AuthContext(subject="mcp")

    app = Quater(auth=[AuthConfig(authenticate, surfaces=["mcp"])])

    @app.get("/ping", tool=True, description="Ping.")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    response = await TestClient(app).mcp.tools_call(
        "ping",
        token="mcp-token",
        origin="https://evil.example",
    )

    assert response.status_code == 403
    assert response.text == "Invalid MCP Origin"
