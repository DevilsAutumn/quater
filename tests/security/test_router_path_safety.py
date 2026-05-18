from __future__ import annotations

import asyncio
from unicodedata import category

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from quater import AuthContext, AuthRequest, Quater, Request
from quater.exceptions import ConfigurationError


def path_segment_strategy() -> SearchStrategy[str]:
    return st.text(min_size=1, max_size=24).filter(_is_safe_path_segment)


def _is_safe_path_segment(value: str) -> bool:
    return not any(
        char in {"/", "\x00", "\r", "\n"} or category(char) == "Cs" for char in value
    )


@pytest.mark.asyncio
async def test_path_confusion_inputs_do_not_bypass_static_or_method_rules() -> None:
    calls: list[str] = []
    app = Quater()

    @app.get("/admin")
    async def get_admin() -> dict[str, str]:
        calls.append("get")
        return {"route": "get-admin"}

    @app.post("/admin")
    async def post_admin() -> dict[str, str]:
        calls.append("post")
        return {"route": "post-admin"}

    exact = await app.handle(Request(method="GET", path="/admin"))
    encoded_slash = await app.handle(Request(method="GET", path="/admin%2Fdelete"))
    dot_segment = await app.handle(Request(method="GET", path="/admin/."))
    unicode_segment = await app.handle(Request(method="GET", path="/admin/東京"))
    method_mismatch = await app.handle(Request(method="DELETE", path="/admin"))

    assert exact.status_code == 200
    assert encoded_slash.status_code == 404
    assert dot_segment.status_code == 404
    assert unicode_segment.status_code == 404
    assert method_mismatch.status_code == 405
    assert dict(method_mismatch.headers)["allow"] == "GET, POST"
    assert calls == ["get"]


@pytest.mark.asyncio
async def test_normalized_slashes_do_not_bypass_auth_or_call_wrong_handler() -> None:
    calls = 0
    app = Quater()

    async def deny(_ctx: AuthRequest) -> AuthContext | None:
        return None

    @app.get("/private", auth=deny)
    async def private() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    for path in ("//private", "/private/", "///private///"):
        response = await app.handle(Request(method="GET", path=path))
        assert response.status_code == 401

    assert calls == 0


@pytest.mark.asyncio
async def test_dynamic_params_treat_encoded_and_dot_values_as_data_only() -> None:
    seen: list[str] = []
    app = Quater()

    @app.get("/files/{name}")
    async def file(name: str) -> dict[str, str]:
        seen.append(name)
        return {"name": name}

    encoded = await app.handle(Request(method="GET", path="/files/a%2Fb"))
    dotdot = await app.handle(Request(method="GET", path="/files/.."))
    traversal = await app.handle(Request(method="GET", path="/files/../../secret"))

    assert encoded.status_code == 200
    assert encoded.body == b'{"name":"a%2Fb"}'
    assert dotdot.status_code == 200
    assert dotdot.body == b'{"name":".."}'
    assert traversal.status_code == 404
    assert seen == ["a%2Fb", ".."]


def test_user_routes_cannot_claim_quater_internal_paths() -> None:
    app = Quater()

    async def handler() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(ConfigurationError, match="reserved by Quater"):
        app.add_route("GET", "/mcp", handler)
    with pytest.raises(ConfigurationError, match="reserved by Quater"):
        app.add_route("GET", "/__quater__/actions/call", handler)
    with pytest.raises(ConfigurationError, match="reserved by Quater"):
        app.add_route("GET", "/__quater__/private", handler)


@given(segments=st.lists(path_segment_strategy(), min_size=2, max_size=5))
@settings(max_examples=80, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_fuzzed_extra_path_segments_never_match_one_dynamic_segment(
    segments: list[str],
) -> None:
    async def run_case() -> None:
        calls = 0
        app = Quater()

        @app.get("/files/{name}")
        async def file(name: str) -> dict[str, str]:
            nonlocal calls
            calls += 1
            return {"name": name}

        response = await app.handle(
            Request(method="GET", path="/files/" + "/".join(segments))
        )

        assert response.status_code == 404
        assert calls == 0

    asyncio.run(run_case())


@given(segment=path_segment_strategy())
@settings(max_examples=80)
def test_fuzzed_single_path_segment_is_bound_verbatim(segment: str) -> None:
    async def run_case() -> None:
        app = Quater()

        @app.get("/echo/{value}")
        async def echo(value: str) -> dict[str, str]:
            return {"value": value}

        response = await app.handle(Request(method="GET", path=f"/echo/{segment}"))

        assert response.status_code == 200
        assert response.body.startswith(b'{"value":')

    asyncio.run(run_case())
