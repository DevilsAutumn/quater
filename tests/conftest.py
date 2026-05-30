"""Shared pytest configuration for Quater."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support.database import Database, init_db


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    """A fresh, seeded SQLite database on disk for one test.

    Backed by a ``tmp_path`` file so every test is fully isolated: the schema
    and seed rows are rebuilt from scratch and nothing leaks between tests. The
    read-back engine is disposed once the test finishes.
    """

    database = init_db(tmp_path / "quater_test.db")
    try:
        yield database
    finally:
        database.engine.dispose()
