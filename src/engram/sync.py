"""Sync engine -- orchestrates source collection, change detection, and DB upsert.

The ``SyncEngine`` walks every enabled source, discovers files through the
corresponding parser, computes content hashes for change detection, and upserts
parsed entries into the database.  Stale source files that no longer exist on
disk are cleaned up automatically.

Usage::

    from engram.config import load_config
    from engram.sync import SyncEngine

    cfg = load_config(vault_path=Path("."))
    engine = SyncEngine(cfg)
    stats = engine.sync_once()
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from pathlib import Path

from engram.config import EngramConfig
from engram.db import (
    connect,
    delete_entries_for_source,
    ensure_schema,
    get_source_file_info,
    try_ensure_vector_table,
    update_source_file,
    upsert_entries,
    upsert_session,
)
from engram.models import SyncStats
from engram.parsers import get_parser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SyncEngine
# ---------------------------------------------------------------------------


class SyncEngine:
    """Stateless sync orchestrator.

    Each call to :meth:`sync_once` opens a fresh connection, walks every
    configured source, and returns accumulated :class:`SyncStats`.
    """

    def __init__(self, config: EngramConfig) -> None:
        self.config = config
        self.db_path = config.db_path

    # -- public API ---------------------------------------------------------

    def sync_once(
        self,
        *,
        skip_embeddings: bool = False,
        source_filter: str | None = None,
    ) -> SyncStats:
        """Run a single sync pass across all configured sources.

        Parameters
        ----------
        skip_embeddings:
            When ``True``, skip the embedding phase even if the config has
            embeddings enabled.
        source_filter:
            When given, only sync the named source (must match a key in
            ``config.sources``).  Other sources and vault knowledge are
            skipped.

        Returns
        -------
        SyncStats
            Accumulated counters for scanned / indexed / skipped / errors.
        """
        stats = SyncStats()
        conn = connect(self.db_path)
        try:
            ensure_schema(conn)

            # Track every source_path we visit so we can prune stale rows.
            seen_paths: set[str] = set()

            # 1. Walk configured AI-tool sources.
            self._sync_sources(conn, seen_paths, stats, source_filter)

            # 2. Walk vault markdown files (if enabled and no filter active).
            if source_filter is None:
                self._sync_vault(conn, seen_paths, stats)

            # 3. Remove DB rows whose source file no longer exists.
            self._cleanup_stale(conn, seen_paths, stats)

            # 4. Generate embeddings for new entries.
            if not skip_embeddings and self.config.embedding.enabled:
                stats.embedded = self._sync_embeddings(conn)

            conn.commit()
        except Exception:
            logger.exception("Sync pass failed")
            stats.errors += 1
        finally:
            conn.close()

        return stats

    # -- source iteration ---------------------------------------------------

    def _sync_sources(
        self,
        conn: sqlite3.Connection,
        seen_paths: set[str],
        stats: SyncStats,
        source_filter: str | None,
    ) -> None:
        """Iterate over configured AI-tool sources and index changed files."""
        for source_name, source_config in self.config.sources.items():
            if not source_config.enabled:
                continue
            if source_filter is not None and source_name != source_filter:
                continue

            parser_name = source_config.parser or source_name
            try:
                parser = get_parser(parser_name)
            except ValueError:
                logger.warning(
                    "Unknown parser %r for source %r -- skipping",
                    parser_name,
                    source_name,
                )
                stats.errors += 1
                continue

            root = (
                Path(source_config.path)
                if source_config.path
                else parser.default_root()
            )
            if root is None or not root.exists():
                logger.debug(
                    "Source %s root does not exist: %s", source_name, root
                )
                continue

            for file_path in parser.discover_paths(root):
                self._process_file(
                    conn, file_path, source_name, parser, seen_paths, stats
                )

    def _sync_vault(
        self,
        conn: sqlite3.Connection,
        seen_paths: set[str],
        stats: SyncStats,
    ) -> None:
        """Index vault markdown files when vault_knowledge is enabled."""
        if not self.config.vault_knowledge.enabled:
            return
        vault_path = self.config.vault_path
        if vault_path is None or not vault_path.exists():
            return

        try:
            parser = get_parser("vault")
        except ValueError:
            logger.warning("Vault parser not available -- skipping vault sync")
            return

        for file_path in parser.discover_paths(vault_path):
            self._process_file(
                conn, file_path, "vault", parser, seen_paths, stats
            )

    # -- per-file processing ------------------------------------------------

    def _process_file(
        self,
        conn: sqlite3.Connection,
        file_path: Path,
        source_name: str,
        parser: object,
        seen_paths: set[str],
        stats: SyncStats,
    ) -> None:
        """Check a single file for changes; parse and upsert if needed."""
        stats.scanned += 1
        source_path_str = str(file_path)
        seen_paths.add(source_path_str)

        # Stat the file -------------------------------------------------
        try:
            st = file_path.stat()
        except OSError:
            logger.debug("Cannot stat %s -- skipping", file_path)
            return

        # Settle check -- skip files modified too recently so editors can
        # finish flushing writes.
        age = time.time() - st.st_mtime
        if age < self.config.sync.settle_seconds:
            stats.skipped += 1
            return

        # Content hash for reliable change detection --------------------
        content_hash = _file_hash(file_path)
        if not content_hash:
            # Could not read the file -- skip silently.
            stats.skipped += 1
            return

        # Compare against the DB record ---------------------------------
        existing = get_source_file_info(conn, source_path_str)
        if existing is not None and not _has_changed(existing, st, content_hash):
            stats.skipped += 1
            return

        # Parse the file ------------------------------------------------
        try:
            session, entries = parser.parse(file_path)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", file_path, exc)
            stats.errors += 1
            return

        if not entries:
            stats.skipped += 1
        else:
            # Delete old entries first so the FTS triggers fire correctly,
            # then insert the fresh set.
            delete_entries_for_source(conn, source_path_str)
            upsert_session(conn, session)
            upsert_entries(conn, entries)
            stats.indexed += 1
            logger.debug(
                "Indexed %s (%d entries)", file_path, len(entries)
            )

        # Update the source-file tracking row ---------------------------
        update_source_file(
            conn,
            source_path_str,
            source_name,
            int(st.st_mtime_ns),
            st.st_size,
            content_hash,
        )

    # -- stale cleanup ------------------------------------------------------

    def _cleanup_stale(
        self,
        conn: sqlite3.Connection,
        seen_paths: set[str],
        stats: SyncStats,
    ) -> None:
        """Remove DB rows for source files that no longer exist on disk."""
        cursor = conn.execute("SELECT source_path FROM source_files")
        stale: list[str] = [
            row["source_path"]
            for row in cursor.fetchall()
            if row["source_path"] not in seen_paths
        ]

        for path in stale:
            delete_entries_for_source(conn, path)
            conn.execute(
                "DELETE FROM source_files WHERE source_path = ?", (path,)
            )
            logger.debug("Cleaned stale source: %s", path)

        if stale:
            conn.commit()

    # -- embeddings ---------------------------------------------------------

    def _sync_embeddings(self, conn: sqlite3.Connection) -> int:
        """Generate embeddings for entries that do not have one yet.

        Returns the number of newly embedded entries.  If the embeddings
        dependencies are not installed the step is silently skipped.
        """
        try:
            from engram.embeddings import create_embedder  # type: ignore[import-untyped]
        except ImportError:
            logger.info(
                "Embeddings dependencies not installed -- skipping embedding phase"
            )
            return 0

        embedder = create_embedder(self.config.embedding)
        if embedder is None:
            return 0

        # Ensure the storage tables exist.
        try_ensure_vector_table(conn, embedder.dimension)

        # Find entries that have no corresponding embedding row.
        rows = conn.execute(
            """
            SELECT e.entry_id, e.text
            FROM entries e
            LEFT JOIN entry_embeddings ee ON e.entry_id = ee.entry_id
            WHERE ee.entry_id IS NULL AND length(e.text) > 10
            LIMIT 1000
            """,
        ).fetchall()

        if not rows:
            return 0

        batch_size = self.config.embedding.batch_size
        max_chars = self.config.embedding.max_characters
        count = 0

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            entry_ids = [r["entry_id"] for r in batch]
            texts = [r["text"][:max_chars] for r in batch]

            try:
                vectors = embedder.encode(texts)
            except Exception as exc:
                logger.warning("Embedding batch failed: %s", exc)
                continue

            for entry_id, vec in zip(entry_ids, vectors, strict=False):
                try:
                    import numpy as np

                    blob = vec.astype(np.float32).tobytes()
                except Exception:
                    blob = bytes(vec)

                # Store embedding (metadata + blob).
                conn.execute(
                    """
                    INSERT OR REPLACE INTO entry_embeddings
                        (entry_id, model_name, dimension, embedding, indexed_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    """,
                    (entry_id, embedder.model_name, embedder.dimension, blob),
                )

                # Optionally populate the vec0 virtual table.
                _upsert_vec0(conn, entry_id, blob)
                count += 1

        conn.commit()
        return count


# ---------------------------------------------------------------------------
# Pure helpers (module-level, no side effects)
# ---------------------------------------------------------------------------


def _file_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of *path*, or ``""`` on read failure."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _has_changed(
    existing: dict,
    st: os.stat_result,
    content_hash: str,
) -> bool:
    """Return ``True`` if any tracked attribute differs from *existing*."""
    if existing.get("mtime_ns") != int(st.st_mtime_ns):
        return True
    if existing.get("file_size") != st.st_size:
        return True
    return existing.get("content_hash") != content_hash


def _vector_rowid(entry_id: str) -> int:
    """Derive a deterministic positive int64 rowid from *entry_id*.

    Used as the ``rowid`` for the ``entry_vec`` vec0 virtual table so we
    can look up vectors by entry_id without an extra mapping table.
    """
    digest = hashlib.sha256(entry_id.encode()).digest()[:8]
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


def _upsert_vec0(
    conn: sqlite3.Connection,
    entry_id: str,
    blob: bytes,
) -> None:
    """Insert into the vec0 table if it exists; silently skip otherwise."""
    import contextlib

    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute(
            "INSERT OR REPLACE INTO entry_vec (rowid, embedding) VALUES (?, ?)",
            (_vector_rowid(entry_id), blob),
        )
