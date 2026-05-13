from __future__ import annotations

from quater.exceptions import ConfigurationError, ImproperlyConfigured, QuaterError


def test_configuration_error_is_an_improperly_configured_error() -> None:
    error = ConfigurationError("bad config")

    assert isinstance(error, ImproperlyConfigured)
    assert isinstance(error, QuaterError)
