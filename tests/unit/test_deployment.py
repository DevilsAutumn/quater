from __future__ import annotations

import pytest

from quater import Quater
from quater.deployment import production_safety_issues


@pytest.mark.parametrize(
    ("app", "issues"),
    (
        (
            Quater(debug=True, allowed_hosts=["api.example.com"]),
            ("debug must be disabled",),
        ),
        (
            Quater(),
            ("allowed_hosts must be configured",),
        ),
        (
            Quater(allowed_hosts=["*"]),
            ("allowed_hosts must not contain '*'",),
        ),
        (
            Quater(security="off", allowed_hosts=["api.example.com"]),
            ("security must be 'strict'",),
        ),
    ),
)
def test_production_safety_issues(app: Quater, issues: tuple[str, ...]) -> None:
    assert production_safety_issues(app) == issues
