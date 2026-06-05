from __future__ import annotations

import inspect

import pytest

from quater import Quater, Request


@pytest.mark.asyncio
async def test_static_routes_win_before_dynamic_routes() -> None:
    app = Quater()

    @app.get("/users/{id:int}")
    async def get_user(id: int) -> dict[str, int]:
        return {"id": id}

    @app.get("/users/me")
    async def get_me() -> dict[str, str]:
        return {"name": "me"}

    response = await app.handle(Request(method="GET", path="/users/me"))

    assert response.status_code == 200
    assert response.body == b'{"name":"me"}'


@pytest.mark.asyncio
async def test_static_routes_win_inside_nested_dynamic_tree() -> None:
    app = Quater()

    @app.get("/projects/{project}/members")
    async def project_members(project: str) -> dict[str, str]:
        return {"route": "project", "project": project}

    @app.get("/projects/archive/members")
    async def archived_members() -> dict[str, str]:
        return {"route": "archive"}

    response = await app.handle(Request(method="GET", path="/projects/archive/members"))

    assert response.status_code == 200
    assert response.body == b'{"route":"archive"}'


@pytest.mark.asyncio
async def test_root_route_matches_normalized_root_paths() -> None:
    app = Quater()

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"route": "root"}

    for path in ("", "/", "///"):
        response = await app.handle(Request(method="GET", path=path))
        assert response.status_code == 200
        assert response.body == b'{"route":"root"}'


@pytest.mark.asyncio
async def test_nested_path_params_are_bound_by_name_and_type() -> None:
    app = Quater()

    @app.get("/orgs/{org}/users/{user_id:int}/posts/{slug}")
    async def post(org: str, user_id: int, slug: str) -> dict[str, object]:
        return {"org": org, "user_id": user_id, "slug": slug}

    response = await app.handle(
        Request(method="GET", path="/orgs/acme/users/42/posts/hello-world")
    )

    assert response.status_code == 200
    assert response.body == b'{"org":"acme","user_id":42,"slug":"hello-world"}'


@pytest.mark.asyncio
async def test_same_dynamic_shape_under_different_static_prefixes_can_coexist() -> None:
    app = Quater()

    @app.get("/users/{id:int}")
    async def user(id: int) -> dict[str, int]:
        return {"user_id": id}

    @app.get("/teams/{slug}")
    async def team(slug: str) -> dict[str, str]:
        return {"team": slug}

    user_response = await app.handle(Request(method="GET", path="/users/7"))
    team_response = await app.handle(Request(method="GET", path="/teams/core"))

    assert user_response.status_code == 200
    assert user_response.body == b'{"user_id":7}'
    assert team_response.status_code == 200
    assert team_response.body == b'{"team":"core"}'


@pytest.mark.asyncio
async def test_dynamic_segment_does_not_cross_path_separator() -> None:
    app = Quater()
    calls = 0

    @app.get("/files/{name}")
    async def file(name: str) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"name": name}

    matched = await app.handle(Request(method="GET", path="/files/report.pdf"))
    extra_segment = await app.handle(Request(method="GET", path="/files/reports/2026"))

    assert matched.status_code == 200
    assert matched.body == b'{"name":"report.pdf"}'
    assert extra_segment.status_code == 404
    assert calls == 1


@pytest.mark.asyncio
async def test_static_matching_is_case_sensitive() -> None:
    app = Quater()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(Request(method="GET", path="/Health"))

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_literal_braces_inside_static_segments_are_matched() -> None:
    app = Quater()

    @app.get("/files/name{draft}v2")
    async def static_braces() -> dict[str, str]:
        return {"route": "static-braces"}

    response = await app.handle(Request(method="GET", path="/files/name{draft}v2"))

    assert response.status_code == 200
    assert response.body == b'{"route":"static-braces"}'


@pytest.mark.asyncio
async def test_typed_path_param_rejection_does_not_call_handler() -> None:
    app = Quater()
    calls = 0

    @app.get("/users/{id:int}")
    async def get_user(id: int) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"id": id}

    response = await app.handle(Request(method="GET", path="/users/not-an-int"))

    assert response.status_code == 404
    assert calls == 0


@pytest.mark.asyncio
async def test_int_converter_accepts_canonical_ascii_digits() -> None:
    app = Quater()

    @app.get("/numbers/{value:int}")
    async def number(value: int) -> dict[str, int]:
        return {"value": value}

    for path, body in (
        ("/numbers/0", b'{"value":0}'),
        ("/numbers/7", b'{"value":7}'),
        ("/numbers/12345", b'{"value":12345}'),
        # Leading zeros are still canonical ASCII digits and map to the int.
        ("/numbers/007", b'{"value":7}'),
    ):
        response = await app.handle(Request(method="GET", path=path))
        assert response.status_code == 200
        assert response.body == body


@pytest.mark.asyncio
async def test_int_converter_rejects_signed_values() -> None:
    app = Quater()
    calls = 0

    @app.get("/numbers/{value:int}")
    async def number(value: int) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": value}

    for path in ("/numbers/+7", "/numbers/-7", "/numbers/-0", "/numbers/+0"):
        response = await app.handle(Request(method="GET", path=path))
        assert response.status_code == 404, path

    assert calls == 0


@pytest.mark.asyncio
async def test_int_converter_rejects_underscore_grouping() -> None:
    app = Quater()

    @app.get("/numbers/{value:int}")
    async def number(value: int) -> dict[str, int]:
        return {"value": value}

    for path in ("/numbers/1_000", "/numbers/1_0_0", "/numbers/_1", "/numbers/1_"):
        response = await app.handle(Request(method="GET", path=path))
        assert response.status_code == 404, path


@pytest.mark.asyncio
async def test_int_converter_rejects_non_ascii_digits() -> None:
    app = Quater()

    @app.get("/numbers/{value:int}")
    async def number(value: int) -> dict[str, int]:
        return {"value": value}

    # Arabic-Indic, Devanagari, and fullwidth digits are all rejected even
    # though Python's int() would happily parse them.
    for path in ("/numbers/٣", "/numbers/१२३", "/numbers/５"):
        response = await app.handle(Request(method="GET", path=path))
        assert response.status_code == 404, path


@pytest.mark.asyncio
async def test_int_converter_rejects_surrounding_whitespace() -> None:
    app = Quater()

    @app.get("/numbers/{value:int}")
    async def number(value: int) -> dict[str, int]:
        return {"value": value}

    # Python's int() strips surrounding ASCII whitespace; the converter must not.
    for path in ("/numbers/ 7", "/numbers/7 ", "/numbers/\t7", "/numbers/7\n"):
        response = await app.handle(Request(method="GET", path=path))
        assert response.status_code == 404, repr(path)


@pytest.mark.asyncio
async def test_method_not_allowed_requires_valid_path_converters() -> None:
    app = Quater()

    @app.get("/items/{id:int}")
    async def get_item(id: int) -> dict[str, int]:
        return {"id": id}

    valid_path = await app.handle(Request(method="DELETE", path="/items/1"))
    invalid_path = await app.handle(Request(method="DELETE", path="/items/not-int"))

    assert valid_path.status_code == 405
    assert dict(valid_path.headers)["allow"] == "GET"
    assert invalid_path.status_code == 404
    assert "allow" not in dict(invalid_path.headers)


@pytest.mark.asyncio
async def test_non_canonical_int_is_not_reported_as_method_not_allowed() -> None:
    app = Quater()

    @app.get("/items/{id:int}")
    async def get_item(id: int) -> dict[str, int]:
        return {"id": id}

    # A non-canonical id must not even resolve the route shape, so an otherwise
    # unsupported method reports 404 rather than 405.
    response = await app.handle(Request(method="DELETE", path="/items/+1"))

    assert response.status_code == 404
    assert "allow" not in dict(response.headers)


@pytest.mark.asyncio
async def test_method_not_allowed_lists_supported_methods() -> None:
    app = Quater()

    @app.get("/items/{id:int}")
    async def get_item(id: int) -> dict[str, int]:
        return {"id": id}

    @app.post("/items/{id:int}")
    async def update_item(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(Request(method="DELETE", path="/items/1"))

    assert response.status_code == 405
    headers = dict(response.headers)
    assert headers["allow"] == "GET, POST"
    assert headers["content-type"] == "text/plain; charset=utf-8"
    assert headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_method_not_allowed_for_static_route() -> None:
    app = Quater()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(Request(method="POST", path="/health"))

    assert response.status_code == 405
    assert dict(response.headers)["allow"] == "GET"


@pytest.mark.asyncio
async def test_request_path_slashes_keep_existing_router_semantics() -> None:
    app = Quater()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    for path in ("/health/", "//health", "/health//", "health"):
        response = await app.handle(Request(method="GET", path=path))
        assert response.status_code == 200
        assert response.body == b'{"ok":true}'


@pytest.mark.asyncio
async def test_normalized_dynamic_path_still_uses_converter() -> None:
    app = Quater()

    @app.get("/items/{id:int}")
    async def item(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(Request(method="GET", path="//items//001//"))

    assert response.status_code == 200
    assert response.body == b'{"id":1}'


@pytest.mark.asyncio
async def test_large_integer_path_param_uses_python_int_semantics() -> None:
    app = Quater()

    @app.get("/numbers/{id:int}")
    async def get_number(id: int) -> dict[str, int]:
        return {"id": id}

    response = await app.handle(
        Request(method="GET", path="/numbers/999999999999999999999999")
    )

    assert response.status_code == 200
    assert response.body == b'{"id":999999999999999999999999}'


@pytest.mark.asyncio
async def test_no_runtime_signature_inspection_after_compile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Quater()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    app.compile_routes()

    def fail_signature(_: object) -> inspect.Signature:
        raise AssertionError("signature inspection happened during dispatch")

    monkeypatch.setattr(inspect, "signature", fail_signature)

    response = await app.handle(Request(method="GET", path="/health"))

    assert response.status_code == 200
    assert response.body == b'{"ok":true}'
