from __future__ import annotations

from pathlib import Path

import pytest

TESTDATA = Path(__file__).parent / "testdata"

@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database with schema applied."""
    from engram.db import connect, ensure_fts, ensure_schema
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    ensure_schema(conn)
    ensure_fts(conn)
    yield conn
    conn.close()

@pytest.fixture
def testdata():
    return TESTDATA

@pytest.fixture
def sample_config(tmp_path):
    from engram.config import EngramConfig
    return EngramConfig(db_path=tmp_path / "test.db")
