from __future__ import annotations

import pytest

from quater import File, Form, Quater, Request, TestClient, UploadFile

UPLOAD_FILE = File()


@pytest.mark.asyncio
async def test_form_field_size_limit_denies_large_values_before_handler() -> None:
    app = Quater(max_body_size="2mb")
    calls = 0

    @app.post("/profile")
    async def profile(bio: str = Form()) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"bio": bio}

    response = await TestClient(app).post("/profile", data={"bio": "x" * 1_100_000})

    assert response.status_code == 413
    assert response.body == b"Payload Too Large"
    assert calls == 0


@pytest.mark.asyncio
async def test_request_body_limit_applies_before_multipart_parsing() -> None:
    app = Quater(max_body_size=64)
    calls = 0

    @app.post("/upload")
    async def upload(file: UploadFile = UPLOAD_FILE) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"filename": file.filename}

    response = await TestClient(app).post(
        "/upload",
        files={"file": ("report.txt", b"x" * 256, "text/plain")},
    )

    assert response.status_code == 413
    assert response.body == b"Payload Too Large"
    assert calls == 0


@pytest.mark.asyncio
async def test_file_size_limit_denies_large_upload_before_handler() -> None:
    app = Quater(max_body_size="2mb", max_file_size=4)
    calls = 0

    @app.post("/upload")
    async def upload(file: UploadFile = UPLOAD_FILE) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"filename": file.filename}

    response = await TestClient(app).post(
        "/upload",
        files={"file": ("report.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 413
    assert response.body == b"Payload Too Large"
    assert calls == 0


@pytest.mark.asyncio
async def test_multipart_header_injection_is_rejected() -> None:
    app = Quater()
    calls = 0

    @app.post("/upload")
    async def upload(file: UploadFile = UPLOAD_FILE) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"filename": file.filename}

    boundary = "safe-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="bad\r\nname.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "hello\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    response = await app.handle(
        Request(
            method="POST",
            path="/upload",
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
            body=body,
        )
    )

    assert response.status_code == 400
    assert response.body == b"Malformed form body"
    assert b"Traceback" not in response.body
    assert calls == 0


@pytest.mark.asyncio
async def test_multipart_without_boundary_fails_before_handler() -> None:
    app = Quater()
    calls = 0

    @app.post("/upload")
    async def upload(file: UploadFile = UPLOAD_FILE) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"filename": file.filename}

    response = await app.handle(
        Request(
            method="POST",
            path="/upload",
            headers={"content-type": "multipart/form-data"},
            body=b"not a valid multipart body",
        )
    )

    assert response.status_code == 400
    assert response.body == b"Malformed form body"
    assert calls == 0


@pytest.mark.asyncio
async def test_unsupported_form_charset_fails_before_handler() -> None:
    app = Quater()
    calls = 0

    @app.post("/profile")
    async def profile(name: str = Form()) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"name": name}

    response = await app.handle(
        Request(
            method="POST",
            path="/profile",
            headers={
                "content-type": "application/x-www-form-urlencoded; charset=utf-16"
            },
            body=b"name=Ada",
        )
    )

    assert response.status_code == 415
    assert response.body == b"Unsupported form charset"
    assert calls == 0


@pytest.mark.asyncio
async def test_uploaded_files_are_closed_after_response_collection() -> None:
    app = Quater()
    seen: list[UploadFile] = []

    @app.post("/upload")
    async def upload(file: UploadFile = UPLOAD_FILE) -> dict[str, str]:
        seen.append(file)
        return {"filename": file.filename}

    response = await TestClient(app).post(
        "/upload",
        files={"file": ("report.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 200
    assert seen
    assert seen[0].closed is True
