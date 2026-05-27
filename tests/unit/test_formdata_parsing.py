"""Direct unit tests for the form parser and its data structures.

The HTTP-level form binding is exercised through ``TestClient`` elsewhere; this
module covers ``parse_form_data`` and the ``FormData`` / ``UploadFile`` contracts
directly so the parser's edge cases are pinned without a full request round-trip.
"""

from __future__ import annotations

import pytest

from quater.exceptions import (
    PayloadTooLargeError,
    RequestFormError,
    UnsupportedMediaTypeError,
)
from quater.formdata import FormData, UploadFile, parse_form_data

URLENCODED = "application/x-www-form-urlencoded"


def multipart(
    parts: list[tuple[list[str], bytes]],
    *,
    boundary: str = "boundary123",
) -> tuple[str, bytes]:
    """Build a ``(content_type, body)`` pair for a multipart payload."""

    lines: list[bytes] = []
    for headers, payload in parts:
        lines.append(f"--{boundary}".encode())
        lines.extend(header.encode() for header in headers)
        lines.append(b"")
        lines.append(payload)
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    return f"multipart/form-data; boundary={boundary}", b"\r\n".join(lines)


class TestUploadFile:
    @pytest.mark.asyncio
    async def test_read_seek_and_size_track_content(self) -> None:
        upload = UploadFile(
            filename="report.csv",
            content_type="text/csv",
            content=b"id,total\n1,42\n",
        )

        assert upload.size == 14
        assert await upload.read() == b"id,total\n1,42\n"
        assert await upload.seek(0) == 0
        assert await upload.read(2) == b"id"
        assert upload.file.read() == b",total\n1,42\n"

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self) -> None:
        upload = UploadFile(filename="a.txt", content_type="text/plain", content=b"a")

        assert upload.closed is False
        await upload.close()
        assert upload.closed is True
        # A second close must not raise even though the file is already gone.
        await upload.close()
        assert upload.closed is True


class TestFormDataMapping:
    def test_mapping_interface_exposes_fields(self) -> None:
        form = FormData(fields=(("name", "Ada"), ("role", "admin")))

        assert form["name"] == "Ada"
        assert len(form) == 2
        assert set(form) == {"name", "role"}
        assert "role" in form
        assert dict(form) == {"name": "Ada", "role": "admin"}

    def test_get_all_returns_every_value_for_repeated_field(self) -> None:
        form = FormData(fields=(("tag", "a"), ("tag", "b"), ("other", "c")))

        assert form.get_all("tag") == ("a", "b")
        assert form.get_all("missing") == ()
        # The mapping view collapses duplicates to the last value (dict semantics).
        assert form["tag"] == "b"

    def test_file_accessors_return_last_and_all_uploads(self) -> None:
        first = UploadFile(filename="a.txt", content_type="text/plain", content=b"a")
        second = UploadFile(filename="b.txt", content_type="text/plain", content=b"b")
        form = FormData(files=(("doc", first), ("doc", second)))

        assert form.files == (("doc", first), ("doc", second))
        assert form.get_files("doc") == (first, second)
        assert form.get_file("doc") is second
        assert form.get_files("missing") == ()
        assert form.get_file("missing") is None


class TestParseUrlencoded:
    def test_empty_body_without_content_type_returns_empty_form(self) -> None:
        form = parse_form_data(content_type=None, body=b"")

        assert isinstance(form, FormData)
        assert len(form) == 0
        assert form.files == ()

    def test_parses_fields_and_keeps_blank_values(self) -> None:
        form = parse_form_data(content_type=URLENCODED, body=b"a=1&b=&a=2")

        assert form.fields == (("a", "1"), ("b", ""), ("a", "2"))
        assert form.get_all("a") == ("1", "2")

    def test_accepts_us_ascii_charset(self) -> None:
        form = parse_form_data(
            content_type=f"{URLENCODED}; charset=us-ascii",
            body=b"name=Ada",
        )

        assert form["name"] == "Ada"

    def test_rejects_unsupported_charset(self) -> None:
        with pytest.raises(UnsupportedMediaTypeError):
            parse_form_data(
                content_type=f"{URLENCODED}; charset=utf-16",
                body=b"name=Ada",
            )

    def test_rejects_invalid_utf8_bytes(self) -> None:
        with pytest.raises(RequestFormError):
            parse_form_data(content_type=URLENCODED, body=b"name=\xff")

    @pytest.mark.parametrize("body", [b"a=%ZZ", b"a=ab%2", b"a=%"])
    def test_rejects_bad_percent_escape(self, body: bytes) -> None:
        with pytest.raises(RequestFormError):
            parse_form_data(content_type=URLENCODED, body=body)

    def test_rejects_too_many_fields(self) -> None:
        with pytest.raises(RequestFormError):
            parse_form_data(content_type=URLENCODED, body=b"a=1&b=2", max_parts=1)

    def test_rejects_oversized_field_value(self) -> None:
        with pytest.raises(PayloadTooLargeError):
            parse_form_data(
                content_type=URLENCODED,
                body=b"bio=abcdef",
                max_field_size=3,
            )

    def test_rejects_control_character_in_field_name(self) -> None:
        with pytest.raises(RequestFormError):
            parse_form_data(content_type=URLENCODED, body=b"%01=value")

    def test_rejects_empty_field_name(self) -> None:
        with pytest.raises(RequestFormError):
            parse_form_data(content_type=URLENCODED, body=b"=value")


class TestParseMultipart:
    def test_parses_field_and_file_together(self) -> None:
        content_type, body = multipart(
            [
                (['Content-Disposition: form-data; name="account_id"'], b"acct_1"),
                (
                    [
                        'Content-Disposition: form-data; name="doc"; '
                        'filename="report.csv"',
                        "Content-Type: text/csv",
                    ],
                    b"id,total\n1,42\n",
                ),
            ]
        )

        form = parse_form_data(content_type=content_type, body=body)

        assert form["account_id"] == "acct_1"
        upload = form.get_file("doc")
        assert upload is not None
        assert upload.filename == "report.csv"
        assert upload.content_type == "text/csv"
        assert upload.size == 14

    def test_sanitizes_path_traversal_in_filename(self) -> None:
        content_type, body = multipart(
            [
                (
                    [
                        'Content-Disposition: form-data; name="doc"; '
                        'filename="../../etc/passwd"',
                        "Content-Type: text/plain",
                    ],
                    b"x",
                ),
            ]
        )

        form = parse_form_data(content_type=content_type, body=body)
        upload = form.get_file("doc")
        assert upload is not None
        assert upload.filename == "passwd"

    def test_rejects_too_many_parts(self) -> None:
        content_type, body = multipart(
            [
                (['Content-Disposition: form-data; name="a"'], b"1"),
                (['Content-Disposition: form-data; name="b"'], b"2"),
            ]
        )

        with pytest.raises(PayloadTooLargeError):
            parse_form_data(content_type=content_type, body=body, max_parts=1)

    def test_rejects_non_form_data_disposition(self) -> None:
        content_type, body = multipart(
            [(['Content-Disposition: attachment; name="a"'], b"1")]
        )

        with pytest.raises(RequestFormError):
            parse_form_data(content_type=content_type, body=body)

    def test_rejects_part_without_name(self) -> None:
        content_type, body = multipart([(["Content-Disposition: form-data"], b"1")])

        with pytest.raises(RequestFormError):
            parse_form_data(content_type=content_type, body=body)

    def test_rejects_oversized_field_value(self) -> None:
        content_type, body = multipart(
            [(['Content-Disposition: form-data; name="bio"'], b"abcdef")]
        )

        with pytest.raises(PayloadTooLargeError):
            parse_form_data(content_type=content_type, body=body, max_field_size=3)

    def test_rejects_non_utf8_field_value(self) -> None:
        content_type, body = multipart(
            [(['Content-Disposition: form-data; name="bio"'], b"\xff\xfe")]
        )

        with pytest.raises(RequestFormError):
            parse_form_data(content_type=content_type, body=body)

    def test_rejects_oversized_file(self) -> None:
        content_type, body = multipart(
            [
                (
                    [
                        'Content-Disposition: form-data; name="doc"; '
                        'filename="big.bin"',
                        "Content-Type: application/octet-stream",
                    ],
                    b"abcdef",
                ),
            ]
        )

        with pytest.raises(PayloadTooLargeError):
            parse_form_data(content_type=content_type, body=body, max_file_size=3)

    def test_rejects_unsupported_part_charset(self) -> None:
        content_type, body = multipart(
            [
                (
                    [
                        'Content-Disposition: form-data; name="bio"',
                        "Content-Type: text/plain; charset=utf-16",
                    ],
                    b"hi",
                ),
            ]
        )

        with pytest.raises(UnsupportedMediaTypeError):
            parse_form_data(content_type=content_type, body=body)

    def test_filename_resolving_to_empty_with_payload_is_rejected(self) -> None:
        content_type, body = multipart(
            [
                (
                    [
                        'Content-Disposition: form-data; name="doc"; filename="/"',
                        "Content-Type: text/plain",
                    ],
                    b"data",
                ),
            ]
        )

        with pytest.raises(RequestFormError):
            parse_form_data(content_type=content_type, body=body)

    def test_empty_file_field_is_ignored(self) -> None:
        # A file input left empty by the browser arrives with no filename and
        # no payload; it must be dropped rather than recorded as an upload.
        content_type, body = multipart(
            [
                (
                    [
                        'Content-Disposition: form-data; name="doc"; filename=""',
                        "Content-Type: application/octet-stream",
                    ],
                    b"",
                ),
            ]
        )

        form = parse_form_data(content_type=content_type, body=body)

        assert form.get_file("doc") is None
        assert form.files == ()
        assert len(form) == 0

    def test_rejects_non_latin1_content_type(self) -> None:
        with pytest.raises(UnsupportedMediaTypeError):
            parse_form_data(
                content_type="multipart/form-data; boundary=☃",
                body=b"--x--\r\n",
            )


class TestMediaTypeGuards:
    def test_body_without_content_type_is_unsupported(self) -> None:
        with pytest.raises(UnsupportedMediaTypeError):
            parse_form_data(content_type=None, body=b"a=1")

    def test_unknown_media_type_is_unsupported(self) -> None:
        with pytest.raises(UnsupportedMediaTypeError):
            parse_form_data(content_type="application/json", body=b"{}")
