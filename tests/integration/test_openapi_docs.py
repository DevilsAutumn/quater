from __future__ import annotations

import json

import msgspec
import pytest

from quater import (
    Body,
    Cookie,
    File,
    Form,
    Header,
    HTMLResponse,
    Path,
    Quater,
    Query,
    Request,
    UploadFile,
)
from quater.exceptions import ConfigurationError, RouteConflictError
from quater.typing import AuthContext, AuthRequest


class CreateUser(msgspec.Struct):
    name: str
    age: int


UPDATE_PAYLOAD = Body(description="Update payload.")
CSV_DOCUMENT = File(description="CSV document.")


@pytest.mark.asyncio
async def test_openapi_json_is_generated_by_default() -> None:
    app = Quater(name="Users API")

    @app.get("/users/{id:int}", description="Fetch one user.")
    async def get_user(id: int, include_pets: bool = False) -> dict[str, object]:
        return {"id": id, "include_pets": include_pets}

    @app.post("/users")
    async def create_user(user: CreateUser) -> dict[str, object]:
        return {"name": user.name, "age": user.age}

    response = await app.handle(Request(method="GET", path="/openapi.json"))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert dict(response.headers)["content-type"] == "application/json"
    assert body["openapi"] == "3.1.1"
    assert body["info"]["title"] == "Users API"
    get_operation = body["paths"]["/users/{id}"]["get"]
    assert get_operation["description"] == "Fetch one user."
    assert get_operation["parameters"] == [
        {
            "name": "id",
            "in": "path",
            "required": True,
            "schema": {"type": "integer"},
        },
        {
            "name": "include_pets",
            "in": "query",
            "required": False,
            "schema": {"type": "boolean", "default": False},
        },
    ]
    post_operation = body["paths"]["/users"]["post"]
    assert post_operation["requestBody"] == {
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer"},
                    },
                    "additionalProperties": False,
                    "required": ["name", "age"],
                }
            }
        },
        "required": True,
    }


@pytest.mark.asyncio
async def test_openapi_uses_parameter_markers_for_metadata() -> None:
    app = Quater(name="Orders API")

    @app.post("/orders/{id}", description="Update one order.")
    async def update_order(
        order_id: str = Path(alias="id", description="Order id."),
        include_events: bool = Query(
            default=False,
            alias="include-events",
            description="Include event history.",
        ),
        request_id: str | None = Header(
            default=None,
            alias="X-Request-ID",
            description="Caller request id.",
        ),
        session_id: str = Cookie(alias="session", description="Session cookie."),
        payload: CreateUser = UPDATE_PAYLOAD,
    ) -> dict[str, str]:
        return {"order_id": order_id, "payload": payload.name}

    response = await app.handle(Request(method="GET", path="/openapi.json"))
    body = json.loads(response.body)
    operation = body["paths"]["/orders/{id}"]["post"]

    assert operation["parameters"] == [
        {
            "name": "id",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
            "description": "Order id.",
        },
        {
            "name": "include-events",
            "in": "query",
            "required": False,
            "schema": {"type": "boolean", "default": False},
            "description": "Include event history.",
        },
        {
            "name": "X-Request-ID",
            "in": "header",
            "required": False,
            "schema": {"type": "string", "default": None},
            "description": "Caller request id.",
        },
        {
            "name": "session",
            "in": "cookie",
            "required": True,
            "schema": {"type": "string"},
            "description": "Session cookie.",
        },
    ]
    assert operation["requestBody"]["description"] == "Update payload."
    assert (
        operation["requestBody"]["content"]["application/json"]["schema"]["description"]
        == "Update payload."
    )


@pytest.mark.asyncio
async def test_openapi_documents_form_and_file_request_bodies() -> None:
    app = Quater(name="Imports API")

    @app.post("/oauth/token")
    async def token(
        grant_type: str = Form(description="OAuth grant type."),
        client_id: str = Form(alias="client-id"),
    ) -> dict[str, str]:
        return {"grant_type": grant_type, "client_id": client_id}

    @app.post("/imports")
    async def import_document(
        account_id: str = Form(),
        document: UploadFile = CSV_DOCUMENT,
    ) -> dict[str, str]:
        return {"account_id": account_id, "filename": document.filename}

    response = await app.handle(Request(method="GET", path="/openapi.json"))
    body = json.loads(response.body)

    token_body = body["paths"]["/oauth/token"]["post"]["requestBody"]
    assert token_body == {
        "content": {
            "application/x-www-form-urlencoded": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "grant_type": {
                            "type": "string",
                            "description": "OAuth grant type.",
                        },
                        "client-id": {"type": "string"},
                    },
                    "additionalProperties": False,
                    "required": ["grant_type", "client-id"],
                }
            }
        },
        "description": "grant_type: OAuth grant type.",
        "required": True,
    }
    import_body = body["paths"]["/imports"]["post"]["requestBody"]
    assert import_body["content"]["multipart/form-data"]["schema"] == {
        "type": "object",
        "properties": {
            "account_id": {"type": "string"},
            "document": {
                "type": "string",
                "format": "binary",
                "description": "CSV document.",
            },
        },
        "additionalProperties": False,
        "required": ["account_id", "document"],
    }


@pytest.mark.asyncio
async def test_openapi_docs_html_uses_swagger_ui_by_default() -> None:
    app = Quater()

    @app.get("/unsafe", description="<script>alert(1)</script>")
    async def unsafe() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(Request(method="GET", path="/docs"))
    body = response.body.decode("utf-8")

    assert response.status_code == 200
    assert isinstance(response, HTMLResponse)
    assert dict(response.headers)["content-type"] == "text/html; charset=utf-8"
    assert "swagger-ui-bundle.js" in body
    assert "swagger-initializer.js" in body
    assert "/openapi.json" in body
    assert "SwaggerUIBundle" not in body
    assert "<script>alert(1)</script>" not in body


@pytest.mark.asyncio
async def test_docs_and_openapi_paths_are_configurable() -> None:
    app = Quater(docs_path="/api-docs", openapi_path="/schema.json")

    schema_response = await app.handle(Request(method="GET", path="/schema.json"))
    docs_response = await app.handle(Request(method="GET", path="/api-docs"))
    initializer_response = await app.handle(
        Request(method="GET", path="/api-docs/swagger-initializer.js")
    )

    assert schema_response.status_code == 200
    assert docs_response.status_code == 200
    assert "/schema.json" in docs_response.body.decode("utf-8")
    assert b'url: "/schema.json"' in initializer_response.body


@pytest.mark.asyncio
async def test_openapi_docs_can_be_disabled_without_disabling_schema() -> None:
    app = Quater(docs_path=None)

    docs_response = await app.handle(Request(method="GET", path="/docs"))
    schema_response = await app.handle(Request(method="GET", path="/openapi.json"))

    assert docs_response.status_code == 404
    assert schema_response.status_code == 200


@pytest.mark.asyncio
async def test_openapi_can_be_disabled_entirely() -> None:
    app = Quater(docs_path=None, openapi_path=None)

    docs_response = await app.handle(Request(method="GET", path="/docs"))
    schema_response = await app.handle(Request(method="GET", path="/openapi.json"))

    assert docs_response.status_code == 404
    assert schema_response.status_code == 404


@pytest.mark.asyncio
async def test_openapi_marks_route_level_auth_without_guessing_scheme() -> None:
    async def authenticate(ctx: AuthRequest) -> AuthContext | None:
        return AuthContext(subject="user_1")

    app = Quater()

    @app.get("/private", auth=authenticate)
    async def private() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(Request(method="GET", path="/openapi.json"))
    body = json.loads(response.body)

    assert body["paths"]["/private"]["get"]["x-quater-auth"] == "required"


@pytest.mark.asyncio
async def test_openapi_metadata_response_shapes_and_hidden_routes() -> None:
    app = Quater(name="Orders API")

    @app.get(
        "/orders",
        metadata={
            "summary": "  List orders  ",
            "tags": ["orders", "", 123, "ops"],
            "operation_id": "orders.list",
            "openapi_extra": {"x-audience": "internal"},
        },
    )
    async def list_orders() -> str:
        return "ok"

    @app.get(
        "/orders/archive",
        metadata={"operation_id": "orders.list"},
    )
    async def archived_orders() -> bytes:
        return b"ok"

    @app.delete("/orders/{id}")
    async def delete_order(id: str) -> None:
        return None

    @app.get("/fragments/status")
    async def status_fragment() -> HTMLResponse:
        return HTMLResponse("<p>ok</p>")

    @app.get("/internal", metadata={"include_in_openapi": False})
    async def internal() -> dict[str, bool]:
        return {"ok": True}

    response = await app.handle(Request(method="GET", path="/openapi.json"))
    body = json.loads(response.body)

    assert "/internal" not in body["paths"]
    list_operation = body["paths"]["/orders"]["get"]
    assert list_operation["operationId"] == "orders_list"
    assert list_operation["summary"] == "List orders"
    assert list_operation["tags"] == ["orders", "ops"]
    assert list_operation["x-audience"] == "internal"
    assert list_operation["responses"]["200"]["content"] == {
        "text/plain": {"schema": {"type": "string"}}
    }

    archive_operation = body["paths"]["/orders/archive"]["get"]
    assert archive_operation["operationId"] == "orders_list_2"
    assert archive_operation["responses"]["200"]["content"] == {
        "application/octet-stream": {
            "schema": {"type": "string", "format": "binary"},
        }
    }

    delete_operation = body["paths"]["/orders/{id}"]["delete"]
    assert delete_operation["responses"] == {"204": {"description": "No Content"}}

    html_operation = body["paths"]["/fragments/status"]["get"]
    assert "content" not in html_operation["responses"]["200"]


def test_user_routes_conflicting_with_enabled_docs_paths_are_rejected() -> None:
    app = Quater()

    @app.get("/docs")
    async def docs() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(RouteConflictError):
        app.compile_routes()


def test_user_routes_conflicting_with_openapi_json_path_are_rejected() -> None:
    app = Quater()

    @app.get("/openapi.json")
    async def schema() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(RouteConflictError):
        app.compile_routes()


def test_user_routes_conflicting_with_swagger_assets_are_rejected() -> None:
    app = Quater()

    @app.get("/docs/swagger-ui.css")
    async def asset() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(RouteConflictError):
        app.compile_routes()


@pytest.mark.asyncio
async def test_swagger_ui_assets_are_served_from_bundle() -> None:
    app = Quater()

    css = await app.handle(Request(method="GET", path="/docs/swagger-ui.css"))
    js = await app.handle(Request(method="GET", path="/docs/swagger-ui-bundle.js"))
    initializer = await app.handle(
        Request(method="GET", path="/docs/swagger-initializer.js")
    )

    assert css.status_code == 200
    assert dict(css.headers)["content-type"] == "text/css; charset=utf-8"
    assert b"swagger-ui" in css.body.lower()
    assert js.status_code == 200
    assert dict(js.headers)["content-type"] == "application/javascript; charset=utf-8"
    assert b"SwaggerUIBundle" in js.body
    assert b'url: "/openapi.json"' in initializer.body


def test_enabled_swagger_ui_fails_fast_when_bundle_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quater.docs import swagger

    swagger._swagger_ui_asset_dir.cache_clear()
    swagger._swagger_ui_asset_bytes.cache_clear()

    def missing_bundle(name: str) -> object:
        if name == "swagger_ui_bundle":
            raise ModuleNotFoundError(name)
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr(swagger, "import_module", missing_bundle)

    app = Quater()

    with pytest.raises(ConfigurationError, match="swagger-ui-bundle"):
        app.compile_routes()


def test_disabled_swagger_ui_does_not_require_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quater.docs import swagger

    swagger._swagger_ui_asset_dir.cache_clear()
    swagger._swagger_ui_asset_bytes.cache_clear()

    def missing_bundle(name: str) -> object:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(swagger, "import_module", missing_bundle)

    app = Quater(docs_path=None)
    app.compile_routes()
