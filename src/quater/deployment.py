"""Deployment safety checks shared by CLI and direct server paths."""

from __future__ import annotations

from typing import Protocol

from quater.config import AppConfig
from quater.exceptions import ConfigurationError


class _ConfiguredApplication(Protocol):
    config: AppConfig


def production_safety_issues(
    target: AppConfig | _ConfiguredApplication,
) -> tuple[str, ...]:
    """Return configuration issues that should block production startup."""

    config = target if isinstance(target, AppConfig) else target.config
    issues: list[str] = []
    if config.debug:
        issues.append("debug must be disabled")
    if config.security != "strict":
        issues.append("security must be 'strict'")
    if not config.allowed_hosts:
        issues.append("allowed_hosts must be configured")
    elif "*" in config.allowed_hosts:
        issues.append("allowed_hosts must not contain '*'")
    return tuple(issues)


def production_safety_message(issues: tuple[str, ...]) -> str:
    joined = "\n".join(f"- {issue}" for issue in issues)
    return f"Production safety check failed:\n{joined}"


def validate_production_config(target: AppConfig | _ConfiguredApplication) -> None:
    issues = production_safety_issues(target)
    if issues:
        raise ConfigurationError(production_safety_message(issues))
