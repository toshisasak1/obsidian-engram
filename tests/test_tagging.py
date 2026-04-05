"""Tests for the tagging feature (schema, keyword tagger, search filtering)."""

from __future__ import annotations

from unittest.mock import patch

from engram.config import SearchConfig, TaggingConfig
from engram.db import (
    connect,
    delete_tags_for_entry,
    ensure_schema,
    get_all_tags,
    get_tags_for_entry,
    get_untagged_entry_ids,
    upsert_entries,
    upsert_session,
    upsert_tags,
)
from engram.models import EntryRecord, SessionRecord
from engram.search import search
from engram.tagging import KeywordTagger, _extract_project_from_path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path):
    """Create a temp DB with schema and return connection."""
    conn = connect(tmp_path / "test.db")
    ensure_schema(conn)
    return conn


def _populate(conn):
    """Insert test data."""
    session = SessionRecord(
        session_key="claude:s1",
        source_app="claude",
        source_path="/home/user/.claude/projects/my-app/session.jsonl",
        external_id="s1",
        title="Python Dev Session",
    )
    upsert_session(conn, session)
    entries = [
        EntryRecord(
            entry_id="claude:s1:qa:0",
            session_key="claude:s1",
            source_app="claude",
            source_kind="qa_chunk",
            source_path="/home/user/.claude/projects/my-app/session.jsonl",
            ordinal=0,
            role="qa",
            text="Q: How do I set up a Python venv? A: Run python -m venv .venv",
            timestamp="2026-04-01T10:00:00Z",
        ),
        EntryRecord(
            entry_id="claude:s1:qa:1",
            session_key="claude:s1",
            source_app="claude",
            source_kind="qa_chunk",
            source_path="/home/user/.claude/projects/my-app/session.jsonl",
            ordinal=1,
            role="qa",
            text="Q: How does Docker work? A: Docker uses containers.",
            timestamp="2026-04-01T10:05:00Z",
        ),
        EntryRecord(
            entry_id="claude:s1:qa:2",
            session_key="claude:s1",
            source_app="claude",
            source_kind="qa_chunk",
            source_path="/home/user/.claude/projects/my-app/session.jsonl",
            ordinal=2,
            role="qa",
            text="Q: What is GMMA? A: GMMA is a forex trading indicator.",
            timestamp="2026-04-01T10:10:00Z",
        ),
    ]
    upsert_entries(conn, entries)
    return entries


# ---------------------------------------------------------------------------
# Schema V2 migration tests
# ---------------------------------------------------------------------------


def test_schema_creates_entry_tags_table(tmp_path):
    conn = _make_db(tmp_path)
    # entry_tags table should exist
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='entry_tags'"
    ).fetchone()
    assert row is not None
    conn.close()


def test_schema_migration_is_recorded(tmp_path):
    conn = _make_db(tmp_path)
    row = conn.execute(
        "SELECT MAX(version) AS v FROM schema_migrations"
    ).fetchone()
    assert row["v"] >= 2
    conn.close()


# ---------------------------------------------------------------------------
# Tag CRUD tests
# ---------------------------------------------------------------------------


def test_upsert_and_get_tags(tmp_path):
    conn = _make_db(tmp_path)
    _populate(conn)
    upsert_tags(conn, "claude:s1:qa:0", ["python", "venv", "dev"])
    tags = get_tags_for_entry(conn, "claude:s1:qa:0")
    assert set(tags) == {"python", "venv", "dev"}
    conn.close()


def test_upsert_tags_deduplicates(tmp_path):
    conn = _make_db(tmp_path)
    _populate(conn)
    upsert_tags(conn, "claude:s1:qa:0", ["python", "Python", "PYTHON"])
    tags = get_tags_for_entry(conn, "claude:s1:qa:0")
    # All should be lowercased to "python"
    assert tags == ["python"]
    conn.close()


def test_delete_tags(tmp_path):
    conn = _make_db(tmp_path)
    _populate(conn)
    upsert_tags(conn, "claude:s1:qa:0", ["python", "docker"])
    deleted = delete_tags_for_entry(conn, "claude:s1:qa:0")
    assert deleted == 2
    assert get_tags_for_entry(conn, "claude:s1:qa:0") == []
    conn.close()


def test_get_all_tags(tmp_path):
    conn = _make_db(tmp_path)
    _populate(conn)
    upsert_tags(conn, "claude:s1:qa:0", ["python", "docker"])
    upsert_tags(conn, "claude:s1:qa:1", ["docker", "devops"])
    all_tags = get_all_tags(conn)
    tag_map = {t["tag"]: t["count"] for t in all_tags}
    assert tag_map["docker"] == 2
    assert tag_map["python"] == 1
    conn.close()


def test_get_untagged_entries(tmp_path):
    conn = _make_db(tmp_path)
    _populate(conn)
    # All entries should be untagged initially
    untagged = get_untagged_entry_ids(conn, limit=100)
    assert len(untagged) == 3

    # Tag one entry
    upsert_tags(conn, "claude:s1:qa:0", ["python"])
    untagged = get_untagged_entry_ids(conn, limit=100)
    assert len(untagged) == 2
    assert all(e["entry_id"] != "claude:s1:qa:0" for e in untagged)
    conn.close()


# ---------------------------------------------------------------------------
# KeywordTagger tests
# ---------------------------------------------------------------------------


def test_keyword_tagger_source_and_role():
    config = TaggingConfig()
    tagger = KeywordTagger(config)
    tags = tagger.tag(
        text="Hello world",
        source_app="claude",
        role="assistant",
        source_path="/test/file.jsonl",
    )
    assert "claude" in tags
    assert "assistant" in tags


def test_keyword_tagger_python_detection():
    config = TaggingConfig()
    tagger = KeywordTagger(config)
    tags = tagger.tag(
        text="I need to install pytest and run the test suite",
        source_app="codex",
        role="user",
        source_path="/test/file.jsonl",
    )
    assert "python" in tags or "testing" in tags


def test_keyword_tagger_custom_rules():
    config = TaggingConfig(
        custom_rules={"trading": ["forex", "gmma", "ema"]}
    )
    tagger = KeywordTagger(config)
    tags = tagger.tag(
        text="The GMMA indicator shows a bullish signal on EUR/USD",
        source_app="vault",
        role="document",
        source_path="/vault/trading.md",
    )
    assert "trading" in tags


def test_keyword_tagger_max_tags():
    config = TaggingConfig(max_tags=3)
    tagger = KeywordTagger(config)
    tags = tagger.tag(
        text="python docker git api testing devops sql",
        source_app="claude",
        role="assistant",
        source_path="/projects/big-project/file.jsonl",
    )
    assert len(tags) <= 3


def test_extract_project_from_path():
    assert _extract_project_from_path(
        "/home/user/.claude/projects/obsidian-engram/session.jsonl"
    ) == "obsidian-engram"
    assert _extract_project_from_path(
        "C:\\Users\\toshi\\.claude\\projects\\my-app\\session.jsonl"
    ) == "my-app"
    assert _extract_project_from_path("") == ""


# ---------------------------------------------------------------------------
# Search with tag filter tests
# ---------------------------------------------------------------------------


def test_search_with_tag_filter(tmp_path):
    conn = _make_db(tmp_path)
    _populate(conn)

    # Tag only the first entry
    upsert_tags(conn, "claude:s1:qa:0", ["python"])

    config = SearchConfig()
    # Search with tag filter
    results = search(conn, "How", config, tags="python")
    assert len(results) >= 1
    assert all(r.entry_id == "claude:s1:qa:0" for r in results)
    conn.close()


def test_search_without_tag_filter_returns_all(tmp_path):
    conn = _make_db(tmp_path)
    _populate(conn)
    upsert_tags(conn, "claude:s1:qa:0", ["python"])

    config = SearchConfig()
    results = search(conn, "How", config, tags=None)
    # Should return all matching entries regardless of tags
    assert len(results) >= 2
    conn.close()


def test_search_result_includes_tags(tmp_path):
    conn = _make_db(tmp_path)
    _populate(conn)
    upsert_tags(conn, "claude:s1:qa:0", ["python", "venv"])

    config = SearchConfig()
    results = search(conn, "venv", config)
    tagged = [r for r in results if r.entry_id == "claude:s1:qa:0"]
    assert len(tagged) == 1
    assert set(tagged[0].tags) == {"python", "venv"}
    conn.close()


# ---------------------------------------------------------------------------
# CliTagger tests (mocked)
# ---------------------------------------------------------------------------


def test_cli_tagger_parse_response():
    from engram.tagging import CliTagger

    config = TaggingConfig(cli_command="claude")
    tagger = CliTagger(config)

    entries = [
        {"entry_id": "e1", "text": "python code"},
        {"entry_id": "e2", "text": "docker setup"},
    ]

    response = '{"e1": ["python", "code"], "e2": ["docker", "devops"]}'
    result = tagger._parse_response(response, entries)
    assert result["e1"] == ["python", "code"]
    assert result["e2"] == ["docker", "devops"]


def test_cli_tagger_handles_bad_json():
    from engram.tagging import CliTagger

    config = TaggingConfig(cli_command="claude")
    tagger = CliTagger(config)

    entries = [{"entry_id": "e1", "text": "test"}]
    result = tagger._parse_response("not json at all", entries)
    assert result == {}


def test_cli_tagger_batch_with_mock(tmp_path):
    from engram.tagging import CliTagger

    config = TaggingConfig(cli_command="claude")
    tagger = CliTagger(config)

    entries = [
        {"entry_id": "e1", "text": "python venv setup"},
    ]

    mock_output = '{"e1": ["python", "setup"]}'

    with patch("engram.tagging.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = mock_output
        result = tagger.tag_batch(entries)

    assert result["e1"] == ["python", "setup"]
