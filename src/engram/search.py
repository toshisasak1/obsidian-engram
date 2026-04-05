"""Hybrid search engine: FTS5 + optional vector search with RRF fusion.

Algorithm
---------
1. FTS5 keyword search (BM25 ranking via ``entries_fts``)
2. Vector cosine similarity (if embeddings enabled and sqlite-vec loaded)
3. Reciprocal Rank Fusion:  ``score = sum(1 / (K + rank))``
4. Time decay:  ``multiplier = 0.5 ^ (age_days / half_life_days)``
5. Final:  ``score = rrf_score * decay_multiplier``

Graceful degradation
--------------------
* If FTS5 is unavailable the function logs a warning and returns ``[]``.
* If embeddings are disabled or sqlite-vec is not loaded, vector search is
  silently skipped and only FTS results are used.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import struct
from datetime import datetime, timezone
from typing import Any

from engram.config import EmbeddingConfig, SearchConfig
from engram.models import SearchResult

logger = logging.getLogger(__name__)

# Characters that carry special meaning inside FTS5 MATCH expressions.
# We strip / escape them in ``safe_match_query`` to avoid syntax errors.
_FTS5_SPECIAL = re.compile(r'["\'\(\)\*\+\-\:\;\<\>\^\{\}\~]')

# Rough heuristic for CJK codepoint ranges (CJK Unified + extensions).
_CJK_RE = re.compile(
    r"[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff"
    r"\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]+"
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def search(
    conn: sqlite3.Connection,
    query: str,
    config: SearchConfig,
    embedding_config: EmbeddingConfig | None = None,
    limit: int = 10,
    source_app: str | None = None,
    tags: str | None = None,
) -> list[SearchResult]:
    """Hybrid search: FTS5 + vector (if available) with RRF fusion and time decay.

    Parameters
    ----------
    conn:
        An open SQLite connection (from ``engram.db.connect``).
    query:
        Free-text search query.
    config:
        Search tuning knobs (RRF *K*, half-life, limit multipliers).
    embedding_config:
        When present **and** ``enabled=True``, vector search is attempted.
    limit:
        Maximum number of results to return.
    source_app:
        Optional filter -- only return entries from this source application.
    tags:
        Comma-separated tag names for filtering (OR match).

    Returns
    -------
    list[SearchResult]
        Results sorted by final fused + decayed score (descending).
    """
    if not query or not query.strip():
        return []

    query = query.strip()

    # -- Step 1: FTS5 keyword search --------------------------------------
    fts_limit = limit * config.fts_limit_multiplier
    fts_results = _fts_search(conn, query, fts_limit, source_app)

    # -- Step 2: Vector search (optional) ---------------------------------
    vec_results: list[dict[str, Any]] = []
    use_vectors = (
        embedding_config is not None
        and embedding_config.enabled
        and _vec_available(conn)
    )
    if use_vectors:
        assert embedding_config is not None  # for type-checker
        vec_limit = limit * config.vector_limit_multiplier
        vec_results = _vector_search(
            conn, query, vec_limit, embedding_config, source_app
        )

    # -- Step 3: RRF fusion -----------------------------------------------
    if fts_results or vec_results:
        fused = _rrf_fuse(fts_results, vec_results, limit, config.rrf_k)
    else:
        fused = []

    # -- Step 4: Time decay -----------------------------------------------
    decayed = _apply_time_decay(fused, config.half_life_days)

    # -- Step 4b: Tag filtering (if requested) -----------------------------
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        if tag_list:
            decayed = _filter_by_tags(conn, decayed, tag_list)

    # -- Step 5: Build SearchResult objects --------------------------------
    results: list[SearchResult] = []
    for item in decayed[:limit]:
        snippet = item.get("snippet") or build_snippet(
            item.get("text", ""), query
        )
        entry_tags = _get_entry_tags(conn, item["entry_id"])
        results.append(
            SearchResult(
                entry_id=item["entry_id"],
                session_key=item.get("session_key", ""),
                source_app=item.get("source_app", ""),
                role=item.get("role", ""),
                text=item.get("text", ""),
                snippet=snippet,
                score=item["final_score"],
                timestamp=item.get("timestamp"),
                entry_title=item.get("entry_title"),
                session_title=item.get("session_title"),
                source_path=item.get("source_path", ""),
                fts_rank=item.get("fts_rank"),
                vector_rank=item.get("vector_rank"),
                decay_multiplier=item.get("decay_multiplier", 1.0),
                tags=entry_tags,
            )
        )
    return results


# ---------------------------------------------------------------------------
# FTS5 keyword search
# ---------------------------------------------------------------------------


def _fts_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    source_app: str | None,
) -> list[dict[str, Any]]:
    """Run an FTS5 MATCH query and return ranked dicts.

    The FTS table ``entries_fts`` is a content-sync table backed by
    ``entries``.  We join through ``entries`` to fetch metadata columns
    and through ``sessions`` to fetch the session title.
    """
    match_expr = safe_match_query(query)
    if not match_expr:
        return []

    # Build the WHERE clause pieces.
    where_extra = ""
    params: list[Any] = [match_expr]
    if source_app:
        where_extra = "AND e.source_app = ?"
        params.append(source_app)
    params.append(limit)

    sql = f"""
        SELECT
            e.entry_id,
            e.session_key,
            e.source_app,
            e.role,
            e.text,
            e.timestamp,
            e.title        AS entry_title,
            e.source_path,
            s.title         AS session_title,
            rank            AS bm25_rank
        FROM entries_fts AS f
        JOIN entries  AS e ON e.entry_id = f.entry_id
        LEFT JOIN sessions AS s ON s.session_key = e.session_key
        WHERE entries_fts MATCH ?
        {where_extra}
        ORDER BY rank
        LIMIT ?
    """

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("FTS5 search failed: %s", exc)
        return []

    results: list[dict[str, Any]] = []
    for rank_pos, row in enumerate(rows, start=1):
        results.append(
            {
                "entry_id": row["entry_id"],
                "session_key": row["session_key"],
                "source_app": row["source_app"],
                "role": row["role"],
                "text": row["text"],
                "timestamp": row["timestamp"],
                "entry_title": row["entry_title"],
                "session_title": row["session_title"],
                "source_path": row["source_path"],
                "bm25_rank": row["bm25_rank"],
                "fts_rank": rank_pos,
                "snippet": build_snippet(row["text"], query),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Vector cosine-similarity search
# ---------------------------------------------------------------------------


def _vec_available(conn: sqlite3.Connection) -> bool:
    """Return True if sqlite-vec is loaded AND entry_vec table exists."""
    try:
        conn.execute("SELECT vec_version()")
    except sqlite3.OperationalError:
        return False
    try:
        conn.execute("SELECT COUNT(*) FROM entry_vec LIMIT 1")
        return True
    except sqlite3.OperationalError:
        return False


def _embed_query(query: str, config: EmbeddingConfig) -> list[float] | None:
    """Produce an embedding vector for *query*.

    Supports two provider families:
    * ``local`` -- uses ``sentence_transformers`` (must be installed).
    * ``openai`` / ``voyage`` -- uses the ``openai`` library with the
      appropriate base URL.

    Returns ``None`` if the provider cannot be loaded.
    """
    text = query[: config.max_characters]

    if config.provider == "local":
        return _embed_local(text, config.model)
    if config.provider in ("openai", "voyage"):
        return _embed_api(text, config)
    logger.warning("Unknown embedding provider: %s", config.provider)
    return None


def _embed_local(text: str, model_name: str) -> list[float] | None:
    """Embed using sentence-transformers (runs on CPU)."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "sentence-transformers is not installed; vector search disabled"
        )
        return None

    # Cache the model on the function object to avoid reloading.
    cache_attr = "_st_model_cache"
    cached: dict[str, Any] = getattr(_embed_local, cache_attr, {})
    if model_name not in cached:
        cached[model_name] = SentenceTransformer(model_name)
        setattr(_embed_local, cache_attr, cached)

    model = cached[model_name]
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()  # type: ignore[no-any-return]


def _embed_api(text: str, config: EmbeddingConfig) -> list[float] | None:
    """Embed using an OpenAI-compatible API (openai / voyage)."""
    try:
        import openai  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("openai package not installed; vector search disabled")
        return None

    api_key = config.api_key
    if not api_key:
        import os

        api_key = os.environ.get("ENGRAM_EMBEDDING_API_KEY", "")
    if not api_key:
        logger.warning("No API key for embedding provider %s", config.provider)
        return None

    base_url: str | None = None
    if config.provider == "voyage":
        base_url = "https://api.voyageai.com/v1"

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    try:
        resp = client.embeddings.create(model=config.model, input=[text])
        return resp.data[0].embedding
    except Exception:
        logger.exception("API embedding request failed")
        return None


def _vector_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    embedding_config: EmbeddingConfig,
    source_app: str | None,
) -> list[dict[str, Any]]:
    """Embed the query and search ``entry_vec`` for nearest neighbours."""
    vec = _embed_query(query, embedding_config)
    if vec is None:
        return []

    # sqlite-vec expects the query vector as a raw float32 blob.
    query_blob = struct.pack(f"{len(vec)}f", *vec)

    # entry_vec only stores (entry_id, embedding).  We JOIN back to entries
    # for metadata columns and optionally filter by source_app.
    where_extra = ""
    params: list[Any] = [query_blob, limit]
    if source_app:
        where_extra = "AND e.source_app = ?"
        params = [query_blob, limit + 50]  # fetch extra, filter in Python
        # We cannot push the source_app filter into the vec0 query itself
        # so we over-fetch and filter afterwards.

    sql = f"""
        SELECT
            v.entry_id,
            v.distance,
            e.session_key,
            e.source_app,
            e.role,
            e.text,
            e.timestamp,
            e.title        AS entry_title,
            e.source_path,
            s.title         AS session_title
        FROM entry_vec AS v
        JOIN entries  AS e ON e.entry_id = v.entry_id
        LEFT JOIN sessions AS s ON s.session_key = e.session_key
        WHERE v.embedding MATCH ?
          AND k = ?
          {where_extra}
    """

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("Vector search failed: %s", exc)
        return []

    # Post-filter by source_app if needed.
    if source_app:
        rows = [r for r in rows if r["source_app"] == source_app]

    results: list[dict[str, Any]] = []
    for rank_pos, row in enumerate(rows[:limit], start=1):
        results.append(
            {
                "entry_id": row["entry_id"],
                "session_key": row["session_key"],
                "source_app": row["source_app"],
                "role": row["role"],
                "text": row["text"],
                "timestamp": row["timestamp"],
                "entry_title": row["entry_title"],
                "session_title": row["session_title"],
                "source_path": row["source_path"],
                "distance": row["distance"],
                "vector_rank": rank_pos,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def _rrf_fuse(
    fts_results: list[dict[str, Any]],
    vec_results: list[dict[str, Any]],
    limit: int,
    rrf_k: int,
) -> list[dict[str, Any]]:
    """Merge FTS and vector results using Reciprocal Rank Fusion.

    For each unique ``entry_id`` that appears in either result set:

    * If in FTS results at rank *r_fts*:  ``score += 1 / (K + r_fts)``
    * If in vector results at rank *r_vec*:  ``score += 1 / (K + r_vec)``

    The combined results are sorted by RRF score descending.
    """
    combined: dict[str, dict[str, Any]] = {}

    # --- FTS contribution ------------------------------------------------
    for item in fts_results:
        eid = item["entry_id"]
        rank = item["fts_rank"]
        rrf_score = 1.0 / (rrf_k + rank)
        if eid not in combined:
            combined[eid] = {
                **item,
                "rrf_score": rrf_score,
                "fts_rank": rank,
                "vector_rank": None,
            }
        else:
            combined[eid]["rrf_score"] += rrf_score
            combined[eid]["fts_rank"] = rank

    # --- Vector contribution ---------------------------------------------
    for item in vec_results:
        eid = item["entry_id"]
        rank = item["vector_rank"]
        rrf_score = 1.0 / (rrf_k + rank)
        if eid not in combined:
            combined[eid] = {
                **item,
                "rrf_score": rrf_score,
                "fts_rank": None,
                "vector_rank": rank,
            }
        else:
            combined[eid]["rrf_score"] += rrf_score
            # Prefer FTS metadata if already present; fill vector rank.
            combined[eid]["vector_rank"] = rank

    # Sort by combined RRF score descending.
    fused = sorted(combined.values(), key=lambda d: d["rrf_score"], reverse=True)
    return fused[:limit]


# ---------------------------------------------------------------------------
# Time decay
# ---------------------------------------------------------------------------


def _apply_time_decay(
    results: list[dict[str, Any]],
    half_life_days: float,
) -> list[dict[str, Any]]:
    """Apply exponential time decay and re-sort by final score.

    ``final_score = rrf_score * time_decay_multiplier(timestamp, half_life)``
    """
    for item in results:
        dm = time_decay_multiplier(item.get("timestamp"), half_life_days)
        item["decay_multiplier"] = dm
        item["final_score"] = item.get("rrf_score", 0.0) * dm

    results.sort(key=lambda d: d["final_score"], reverse=True)
    return results


def time_decay_multiplier(
    timestamp_str: str | None,
    half_life_days: float,
) -> float:
    """Compute an exponential decay multiplier from an ISO 8601 timestamp.

    ``multiplier = 0.5 ^ (age_days / half_life_days)``

    Returns
    -------
    float
        A value clamped to ``[0.01, 1.0]``.  Returns ``0.5`` when
        *timestamp_str* is ``None`` or unparseable.
    """
    if timestamp_str is None:
        return 0.5
    if half_life_days <= 0:
        return 1.0

    try:
        ts = _parse_timestamp(timestamp_str)
    except (ValueError, TypeError):
        return 0.5

    now = datetime.now(timezone.utc)
    age_days = max((now - ts).total_seconds() / 86400.0, 0.0)
    multiplier = math.pow(0.5, age_days / half_life_days)
    return max(min(multiplier, 1.0), 0.01)


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp, tolerating common variations.

    Handles both timezone-aware (``Z``, ``+00:00``) and naive strings
    (assumed UTC).
    """
    ts = ts.strip()
    # Python's fromisoformat gained full ISO 8601 support in 3.11.
    # For earlier versions, normalise the trailing "Z".
    if ts.endswith("Z") or ts.endswith("z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# FTS5 query escaping
# ---------------------------------------------------------------------------


def safe_match_query(query: str) -> str:
    """Escape a user query into a safe FTS5 MATCH expression.

    * Strips FTS5 operators and special characters.
    * Wraps each token in double quotes so the trigram tokeniser can
      match it literally.
    * Joins tokens with implicit AND.
    * Handles CJK text by preserving character sequences as-is (the
      trigram tokeniser does not need whitespace word boundaries).
    """
    # Strip special FTS5 characters.
    cleaned = _FTS5_SPECIAL.sub(" ", query)

    # Collapse whitespace and split into tokens.
    tokens = cleaned.split()
    if not tokens:
        return ""

    # Wrap each token in double quotes for literal matching.
    # For the trigram tokeniser every 3-character sequence is indexed,
    # so quoting gives us substring matching for free.
    safe_parts: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        # Escape any embedded double-quotes (shouldn't happen after strip
        # but be defensive).
        tok = tok.replace('"', '""')
        safe_parts.append(f'"{tok}"')

    return " ".join(safe_parts)


# ---------------------------------------------------------------------------
# Snippet builder
# ---------------------------------------------------------------------------


def build_snippet(text: str, query: str, context_chars: int = 150) -> str:
    """Extract a snippet from *text* centred on the first query-term match.

    The snippet is at most ``2 * context_chars`` characters long (context on
    each side of the match).  If no match is found, the first
    ``context_chars`` characters of *text* are returned.
    """
    if not text:
        return ""

    # Build a combined pattern from individual query tokens.
    tokens = _FTS5_SPECIAL.sub(" ", query).split()
    tokens = [t.strip() for t in tokens if t.strip()]

    best_start: int | None = None
    best_end: int | None = None

    if tokens:
        # Try each token; keep the earliest match position.
        text_lower = text.lower()
        for tok in tokens:
            pos = text_lower.find(tok.lower())
            if pos != -1 and (best_start is None or pos < best_start):
                    best_start = pos
                    best_end = pos + len(tok)

    if best_start is not None and best_end is not None:
        snippet_start = max(best_start - context_chars, 0)
        snippet_end = min(best_end + context_chars, len(text))

        snippet = text[snippet_start:snippet_end]

        prefix = "..." if snippet_start > 0 else ""
        suffix = "..." if snippet_end < len(text) else ""
        return f"{prefix}{snippet}{suffix}"

    # Fallback: beginning of text.
    if len(text) <= context_chars:
        return text
    return text[:context_chars] + "..."


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------


def _filter_by_tags(
    conn: sqlite3.Connection,
    results: list[dict[str, Any]],
    tag_list: list[str],
) -> list[dict[str, Any]]:
    """Keep only results whose entry_id has at least one of the given tags."""
    if not results or not tag_list:
        return results

    entry_ids = [r["entry_id"] for r in results]
    placeholders = ",".join("?" * len(tag_list))
    id_placeholders = ",".join("?" * len(entry_ids))

    try:
        rows = conn.execute(
            f"SELECT DISTINCT entry_id FROM entry_tags "
            f"WHERE tag IN ({placeholders}) AND entry_id IN ({id_placeholders})",
            [*tag_list, *entry_ids],
        ).fetchall()
        matched = {row["entry_id"] for row in rows}
    except sqlite3.OperationalError:
        # entry_tags table may not exist yet
        return results

    return [r for r in results if r["entry_id"] in matched]


def _get_entry_tags(conn: sqlite3.Connection, entry_id: str) -> list[str]:
    """Fetch tags for a single entry. Returns empty list on error."""
    try:
        rows = conn.execute(
            "SELECT tag FROM entry_tags WHERE entry_id = ? ORDER BY tag",
            (entry_id,),
        ).fetchall()
        return [row["tag"] for row in rows]
    except sqlite3.OperationalError:
        return []
