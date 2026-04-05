from engram.db import (
    connect,
    ensure_fts,
    ensure_schema,
    get_meta,
    get_stats,
    set_meta,
    upsert_entries,
    upsert_session,
)
from engram.models import EntryRecord, SessionRecord


def test_schema_creation(tmp_path):
    conn = connect(tmp_path / "test.db")
    ensure_schema(conn)
    ensure_fts(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    tables = [r[0] for r in rows]
    assert "sessions" in tables
    assert "entries" in tables
    assert "source_files" in tables
    conn.close()

def test_upsert_session(tmp_db):
    session = SessionRecord(
        session_key="claude:test-1", source_app="claude",
        source_path="/test/session.jsonl", external_id="test-1",
        title="Test Session"
    )
    upsert_session(tmp_db, session)
    row = tmp_db.execute(
        "SELECT * FROM sessions WHERE session_key = ?",
        ("claude:test-1",),
    ).fetchone()
    assert row is not None

def test_upsert_entries_and_fts(tmp_db):
    session = SessionRecord(
        session_key="claude:test-2", source_app="claude",
        source_path="/test/s2.jsonl", external_id="test-2",
        title="Test Session 2"
    )
    upsert_session(tmp_db, session)
    entries = [
        EntryRecord(
            entry_id="claude:test-2:qa:0", session_key="claude:test-2",
            source_app="claude", source_kind="qa_chunk",
            source_path="/test/s2.jsonl", ordinal=0, role="qa",
            text="Q: What is Python? A: Python is a programming language.",
        )
    ]
    upsert_entries(tmp_db, entries)
    # Check FTS works
    results = tmp_db.execute(
        "SELECT entry_id FROM entries_fts WHERE text MATCH ?", ("Python",)
    ).fetchall()
    assert len(results) >= 1

def test_meta(tmp_db):
    set_meta(tmp_db, "test_key", "test_value")
    assert get_meta(tmp_db, "test_key") == "test_value"

def test_stats(tmp_db):
    stats = get_stats(tmp_db)
    assert "sessions" in stats
    assert "entries" in stats
