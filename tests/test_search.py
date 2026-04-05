from engram.config import SearchConfig
from engram.db import connect, ensure_fts, ensure_schema, upsert_entries, upsert_session
from engram.models import EntryRecord, SessionRecord
from engram.search import build_snippet, safe_match_query, search, time_decay_multiplier


def _populate_db(conn):
    session = SessionRecord(
        session_key="claude:s1", source_app="claude",
        source_path="/test/s1.jsonl", external_id="s1",
        title="Test Session"
    )
    upsert_session(conn, session)
    entries = [
        EntryRecord(
            entry_id="claude:s1:qa:0", session_key="claude:s1",
            source_app="claude", source_kind="qa_chunk",
            source_path="/test/s1.jsonl", ordinal=0, role="qa",
            text="Q: What is machine learning? A: Machine learning is a subset of AI.",
            timestamp="2026-04-01T10:00:00Z",
        ),
        EntryRecord(
            entry_id="claude:s1:qa:1", session_key="claude:s1",
            source_app="claude", source_kind="qa_chunk",
            source_path="/test/s1.jsonl", ordinal=1, role="qa",
            text="Q: How does Python work? A: Python is an interpreted language.",
            timestamp="2026-04-01T10:05:00Z",
        ),
    ]
    upsert_entries(conn, entries)

def test_fts_search(tmp_path):
    conn = connect(tmp_path / "test.db")
    ensure_schema(conn)
    ensure_fts(conn)
    _populate_db(conn)
    config = SearchConfig()
    results = search(conn, "machine learning", config, limit=5)
    assert len(results) >= 1
    assert any("machine learning" in r.text.lower() for r in results)
    conn.close()

def test_time_decay():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    old = (now - timedelta(days=60)).isoformat()

    assert time_decay_multiplier(recent, 30.0) > 0.9
    assert time_decay_multiplier(old, 30.0) < 0.3
    assert time_decay_multiplier(None, 30.0) == 0.5

def test_safe_match_query():
    assert safe_match_query("hello world") != ""
    assert safe_match_query('test "quoted"') != ""
    assert safe_match_query("") == ""

def test_build_snippet():
    text = "This is a long text about machine learning and artificial intelligence. " * 10
    snippet = build_snippet(text, "machine learning")
    assert len(snippet) <= 350  # context_chars + some margin
    assert "machine" in snippet.lower()
