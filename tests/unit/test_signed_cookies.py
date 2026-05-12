from __future__ import annotations

import pytest

from quater.cookies import SignedCookieSigner
from quater.exceptions import ConfigurationError


def test_signed_cookie_round_trip_returns_original_value() -> None:
    signer = SignedCookieSigner("current-secret")

    signed_value = signer.sign("user_123")

    assert signed_value != "user_123"
    assert signer.verify(signed_value) == "user_123"


def test_tampered_signed_cookie_fails_verification() -> None:
    signer = SignedCookieSigner("current-secret")
    signed_value = signer.sign("user_123")
    payload, separator, signature = signed_value.partition(".")
    replacement = "x" if signature[-1] != "x" else "y"
    tampered_value = f"{payload}{separator}{signature[:-1]}{replacement}"

    assert signer.verify(tampered_value) is None


def test_malformed_signed_cookie_fails_closed() -> None:
    signer = SignedCookieSigner("current-secret")

    assert signer.verify("not-base64.%%%%") is None
    assert signer.verify("caf\xe9.signature") is None


def test_rotated_cookie_secret_verifies_old_values_and_signs_with_new_secret() -> None:
    old_signer = SignedCookieSigner("old-secret")
    rotated_signer = SignedCookieSigner(
        "new-secret",
        fallback_secrets=["old-secret"],
    )

    old_value = old_signer.sign("user_123")
    new_value = rotated_signer.sign("user_456")

    assert rotated_signer.verify(old_value) == "user_123"
    assert old_signer.verify(new_value) is None
    assert rotated_signer.verify(new_value) == "user_456"


def test_empty_cookie_secret_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        SignedCookieSigner("")
