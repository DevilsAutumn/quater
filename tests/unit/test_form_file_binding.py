from __future__ import annotations

import pytest

from quater import (
    AuthContext,
    AuthRequest,
    Body,
    File,
    Form,
    Quater,
    Request,
    TestClient,
    UploadFile,
)
from quater.exceptions import ConfigurationError, RouteBindingError


async def allow_auth(_ctx: AuthRequest) -> AuthContext | None:
    return AuthContext(subject="tester")


DOCUMENT_FILE = File()
RAW_FILE = File()
ATTACHMENTS_FILE = File()
IMAGE_FILE = File()
MIXED_BODY = Body()
EXPOSED_FILE = File()


@pytest.mark.asyncio
async def test_urlencoded_form_binds_scalars_and_defaults() -> None:
    app = Quater()

    @app.post("/token")
    async def token(
        grant_type: str = Form(),
        client_id: str = Form(alias="client-id"),
        active: bool = Form(default=True),
        attempts: int = Form(default=1),
    ) -> dict[str, object]:
        return {
            "grant_type": grant_type,
            "client_id": client_id,
            "active": active,
            "attempts": attempts,
        }

    response = await TestClient(app).post(
        "/token",
        data={
            "grant_type": "client_credentials",
            "client-id": "client_123",
            "active": "false",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "grant_type": "client_credentials",
        "client_id": "client_123",
        "active": False,
        "attempts": 1,
    }


@pytest.mark.asyncio
async def test_multipart_form_binds_upload_file_and_sanitizes_filename() -> None:
    app = Quater()

    @app.post("/imports")
    async def import_file(
        account_id: str = Form(),
        document: UploadFile = DOCUMENT_FILE,
    ) -> dict[str, object]:
        content = await document.read()
        return {
            "account_id": account_id,
            "filename": document.filename,
            "content_type": document.content_type,
            "size": document.size,
            "content": content.decode("utf-8"),
        }

    response = await TestClient(app).post(
        "/imports",
        data={"account_id": "acct_123"},
        files={"document": ("../report.csv", b"id,total\n1,42\n", "text/csv")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "account_id": "acct_123",
        "filename": "report.csv",
        "content_type": "text/csv",
        "size": 14,
        "content": "id,total\n1,42\n",
    }


@pytest.mark.asyncio
async def test_file_can_bind_to_bytes_and_upload_lists() -> None:
    app = Quater()

    @app.post("/files")
    async def files(
        raw: bytes = RAW_FILE,
        attachments: list[UploadFile] = ATTACHMENTS_FILE,
    ) -> dict[str, object]:
        names = [file.filename for file in attachments]
        sizes = [len(await file.read()) for file in attachments]
        return {"raw": raw.decode("utf-8"), "names": names, "sizes": sizes}

    response = await TestClient(app).post(
        "/files",
        files=[
            ("raw", ("raw.txt", b"hello", "text/plain")),
            ("attachments", ("a.txt", b"a", "text/plain")),
            ("attachments", ("b.txt", b"bb", "text/plain")),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {
        "raw": "hello",
        "names": ["a.txt", "b.txt"],
        "sizes": [1, 2],
    }


@pytest.mark.asyncio
async def test_missing_and_duplicate_files_fail_safely() -> None:
    app = Quater()
    calls = 0

    @app.post("/avatar")
    async def avatar(image: UploadFile = IMAGE_FILE) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"filename": image.filename}

    missing = await TestClient(app).post("/avatar", data={"note": "none"})
    duplicate = await TestClient(app).post(
        "/avatar",
        files=[
            ("image", ("a.txt", b"a", "text/plain")),
            ("image", ("b.txt", b"b", "text/plain")),
        ],
    )

    assert missing.status_code == 400
    assert missing.body == b"Missing required file: image"
    assert duplicate.status_code == 400
    assert duplicate.body == b"Multiple files received for parameter: image"
    assert calls == 0


@pytest.mark.asyncio
async def test_form_routes_reject_wrong_or_malformed_content_type_safely() -> None:
    app = Quater()
    calls = 0

    @app.post("/submit")
    async def submit(name: str = Form()) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"name": name}

    wrong_type = await TestClient(app).post(
        "/submit",
        headers={"content-type": "application/json"},
        content=b'{"name":"Ada"}',
    )
    malformed = await TestClient(app).post(
        "/submit",
        headers={"content-type": "application/x-www-form-urlencoded"},
        content=b"name=%ZZ",
    )

    assert wrong_type.status_code == 415
    assert wrong_type.body == b"Unsupported form content type"
    assert malformed.status_code == 400
    assert malformed.body == b"Malformed form body"
    assert calls == 0


def test_body_cannot_be_combined_with_form_or_file() -> None:
    app = Quater()

    @app.post("/mixed")
    async def mixed(
        payload: dict[str, object] = MIXED_BODY, name: str = Form()
    ) -> None:
        return None

    with pytest.raises(
        RouteBindingError,
        match="JSON body parameters cannot be combined with form or file parameters",
    ):
        app.compile_routes()


def test_file_routes_are_not_exposed_as_mcp_or_cli_actions() -> None:
    app = Quater(mcp_auth=allow_auth, cli_auth=allow_auth)

    @app.post("/upload", tool=True, cli=True, description="Upload one file.")
    async def upload(document: UploadFile = EXPOSED_FILE) -> dict[str, str]:
        return {"filename": document.filename}

    with pytest.raises(ConfigurationError, match="File parameters cannot be exposed"):
        app.compile_routes()


@pytest.mark.asyncio
async def test_form_routes_work_through_mcp_and_remote_cli_actions() -> None:
    app = Quater(mcp_auth=allow_auth, cli_auth=allow_auth)

    @app.post(
        "/oauth/token",
        tool=True,
        cli=True,
        description="Issue a demo token.",
    )
    async def issue_token(
        grant_type: str = Form(),
        client_id: str = Form(),
        request: Request | None = None,
    ) -> dict[str, object]:
        return {
            "grant_type": grant_type,
            "client_id": client_id,
            "source": request.context.source if request is not None else "unknown",
        }

    client = TestClient(app)
    mcp = await client.mcp.tools_call(
        "issue_token",
        {
            "grant_type": "client_credentials",
            "client_id": "client_123",
        },
        token="demo",
    )
    cli = await client.post(
        "/__quater__/actions/call",
        headers={"authorization": "Bearer demo"},
        json={
            "action": "issue_token",
            "arguments": {
                "grant_type": "client_credentials",
                "client_id": "client_123",
            },
        },
    )

    assert mcp.status_code == 200
    mcp_body = mcp.json()
    assert mcp_body["result"]["content"][0]["text"] == (
        '{"grant_type":"client_credentials","client_id":"client_123","source":"mcp"}'
    )
    assert cli.status_code == 200
    assert cli.json()["body"] == {
        "grant_type": "client_credentials",
        "client_id": "client_123",
        "source": "cli",
    }
