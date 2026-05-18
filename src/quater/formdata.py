"""Form and upload primitives."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from email.message import Message
from email.parser import BytesParser
from email.policy import default
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO, cast
from urllib.parse import parse_qsl

from quater.config import (
    DEFAULT_MAX_FILE_SIZE,
    DEFAULT_MAX_FORM_FIELD_SIZE,
    DEFAULT_MAX_FORM_PARTS,
    DEFAULT_UPLOAD_SPOOL_SIZE,
)
from quater.exceptions import (
    PayloadTooLargeError,
    RequestFormError,
    UnsupportedMediaTypeError,
)


class UploadFile:
    """Uploaded multipart file passed to handlers using ``File(...)`` markers."""

    __slots__ = ("content_type", "filename", "headers", "size", "_closed", "_file")

    def __init__(
        self,
        *,
        filename: str,
        content_type: str,
        headers: Mapping[str, str] | None = None,
        content: bytes = b"",
        spool_size: int = DEFAULT_UPLOAD_SPOOL_SIZE,
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self.headers = dict(headers or {})
        self.size = len(content)
        self._file = cast(
            BinaryIO,
            SpooledTemporaryFile(  # noqa: SIM115 - UploadFile owns this file.
                max_size=spool_size,
                mode="w+b",
            ),
        )
        self._file.write(content)
        self._file.seek(0)
        self._closed = False

    @property
    def file(self) -> BinaryIO:
        """Underlying binary file object."""

        return self._file

    @property
    def closed(self) -> bool:
        """Whether the underlying file has been closed."""

        return self._closed

    async def read(self, size: int = -1) -> bytes:
        """Read bytes from the current file position."""

        return self._file.read(size)

    async def seek(self, offset: int, whence: int = 0) -> int:
        """Move the file cursor and return the new position."""

        return self._file.seek(offset, whence)

    async def close(self) -> None:
        """Close the underlying file."""

        self._close_sync()

    def _close_sync(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._file.close()


class FormData(Mapping[str, str]):
    """Parsed form fields and uploaded files returned by ``Request.form()``."""

    __slots__ = ("_files", "_field_lookup", "_fields")

    def __init__(
        self,
        *,
        fields: tuple[tuple[str, str], ...] = (),
        files: tuple[tuple[str, UploadFile], ...] = (),
    ) -> None:
        self._fields = fields
        self._files = files
        self._field_lookup = dict(fields)

    def __getitem__(self, key: str) -> str:
        return self._field_lookup[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._field_lookup)

    def __len__(self) -> int:
        return len(self._field_lookup)

    @property
    def fields(self) -> tuple[tuple[str, str], ...]:
        return self._fields

    @property
    def files(self) -> tuple[tuple[str, UploadFile], ...]:
        return self._files

    def get_all(self, key: str) -> tuple[str, ...]:
        return tuple(value for name, value in self._fields if name == key)

    def get_file(self, key: str) -> UploadFile | None:
        files = self.get_files(key)
        return files[-1] if files else None

    def get_files(self, key: str) -> tuple[UploadFile, ...]:
        return tuple(value for name, value in self._files if name == key)


def parse_form_data(
    *,
    content_type: str | None,
    body: bytes,
    max_parts: int | None = None,
    max_field_size: int | None = None,
    max_file_size: int | None = None,
    upload_spool_size: int | None = None,
) -> FormData:
    if not body and not content_type:
        return FormData()

    media_type, options = _parse_content_type(content_type)
    if media_type == "application/x-www-form-urlencoded":
        return _parse_urlencoded_form(
            body,
            options,
            max_parts=max_parts if max_parts is not None else DEFAULT_MAX_FORM_PARTS,
            max_field_size=(
                max_field_size
                if max_field_size is not None
                else DEFAULT_MAX_FORM_FIELD_SIZE
            ),
        )
    if media_type == "multipart/form-data":
        return _parse_multipart_form(
            body,
            content_type or "",
            max_parts=max_parts if max_parts is not None else DEFAULT_MAX_FORM_PARTS,
            max_field_size=(
                max_field_size
                if max_field_size is not None
                else DEFAULT_MAX_FORM_FIELD_SIZE
            ),
            max_file_size=(
                max_file_size if max_file_size is not None else DEFAULT_MAX_FILE_SIZE
            ),
            upload_spool_size=(
                upload_spool_size
                if upload_spool_size is not None
                else DEFAULT_UPLOAD_SPOOL_SIZE
            ),
        )
    raise UnsupportedMediaTypeError("Unsupported form content type")


def _parse_urlencoded_form(
    body: bytes,
    options: Mapping[str, str],
    *,
    max_parts: int,
    max_field_size: int,
) -> FormData:
    charset = _form_charset(options)
    try:
        decoded = body.decode(charset)
    except UnicodeDecodeError as exc:
        raise RequestFormError from exc

    if _has_bad_percent_escape(decoded):
        raise RequestFormError

    try:
        fields = parse_qsl(
            decoded,
            keep_blank_values=True,
            encoding=charset,
            errors="strict",
            max_num_fields=max_parts,
        )
    except ValueError as exc:
        raise RequestFormError from exc

    for name, value in fields:
        _validate_field_name(name)
        if len(value.encode(charset)) > max_field_size:
            raise PayloadTooLargeError
    return FormData(fields=tuple(fields))


def _parse_multipart_form(
    body: bytes,
    content_type: str,
    *,
    max_parts: int,
    max_field_size: int,
    max_file_size: int,
    upload_spool_size: int,
) -> FormData:
    try:
        header = content_type.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise UnsupportedMediaTypeError("Unsupported form content type") from exc
    message = BytesParser(policy=default).parsebytes(
        b"Content-Type: " + header + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    if message.defects or not message.is_multipart():
        raise RequestFormError

    fields: list[tuple[str, str]] = []
    files: list[tuple[str, UploadFile]] = []
    uploads: list[UploadFile] = []
    try:
        for index, part in enumerate(message.iter_parts(), start=1):
            if index > max_parts:
                raise PayloadTooLargeError
            if part.defects or part.is_multipart():
                raise RequestFormError
            _parse_multipart_part(
                part,
                fields=fields,
                files=files,
                uploads=uploads,
                max_field_size=max_field_size,
                max_file_size=max_file_size,
                upload_spool_size=upload_spool_size,
            )
    except Exception:
        for upload in uploads:
            upload._close_sync()
        raise

    return FormData(fields=tuple(fields), files=tuple(files))


def _parse_multipart_part(
    part: Any,
    *,
    fields: list[tuple[str, str]],
    files: list[tuple[str, UploadFile]],
    uploads: list[UploadFile],
    max_field_size: int,
    max_file_size: int,
    upload_spool_size: int,
) -> None:
    if part.get_content_disposition() != "form-data":
        raise RequestFormError

    name = part.get_param("name", header="content-disposition")
    if not isinstance(name, str):
        raise RequestFormError
    _validate_field_name(name)

    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        raise RequestFormError

    raw_filename = part.get_filename()
    if raw_filename is None:
        charset = _part_charset(part)
        if len(payload) > max_field_size:
            raise PayloadTooLargeError
        try:
            fields.append((name, payload.decode(charset)))
        except UnicodeDecodeError as exc:
            raise RequestFormError from exc
        return

    filename = _clean_filename(raw_filename)
    if filename is None:
        if payload:
            raise RequestFormError
        return

    if len(payload) > max_file_size:
        raise PayloadTooLargeError

    upload = UploadFile(
        filename=filename,
        content_type=_clean_content_type(part.get_content_type()),
        headers={str(key).lower(): str(value) for key, value in part.items()},
        content=payload,
        spool_size=upload_spool_size,
    )
    uploads.append(upload)
    files.append((name, upload))


def _parse_content_type(value: str | None) -> tuple[str, dict[str, str]]:
    if value is None:
        raise UnsupportedMediaTypeError("Unsupported form content type")
    message = Message()
    try:
        message["content-type"] = value
    except ValueError as exc:
        raise UnsupportedMediaTypeError("Unsupported form content type") from exc
    params = message.get_params(header="content-type") or []
    return (
        message.get_content_type().lower(),
        {str(key).lower(): str(option) for key, option in params[1:]},
    )


def _form_charset(options: Mapping[str, str]) -> str:
    charset = options.get("charset", "utf-8").lower()
    if charset not in {"utf-8", "us-ascii"}:
        raise UnsupportedMediaTypeError("Unsupported form charset")
    return charset


def _part_charset(part: Message) -> str:
    charset = (part.get_content_charset() or "utf-8").lower()
    if charset not in {"utf-8", "us-ascii"}:
        raise UnsupportedMediaTypeError("Unsupported form charset")
    return charset


def _validate_field_name(value: str) -> None:
    if not value or any(_is_control_character(char) for char in value):
        raise RequestFormError


def _clean_filename(value: str) -> str | None:
    if any(_is_control_character(char) for char in value):
        raise RequestFormError
    filename = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return filename or None


def _clean_content_type(value: str) -> str:
    if any(_is_control_character(char) for char in value):
        raise RequestFormError
    return value or "application/octet-stream"


def _is_control_character(value: str) -> bool:
    ordinal = ord(value)
    return ordinal < 32 or ordinal == 127


def _has_bad_percent_escape(value: str) -> bool:
    index = 0
    while True:
        index = value.find("%", index)
        if index == -1:
            return False
        if index + 2 >= len(value):
            return True
        if not all(
            char in "0123456789abcdefABCDEF" for char in value[index + 1 : index + 3]
        ):
            return True
        index += 3


__all__ = ["FormData", "UploadFile", "parse_form_data"]
