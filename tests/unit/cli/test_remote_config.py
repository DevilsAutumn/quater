from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from quater.cli.errors import CLIUsageError
from quater.cli.remotes import (
    RemoteConfig,
    load_remotes,
    save_remote,
    validate_remote_url,
)
from tests.unit.cli.helpers import file_mode


def test_remote_config_is_written_with_strict_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quater_home = tmp_path / ".quater"
    monkeypatch.setenv("QUATER_HOME", str(quater_home))

    save_remote(
        RemoteConfig(
            name="billing",
            url="https://api.example.com",
            token="secret",
        )
    )

    config_path = quater_home / "remotes.json"

    if os.name != "nt":
        assert file_mode(quater_home) == 0o700
        assert file_mode(config_path) == 0o600

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert "manifest" not in payload["remotes"]["billing"]


def test_remote_config_load_rejects_invalid_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quater_home = tmp_path / ".quater"
    quater_home.mkdir()
    quater_home.joinpath("remotes.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("QUATER_HOME", str(quater_home))

    with pytest.raises(CLIUsageError, match="remote config is invalid"):
        load_remotes()


def test_remote_config_load_rejects_tampered_insecure_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quater_home = tmp_path / ".quater"
    quater_home.mkdir()
    quater_home.joinpath("remotes.json").write_text(
        json.dumps(
            {
                "remotes": {
                    "billing": {
                        "url": "http://api.example.com",
                        "token": "secret",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUATER_HOME", str(quater_home))

    with pytest.raises(CLIUsageError, match="HTTPS"):
        load_remotes()


def test_remote_config_load_rejects_tampered_remote_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quater_home = tmp_path / ".quater"
    quater_home.mkdir()
    quater_home.joinpath("remotes.json").write_text(
        json.dumps(
            {
                "remotes": {
                    "../billing": {
                        "url": "https://api.example.com",
                        "token": "secret",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUATER_HOME", str(quater_home))

    with pytest.raises(CLIUsageError, match="Remote names"):
        load_remotes()


def test_remote_config_load_rejects_empty_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quater_home = tmp_path / ".quater"
    quater_home.mkdir()
    quater_home.joinpath("remotes.json").write_text(
        json.dumps(
            {
                "remotes": {
                    "billing": {
                        "url": "https://api.example.com",
                        "token": " ",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUATER_HOME", str(quater_home))

    with pytest.raises(CLIUsageError, match="remote config is invalid"):
        load_remotes()


def test_remote_url_requires_https_for_non_local_hosts() -> None:
    with pytest.raises(CLIUsageError, match="HTTPS"):
        validate_remote_url("http://api.example.com")


def test_remote_url_allows_localhost_http_for_development() -> None:
    assert validate_remote_url("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"


def test_remote_url_rejects_embedded_credentials() -> None:
    with pytest.raises(CLIUsageError, match="must not include credentials"):
        validate_remote_url("https://token@example.com")


def test_remote_url_rejects_query_strings_and_fragments() -> None:
    with pytest.raises(CLIUsageError, match="query strings"):
        validate_remote_url("https://api.example.com?token=secret")
    with pytest.raises(CLIUsageError, match="fragments"):
        validate_remote_url("https://api.example.com#actions")


def test_remote_url_rejects_whitespace() -> None:
    with pytest.raises(CLIUsageError, match="whitespace"):
        validate_remote_url("https://api.example.com/actions list")


def test_loaded_remote_config_ignores_legacy_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quater_home = tmp_path / ".quater"
    quater_home.mkdir()
    quater_home.joinpath("remotes.json").write_text(
        json.dumps(
            {
                "remotes": {
                    "billing": {
                        "url": "https://api.example.com",
                        "token": "secret",
                        "manifest": {
                            "protocol": "quater-actions.v1",
                            "actions": [],
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUATER_HOME", str(quater_home))

    remote = load_remotes()["billing"]

    assert remote.url == "https://api.example.com"
    assert remote.token == "secret"
    assert not hasattr(remote, "manifest")

    save_remote(remote)
    payload = json.loads(
        quater_home.joinpath("remotes.json").read_text(encoding="utf-8")
    )
    assert "manifest" not in payload["remotes"]["billing"]
