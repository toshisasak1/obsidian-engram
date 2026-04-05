from engram.parsers.base import build_qa_entries, normalize_text, split_markdown_sections
from engram.parsers.claude import ClaudeParser
from engram.parsers.codex import CodexParser
from engram.parsers.vault import VaultParser


def test_claude_parser(testdata):
    parser = ClaudeParser()
    session, entries = parser.parse(testdata / "claude_session.jsonl")
    assert session.source_app == "claude"
    assert len(entries) > 0
    # Should have QA entries
    qa_entries = [e for e in entries if e.role == "qa"]
    assert len(qa_entries) >= 1

def test_codex_parser(testdata):
    parser = CodexParser()
    session, entries = parser.parse(testdata / "history.jsonl")
    assert session.source_app == "codex"
    assert len(entries) > 0

def test_vault_parser(testdata):
    parser = VaultParser()
    session, entries = parser.parse(testdata / "vault_doc.md")
    assert session.source_app == "vault"
    assert len(entries) > 0
    # Should have sections
    assert any("PostgreSQL" in e.text for e in entries)

def test_normalize_text():
    assert normalize_text("  hello   world  ") == "hello world"
    assert normalize_text("a\n\n\n\nb") == "a\n\nb"

def test_split_markdown_sections():
    md = "# Title\n\nIntro\n\n## Section 1\n\nContent 1\n\n## Section 2\n\nContent 2"
    sections = split_markdown_sections(md)
    assert len(sections) >= 2

def test_build_qa_entries():
    from engram.models import EntryRecord, SessionRecord
    session = SessionRecord(
        session_key="test:1", source_app="test", source_path="/test",
        external_id="1", title="Test"
    )
    entries = [
        EntryRecord(entry_id="1", session_key="test:1", source_app="test",
                    source_kind="message", source_path="/test", ordinal=0,
                    role="user", text="What is Python?"),
        EntryRecord(entry_id="2", session_key="test:1", source_app="test",
                    source_kind="message", source_path="/test", ordinal=1,
                    role="assistant", text="Python is a programming language."),
    ]
    qa = build_qa_entries(session, entries)
    assert len(qa) == 1
    assert qa[0].role == "qa"
    assert "Q:" in qa[0].text
    assert "A:" in qa[0].text
