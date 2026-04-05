"""SQLite database management for Engram.

WAL mode, FTS5 with trigram tokenizer (CJK-safe), schema migrations,
and optional sqlite-vec vector support.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from engram.models import EntryRecord, SessionRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema version history
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 2

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_key   TEXT PRIMARY KEY,
    source_app    TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    cwd           TEXT,
    project       TEXT,
    started_at    TEXT,
    updated_at    TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS entries (
    entry_id      TEXT PRIMARY KEY,
    session_key   TEXT NOT NULL REFERENCES sessions(session_key),
    source_app    TEXT NOT NULL,
    source_kind   TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    ordinal       INTEGER NOT NULL,
    role          TEXT NOT NULL,
    timestamp     TEXT,
    title         TEXT,
    text          TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_entries_session
    ON entries(session_key);
CREATE INDEX IF NOT EXISTS idx_entries_source_path
    ON entries(source_path);
CREATE INDEX IF NOT EXISTS idx_entries_source_app
    ON entries(source_app);
CREATE INDEX IF NOT EXISTS idx_entries_role
    ON entries(role);
CREATE INDEX IF NOT EXISTS idx_entries_timestamp
    ON entries(timestamp);

CREATE TABLE IF NOT EXISTS source_files (
    source_path    TEXT PRIMARY KEY,
    source_app     TEXT NOT NULL,
    mtime_ns       INTEGER NOT NULL,
    file_size      INTEGER NOT NULL,
    content_hash   TEXT,
    last_synced_at TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'ok'
);
"""

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    entry_id    UNINDEXED,
    session_key UNINDEXED,
    source_app  UNINDEXED,
    role        UNINDEXED,
    text,
    tokenize = 'trigram',
    content = 'entries',
    content_rowid = 'rowid'
);

-- Triggers keep the FTS index in sync with the entries table automatically.
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts (rowid, entry_id, session_key, source_app, role, text)
    VALUES (new.rowid, new.entry_id, new.session_key, new.source_app, new.role, new.text);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts (entries_fts, rowid, entry_id, session_key, source_app, role, text)
    VALUES ('delete', old.rowid, old.entry_id, old.session_key, old.source_app, old.role, old.text);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts (entries_fts, rowid, entry_id, session_key, source_app, role, text)
    VALUES ('delete', old.rowid, old.entry_id, old.session_key, old.source_app, old.role, old.text);
    INSERT INTO entries_fts (rowid, entry_id, session_key, source_app, role, text)
    VALUES (new.rowid, new.entry_id, new.session_key, new.source_app, new.role, new.text);
END;
"""

_VECTOR_DDL = """
CREATE TABLE IF NOT EXISTS entry_embeddings (
    entry_id   TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    dimension  INTEGER NOT NULL,
    embedding  BLOB NOT NULL,
    indexed_at TEXT NOT NULL
);
"""

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS entry_tags (
    entry_id   TEXT NOT NULL REFERENCES entries(entry_id) ON DELETE CASCADE,
    tag        TEXT NOT NULL,
    method     TEXT NOT NULL DEFAULT 'keyword',
    tagged_at  TEXT NOT NULL,
    PRIMARY KEY (entry_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_entry_tags_tag ON entry_tags(tag);
CREATE INDEX IF NOT EXISTS idx_entry_tags_method ON entry_tags(method);
"""

_VEC0_DDL_TEMPLATE = """
CREATE VIRTUAL TABLE IF NOT EXISTS entry_vec USING vec0(
    entry_id TEXT PRIMARY KEY,
    embedding float[{dimension}]
);
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the Engram database with WAL mode and foreign keys."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# -- Schema -----------------------------------------------------------------


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create core tables and run any pending migrations."""
    conn.executescript(_SCHEMA_V1)
    _record_migration(conn, 1)
    ensure_fts(conn)
    _migrate_v2(conn)
    logger.debug("Schema ensured at version %d", SCHEMA_VERSION)


def ensure_fts(conn: sqlite3.Connection) -> None:
    """Create the FTS5 virtual table if it does not exist."""
    try:
        conn.executescript(_FTS_DDL)
    except sqlite3.OperationalError as exc:
        # FTS5 or trigram tokenizer not compiled in -- degrade gracefully.
        logger.warning("FTS5 trigram table unavailable: %s", exc)


def try_ensure_vector_table(
    conn: sqlite3.Connection,
    dimension: int = 384,
) -> bool:
    """Create the vector tables if sqlite-vec is available.

    Returns True if the vec0 virtual table was created, False otherwise.
    The plain ``entry_embeddings`` metadata table is always created.
    """
    conn.executescript(_VECTOR_DDL)

    try:
        conn.execute("SELECT vec_version()")
    except sqlite3.OperationalError:
        logger.info("sqlite-vec extension not available; skipping vec0 table")
        return False

    ddl = _VEC0_DDL_TEMPLATE.format(dimension=dimension)
    try:
        conn.executescript(ddl)
        logger.info("vec0 table created with dimension=%d", dimension)
        return True
    except sqlite3.OperationalError as exc:
        logger.warning("Failed to create vec0 table: %s", exc)
        return False


# -- Metadata helpers -------------------------------------------------------


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """Retrieve a value from the memory_meta table."""
    row = conn.execute(
        "SELECT value FROM memory_meta WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or update a value in the memory_meta table."""
    conn.execute(
        "INSERT INTO memory_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


# -- Session CRUD -----------------------------------------------------------


def upsert_session(conn: sqlite3.Connection, session: SessionRecord) -> None:
    """Insert or replace a session record."""
    conn.execute(
        """
        INSERT INTO sessions (
            session_key, source_app, source_path, external_id,
            title, cwd, project, started_at, updated_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_key) DO UPDATE SET
            source_app    = excluded.source_app,
            source_path   = excluded.source_path,
            external_id   = excluded.external_id,
            title         = excluded.title,
            cwd           = excluded.cwd,
            project       = excluded.project,
            started_at    = excluded.started_at,
            updated_at    = excluded.updated_at,
            metadata_json = excluded.metadata_json
        """,
        (
            session.session_key,
            session.source_app,
            session.source_path,
            session.external_id,
            session.title,
            session.cwd,
            session.project,
            session.started_at,
            session.updated_at,
            json.dumps(session.metadata, ensure_ascii=False),
        ),
    )
    conn.commit()


# -- Entry CRUD -------------------------------------------------------------


def upsert_entries(
    conn: sqlite3.Connection,
    entries: list[EntryRecord],
) -> None:
    """Bulk-insert or replace entries.

    The FTS index is kept in sync automatically via triggers defined in
    ``ensure_fts`` (AFTER INSERT / UPDATE / DELETE on the entries table).
    """
    if not entries:
        return

    entry_rows = [
        (
            e.entry_id,
            e.session_key,
            e.source_app,
            e.source_kind,
            e.source_path,
            e.ordinal,
            e.role,
            e.timestamp,
            e.title,
            e.text,
            json.dumps(e.metadata, ensure_ascii=False),
        )
        for e in entries
    ]

    conn.executemany(
        """
        INSERT INTO entries (
            entry_id, session_key, source_app, source_kind,
            source_path, ordinal, role, timestamp,
            title, text, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entry_id) DO UPDATE SET
            session_key   = excluded.session_key,
            source_app    = excluded.source_app,
            source_kind   = excluded.source_kind,
            source_path   = excluded.source_path,
            ordinal       = excluded.ordinal,
            role          = excluded.role,
            timestamp     = excluded.timestamp,
            title         = excluded.title,
            text          = excluded.text,
            metadata_json = excluded.metadata_json
        """,
        entry_rows,
    )

    conn.commit()


def delete_entries_for_source(
    conn: sqlite3.Connection,
    source_path: str,
) -> int:
    """Delete all entries that came from *source_path*.

    The FTS index is updated automatically via the AFTER DELETE trigger.
    Returns the number of deleted entry rows.
    """
    cur = conn.execute(
        "DELETE FROM entries WHERE source_path = ?",
        (source_path,),
    )
    conn.commit()
    return cur.rowcount


# -- Source file tracking ----------------------------------------------------


def get_source_file_info(
    conn: sqlite3.Connection,
    source_path: str,
) -> dict | None:
    """Return the tracked metadata for a source file, or None."""
    row = conn.execute(
        "SELECT * FROM source_files WHERE source_path = ?",
        (source_path,),
    ).fetchone()
    return dict(row) if row else None


def update_source_file(
    conn: sqlite3.Connection,
    source_path: str,
    source_app: str,
    mtime_ns: int,
    file_size: int,
    content_hash: str | None = None,
) -> None:
    """Insert or update the tracking row for a source file."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO source_files (
            source_path, source_app, mtime_ns, file_size,
            content_hash, last_synced_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, 'ok')
        ON CONFLICT(source_path) DO UPDATE SET
            source_app     = excluded.source_app,
            mtime_ns       = excluded.mtime_ns,
            file_size      = excluded.file_size,
            content_hash   = excluded.content_hash,
            last_synced_at = excluded.last_synced_at,
            status         = 'ok'
        """,
        (source_path, source_app, mtime_ns, file_size, content_hash, now),
    )
    conn.commit()


# -- Tag CRUD ---------------------------------------------------------------


def upsert_tags(
    conn: sqlite3.Connection,
    entry_id: str,
    tags: list[str],
    method: str = "keyword",
) -> None:
    """Insert tags for an entry, ignoring duplicates."""
    if not tags:
        return
    now = _now_iso()
    conn.executemany(
        """
        INSERT INTO entry_tags (entry_id, tag, method, tagged_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(entry_id, tag) DO UPDATE SET
            method    = excluded.method,
            tagged_at = excluded.tagged_at
        """,
        [(entry_id, t.lower().strip(), method, now) for t in tags if t.strip()],
    )
    conn.commit()


def get_tags_for_entry(conn: sqlite3.Connection, entry_id: str) -> list[str]:
    """Return all tags for a given entry."""
    rows = conn.execute(
        "SELECT tag FROM entry_tags WHERE entry_id = ? ORDER BY tag",
        (entry_id,),
    ).fetchall()
    return [row["tag"] for row in rows]


def get_all_tags(conn: sqlite3.Connection) -> list[dict]:
    """Return all unique tags with counts."""
    rows = conn.execute(
        "SELECT tag, COUNT(*) AS cnt FROM entry_tags GROUP BY tag ORDER BY cnt DESC"
    ).fetchall()
    return [{"tag": row["tag"], "count": row["cnt"]} for row in rows]


def delete_tags_for_entry(conn: sqlite3.Connection, entry_id: str) -> int:
    """Delete all tags for an entry. Returns count of deleted rows."""
    cur = conn.execute(
        "DELETE FROM entry_tags WHERE entry_id = ?", (entry_id,)
    )
    conn.commit()
    return cur.rowcount


def get_untagged_entry_ids(
    conn: sqlite3.Connection,
    method: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return entries that have no tags (or no tags from a specific method).

    Returns dicts with entry_id, text, source_app, role, source_path.
    """
    if method:
        sql = """
            SELECT e.entry_id, e.text, e.source_app, e.role, e.source_path
            FROM entries e
            LEFT JOIN entry_tags t ON e.entry_id = t.entry_id AND t.method = ?
            WHERE t.entry_id IS NULL AND length(e.text) > 10
            LIMIT ?
        """
        rows = conn.execute(sql, (method, limit)).fetchall()
    else:
        sql = """
            SELECT e.entry_id, e.text, e.source_app, e.role, e.source_path
            FROM entries e
            LEFT JOIN entry_tags t ON e.entry_id = t.entry_id
            WHERE t.entry_id IS NULL AND length(e.text) > 10
            LIMIT ?
        """
        rows = conn.execute(sql, (limit,)).fetchall()
    return [dict(row) for row in rows]


# -- Stats ------------------------------------------------------------------


def get_stats(conn: sqlite3.Connection) -> dict:
    """Return a summary dict with row counts for each core table."""

    def _count(table: str) -> int:
        try:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()  # noqa: S608
            return row["n"] if row else 0
        except sqlite3.OperationalError:
            return 0

    return {
        "sessions": _count("sessions"),
        "entries": _count("entries"),
        "source_files": _count("source_files"),
        "fts_rows": _count("entries_fts"),
        "embeddings": _count("entry_embeddings"),
        "tagged_entries": _count("entry_tags"),
        "schema_version": _current_version(conn),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT MAX(version) AS v FROM schema_migrations"
        ).fetchone()
        return row["v"] if row and row["v"] is not None else 0
    except sqlite3.OperationalError:
        return 0


def _record_migration(conn: sqlite3.Connection, version: int) -> None:
    if _current_version(conn) >= version:
        return
    conn.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, _now_iso()),
    )
    conn.commit()


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Apply schema V2: entry_tags table for tagging support."""
    if _current_version(conn) >= 2:
        return
    conn.executescript(_SCHEMA_V2)
    _record_migration(conn, 2)
    logger.debug("Migrated to schema V2 (entry_tags)")


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS index from the entries table.

    Useful after bulk operations or if the FTS index gets out of sync.
    """
    try:
        conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
        conn.commit()
    except sqlite3.OperationalError:
        pass
