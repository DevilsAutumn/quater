"""Signed cookie helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from collections.abc import Iterable

from quater.exceptions import ConfigurationError

SecretValue = str | bytes


class SignedCookieSigner:
    """HMAC signer for small cookie values."""

    __slots__ = ("_fallback_secrets", "_salt", "_secret")

    def __init__(
        self,
        secret: SecretValue,
        *,
        fallback_secrets: Iterable[SecretValue] = (),
        salt: str = "quater.cookie",
    ) -> None:
        self._secret = _coerce_secret(secret)
        self._fallback_secrets = tuple(
            _coerce_secret(value) for value in fallback_secrets
        )
        self._salt = salt.encode("utf-8")

    def sign(self, value: str) -> str:
        payload = _encode(value.encode("utf-8"))
        signature = self._signature(payload, self._secret)
        return f"{payload}.{signature}"

    def verify(self, signed_value: str) -> str | None:
        payload, separator, signature = signed_value.partition(".")
        if not separator or not payload or not signature:
            return None

        try:
            for secret in (self._secret, *self._fallback_secrets):
                expected = self._signature(payload, secret)
                if hmac.compare_digest(signature, expected):
                    return _decode(payload).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, UnicodeEncodeError, ValueError):
            return None
        return None

    def _signature(self, payload: str, secret: bytes) -> str:
        digest = hmac.new(
            secret,
            self._salt + b":" + payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return _encode(digest)


def _coerce_secret(secret: SecretValue) -> bytes:
    if isinstance(secret, bytes):
        if not secret:
            raise ConfigurationError("Signed cookie secrets must not be empty")
        return secret
    if not secret:
        raise ConfigurationError("Signed cookie secrets must not be empty")
    return secret.encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        (value + padding).encode("ascii"),
        altchars=b"-_",
        validate=True,
    )
