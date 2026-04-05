"""Pure data models for Engram. No I/O, no side effects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionRecord:
    """A conversation session from any source application."""

    session_key: str  # "source_app:external_id"
    source_app: str  # "claude", "codex", "gemini", "vscode", "vault"
    source_path: str  # Absolute path to source file
    external_id: str  # Original session ID from source
    title: str
    cwd: str | None = None
    project: str | None = None
    started_at: str | None = None  # ISO 8601
    updated_at: str | None = None  # ISO 8601
    metadata: dict = field(default_factory=dict)


@dataclass
class EntryRecord:
    """A single indexed entry (message, chunk, section) within a session."""

    entry_id: str  # Unique across all sources
    session_key: str
    source_app: str
    source_kind: str  # "message", "qa_chunk", "artifact_chunk", "vault_section"
    source_path: str
    ordinal: int
    role: str  # "user", "assistant", "qa", "artifact", "document"
    text: str
    timestamp: str | None = None
    title: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    """A single result from hybrid search (FTS5 + optional vector)."""

    entry_id: str
    session_key: str
    source_app: str
    role: str
    text: str
    snippet: str
    score: float
    timestamp: str | None = None
    entry_title: str | None = None
    session_title: str | None = None
    source_path: str = ""
    fts_rank: int | None = None
    vector_rank: int | None = None
    decay_multiplier: float = 1.0


@dataclass
class SyncStats:
    """Counters accumulated during a sync run."""

    scanned: int = 0
    indexed: int = 0
    skipped: int = 0
    embedded: int = 0
    errors: int = 0
