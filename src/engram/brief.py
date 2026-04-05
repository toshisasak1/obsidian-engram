"""Session brief generation - creates context summaries for AI session startup.

Generates a structured payload of recent sessions and keyword matches
relevant to the current workspace, then renders it as Markdown for
injection into AI tool context windows.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories that are too generic to be useful workspace identifiers.
_SKIP_COMPONENTS = frozenset({
    "users", "home", "toshi", "dropbox", "obsidian", "mnt",
    "documents", "desktop", "projects", "src", "c:", "d:", "e:",
    "volumes", "var", "tmp", "opt", "usr", "lib",
})

_SNIPPET_MAX = 300


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def workspace_terms(path: Path) -> list[str]:
    """Extract meaningful path components for workspace matching.

    Walks the path from deepest to shallowest, skipping common/generic
    directory names, and returns up to 3 of the deepest meaningful parts.

    Parameters
    ----------
    path:
        Absolute or relative filesystem path (e.g. a project directory).

    Returns
    -------
    list[str]
        2-3 lowercase path component strings, deepest first.
    """
    parts = [p for p in path.parts if p.lower().rstrip("/\\") not in _SKIP_COMPONENTS]
    # Take the deepest 3 (rightmost), reversed so deepest is first.
    selected = parts[-3:] if len(parts) >= 3 else parts
    selected.reverse()
    return [p.lower() for p in selected]


def session_matches_workspace(
    session: dict,
    workspace: Path,
    terms: list[str],
) -> bool:
    """Test whether *session* is relevant to *workspace*.

    A session matches if:
    - Its ``cwd``, ``project``, or ``source_path`` is a child of (or equal
      to) *workspace*  (path containment check).
    - OR any of the *terms* appear in the session's ``title``, ``project``,
      or ``source_path``  (keyword check).

    Parameters
    ----------
    session:
        A dict with keys ``cwd``, ``project``, ``source_path``, ``title``
        (as returned by an ``sqlite3.Row`` cast to dict).
    workspace:
        The workspace directory to match against.
    terms:
        Output of :func:`workspace_terms`.
    """
    ws_str = workspace.as_posix().lower()

    # Path containment: session field starts with the workspace path.
    for field in ("cwd", "project", "source_path"):
        val = session.get(field)
        if not val:
            continue
        normalised = val.replace("\\", "/").lower()
        if normalised.startswith(ws_str) or ws_str.startswith(normalised):
            return True

    # Keyword match: any workspace term appears in textual fields.
    if terms:
        haystack = (session.get("title") or "").lower()
        # Also fold in project and source_path for keyword matching.
        for field in ("project", "source_path"):
            val = session.get(field)
            if val:
                haystack += " " + val.replace("\\", "/").lower()

        for term in terms:
            if term in haystack:
                return True

    return False


def generate_brief(
    conn: sqlite3.Connection,
    workspace: Path | None = None,
    queries: list[str] | None = None,
    session_limit: int = 5,
    entries_per_session: int = 2,
    query_limit: int = 5,
) -> dict:
    """Build a context-brief payload from the database.

    Parameters
    ----------
    conn:
        An open SQLite connection (from :func:`engram.db.connect`).
    workspace:
        Working directory to filter sessions by.  When ``None``, the most
        recent sessions are returned without filtering.
    queries:
        Optional free-text search terms to look up in the FTS index.
    session_limit:
        Maximum number of sessions to include.
    entries_per_session:
        Number of highlight entries per session.
    query_limit:
        Maximum matches per query term.

    Returns
    -------
    dict
        A JSON-serialisable payload with ``generated_at``, ``workspace``,
        ``sessions``, and ``query_matches`` keys.
    """
    now = datetime.now(timezone.utc).isoformat()
    ws_path = Path(workspace) if workspace else None
    terms = workspace_terms(ws_path) if ws_path else []

    # ------------------------------------------------------------------
    # 1. Fetch recent sessions
    # ------------------------------------------------------------------
    rows = conn.execute(
        "SELECT session_key, source_app, title, updated_at, cwd, project, source_path "
        "FROM sessions ORDER BY updated_at DESC LIMIT 200"
    ).fetchall()

    matched_sessions: list[dict] = []
    for row in rows:
        s = dict(row)
        if ws_path is None or session_matches_workspace(s, ws_path, terms):
            matched_sessions.append(s)
        if len(matched_sessions) >= session_limit:
            break

    # ------------------------------------------------------------------
    # 2. For each matched session, fetch highlight entries
    # ------------------------------------------------------------------
    session_payloads: list[dict] = []
    for s in matched_sessions:
        highlights = _fetch_highlights(conn, s["session_key"], entries_per_session)
        session_payloads.append({
            "session_key": s["session_key"],
            "source_app": s["source_app"],
            "title": s["title"],
            "updated_at": s["updated_at"],
            "cwd": s.get("cwd"),
            "highlights": highlights,
        })

    # ------------------------------------------------------------------
    # 3. FTS keyword matches
    # ------------------------------------------------------------------
    all_queries = list(queries or [])
    # Also search for workspace terms as additional queries.
    for t in terms:
        if t not in all_queries:
            all_queries.append(t)

    query_matches: list[dict] = []
    for q in all_queries:
        matches = _fts_search(conn, q, query_limit)
        for m in matches:
            m["query"] = q
        query_matches.extend(matches)

    return {
        "generated_at": now,
        "workspace": str(ws_path) if ws_path else None,
        "sessions": session_payloads,
        "query_matches": query_matches,
    }


def render_brief(payload: dict) -> str:
    """Render a brief payload dict as a Markdown document.

    Parameters
    ----------
    payload:
        The dict returned by :func:`generate_brief`.

    Returns
    -------
    str
        A human-readable Markdown string.
    """
    lines: list[str] = []
    lines.append("# Session Memory Brief")
    lines.append("")
    lines.append(f"Generated: {payload.get('generated_at', 'unknown')}")
    if payload.get("workspace"):
        lines.append(f"Workspace: {payload['workspace']}")
    lines.append("")

    # -- Recent Sessions ------------------------------------------------
    sessions = payload.get("sessions", [])
    if sessions:
        lines.append("## Recent Sessions")
        lines.append("")
        for s in sessions:
            source = s.get("source_app", "unknown")
            title = s.get("title") or "(untitled)"
            lines.append(f"### [{source}] {title}")
            lines.append(f"- Session: {s.get('session_key', 'n/a')}")
            if s.get("updated_at"):
                lines.append(f"- Updated: {s['updated_at']}")
            if s.get("cwd"):
                lines.append(f"- CWD: {s['cwd']}")
            lines.append("")

            for h in s.get("highlights", []):
                snippet = h.get("snippet", "").strip()
                if snippet:
                    # Indent blockquote lines
                    quoted = "\n".join(f"> {line}" for line in snippet.split("\n"))
                    lines.append(quoted)
                    lines.append("")
    else:
        lines.append("## Recent Sessions")
        lines.append("")
        lines.append("_No matching sessions found._")
        lines.append("")

    # -- Keyword Matches ------------------------------------------------
    query_matches = payload.get("query_matches", [])
    if query_matches:
        lines.append("## Keyword Matches")
        lines.append("")

        # Group by query
        by_query: dict[str, list[dict]] = {}
        for m in query_matches:
            q = m.get("query", "")
            by_query.setdefault(q, []).append(m)

        for query, matches in by_query.items():
            lines.append(f"**{query}**:")
            for m in matches:
                source = m.get("source_app", "")
                sk = m.get("session_key", "")
                snippet = m.get("snippet", "").strip()
                score_str = f" (score: {m['score']:.3f})" if m.get("score") else ""
                lines.append(f"- [{source}] {sk}: {snippet}{score_str}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int = _SNIPPET_MAX) -> str:
    """Truncate *text* to *max_len* characters with ellipsis."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


def _fetch_highlights(
    conn: sqlite3.Connection,
    session_key: str,
    limit: int,
) -> list[dict]:
    """Return the first *limit* entries for a session as highlight dicts."""
    rows = conn.execute(
        "SELECT source_app, role, timestamp, text "
        "FROM entries "
        "WHERE session_key = ? "
        "ORDER BY ordinal ASC "
        "LIMIT ?",
        (session_key, limit),
    ).fetchall()

    return [
        {
            "source_app": row["source_app"],
            "role": row["role"],
            "timestamp": row["timestamp"],
            "snippet": _truncate(row["text"]),
        }
        for row in rows
    ]


def _fts_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
) -> list[dict]:
    """Run a single FTS5 match query, returning scored result dicts.

    Fails gracefully if the FTS table does not exist (returns []).
    """
    # Escape double-quotes in the query to prevent FTS5 syntax errors.
    safe_query = query.replace('"', '""')

    try:
        rows = conn.execute(
            """
            SELECT
                e.entry_id,
                e.session_key,
                e.source_app,
                e.text,
                f.rank AS score
            FROM entries_fts f
            JOIN entries e ON e.rowid = f.rowid
            WHERE entries_fts MATCH ?
            ORDER BY f.rank
            LIMIT ?
            """,
            (f'"{safe_query}"', limit),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.debug("FTS search failed for %r: %s", query, exc)
        return []

    return [
        {
            "entry_id": row["entry_id"],
            "session_key": row["session_key"],
            "source_app": row["source_app"],
            "snippet": _truncate(row["text"]),
            "score": float(row["score"]) if row["score"] is not None else 0.0,
        }
        for row in rows
    ]
