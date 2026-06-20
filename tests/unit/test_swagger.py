from __future__ import annotations

from pathlib import Path

import pytest

from quater.docs import swagger
from quater.docs.swagger import swagger_ui_asset_response
from quater.exceptions import ConfigurationError


def test_swagger_ui_asset_response_rejects_unknown_assets() -> None:
    with pytest.raises(ConfigurationError, match="Unsupported Swagger UI asset"):
        swagger_ui_asset_response("not-a-real-asset.js")


def test_swagger_ui_asset_response_handles_os_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    swagger._swagger_ui_asset_bytes.cache_clear()

    def mock_read_bytes(self: Path) -> bytes:
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "read_bytes", mock_read_bytes)

    with pytest.raises(ConfigurationError, match="Swagger UI asset is unavailable"):
        swagger_ui_asset_response("swagger-ui.css")

    swagger._swagger_ui_asset_bytes.cache_clear()


def test_swagger_ui_asset_response_handles_malformed_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    swagger._swagger_ui_asset_dir.cache_clear()
    swagger._swagger_ui_asset_bytes.cache_clear()

    class FakeBundle:
        swagger_ui_path = 12345

    def mock_import_module(name: str) -> object:
        if name == "swagger_ui_bundle":
            return FakeBundle()
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(swagger, "import_module", mock_import_module)

    with pytest.raises(
        ConfigurationError, match="swagger-ui-bundle is not installed correctly"
    ):
        swagger_ui_asset_response("swagger-ui.css")

    swagger._swagger_ui_asset_dir.cache_clear()
    swagger._swagger_ui_asset_bytes.cache_clear()
