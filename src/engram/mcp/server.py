"""MCP server for Engram -- exposes memory tools over JSON-RPC 2.0 / stdio.

Protocol: MCP 2024-11-05 (JSON-RPC 2.0 with Content-Length framing).

The server reads requests from stdin and writes responses to stdout.
All diagnostic logging goes to stderr so it never contaminates the
transport channel.

Usage::

    from engram.config import load_config
    from engram.mcp.server import serve

    serve(load_config(vault_path=...))
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

from engram.config import EngramConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (exposed via ``tools/list``)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "memory_search",
        "description": (
            "Search across all indexed AI conversation history and vault "
            "documents. Returns relevant snippets with source, score, and "
            "timestamp."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (keywords or natural language)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 10,
                },
                "source_app": {
                    "type": "string",
                    "description": (
                        "Filter by source: claude, codex, gemini, vault"
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_brief",
        "description": (
            "Generate a context brief for the current workspace. Returns "
            "recent sessions and keyword matches relevant to the working "
            "directory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": (
                        "Workspace path (defaults to current directory)"
                    ),
                },
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional search terms",
                },
            },
        },
    },
    {
        "name": "memory_status",
        "description": (
            "Show knowledge base statistics: session count, entry count, "
            "embeddings, by source app."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_list_sessions",
        "description": (
            "List recent conversation sessions with titles and timestamps."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum sessions to return",
                },
                "source_app": {
                    "type": "string",
                    "description": "Filter by source app",
                },
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Server metadata
# ---------------------------------------------------------------------------

_SERVER_INFO: dict[str, Any] = {
    "name": "engram",
    "version": "0.1.0",
}

_CAPABILITIES: dict[str, Any] = {
    "tools": {},
}

# ---------------------------------------------------------------------------
# Low-level stdio transport (Content-Length framing)
# ---------------------------------------------------------------------------


def _read_message() -> dict[str, Any] | None:
    """Read one JSON-RPC message from stdin using Content-Length framing.

    Returns ``None`` on EOF or malformed input.
    """
    # Read headers until blank line.
    content_length: int | None = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None  # EOF
        line_str = line.decode("utf-8", errors="replace").rstrip("\r\n")
        if line_str == "":
            break  # End of headers
        if line_str.lower().startswith("content-length:"):
            try:
                content_length = int(line_str.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                logger.warning("Malformed Content-Length header: %s", line_str)
                return None

    if content_length is None:
        logger.warning("Missing Content-Length header")
        return None

    body = sys.stdin.buffer.read(content_length)
    if len(body) < content_length:
        logger.warning(
            "Truncated body: expected %d bytes, got %d",
            content_length,
            len(body),
        )
        return None

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON in message body: %s", exc)
        return None


def _write_message(msg: dict[str, Any]) -> None:
    """Write one JSON-RPC message to stdout with Content-Length framing."""
    body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n"
    sys.stdout.buffer.write(header.encode("utf-8"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _result_response(id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _error_response(
    id: Any,
    code: int,
    message: str,
    data: Any = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": error}


# Standard JSON-RPC error codes.
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _handle_memory_search(
    conn: sqlite3.Connection,
    config: EngramConfig,
    args: dict[str, Any],
) -> list[dict[str, Any]]:
    """Execute memory_search and return a list of content items."""
    from engram.search import search

    query = args.get("query", "")
    limit = args.get("limit", 10)
    source_app = args.get("source_app")

    results = search(
        conn,
        query=query,
        config=config.search,
        embedding_config=config.embedding if config.embedding.enabled else None,
        limit=limit,
        source_app=source_app,
    )

    lines: list[str] = []
    if not results:
        lines.append("No results found.")
    else:
        for i, r in enumerate(results, 1):
            title = r.session_title or r.entry_title or ""
            lines.append(
                f"### {i}. [{r.source_app}] {title}"
            )
            lines.append(f"- Score: {r.score:.3f}")
            if r.timestamp:
                lines.append(f"- Time: {r.timestamp}")
            lines.append(f"- Session: {r.session_key}")
            lines.append("")
            lines.append(r.snippet)
            lines.append("")

    return [{"type": "text", "text": "\n".join(lines)}]


def _handle_memory_brief(
    conn: sqlite3.Connection,
    config: EngramConfig,
    args: dict[str, Any],
) -> list[dict[str, Any]]:
    """Execute memory_brief and return rendered markdown."""
    from engram.brief import generate_brief, render_brief

    workspace_str = args.get("workspace")
    workspace = Path(workspace_str) if workspace_str else None
    queries = args.get("queries")

    payload = generate_brief(conn, workspace=workspace, queries=queries)
    markdown = render_brief(payload)

    return [{"type": "text", "text": markdown}]


def _handle_memory_status(
    conn: sqlite3.Connection,
    config: EngramConfig,
    args: dict[str, Any],
) -> list[dict[str, Any]]:
    """Execute memory_status and return stats as formatted text."""
    from engram.db import get_stats

    stats = get_stats(conn)

    # Add per-source session counts.
    try:
        rows = conn.execute(
            "SELECT source_app, COUNT(*) AS cnt "
            "FROM sessions GROUP BY source_app"
        ).fetchall()
        stats["sources"] = {row["source_app"]: row["cnt"] for row in rows}
    except sqlite3.OperationalError:
        stats["sources"] = {}

    stats["db_path"] = str(config.db_path)
    stats["vault_path"] = str(config.vault_path) if config.vault_path else None

    text = json.dumps(stats, indent=2, ensure_ascii=False)
    return [{"type": "text", "text": text}]


def _handle_memory_list_sessions(
    conn: sqlite3.Connection,
    config: EngramConfig,
    args: dict[str, Any],
) -> list[dict[str, Any]]:
    """Execute memory_list_sessions and return a formatted list."""
    limit = args.get("limit", 20)
    source_app = args.get("source_app")

    where_clause = ""
    params: list[Any] = []
    if source_app:
        where_clause = "WHERE source_app = ?"
        params.append(source_app)
    params.append(limit)

    rows = conn.execute(
        f"SELECT session_key, source_app, title, updated_at, cwd "
        f"FROM sessions {where_clause} "
        f"ORDER BY updated_at DESC LIMIT ?",
        params,
    ).fetchall()

    if not rows:
        return [{"type": "text", "text": "No sessions found."}]

    lines: list[str] = []
    for row in rows:
        title = row["title"] or "(untitled)"
        updated = row["updated_at"] or "unknown"
        source = row["source_app"] or "unknown"
        cwd = row["cwd"] or ""
        lines.append(f"- **[{source}]** {title}")
        lines.append(f"  - Updated: {updated}")
        if cwd:
            lines.append(f"  - CWD: {cwd}")
        lines.append(f"  - Key: {row['session_key']}")

    return [{"type": "text", "text": "\n".join(lines)}]


# Dispatch table mapping tool name -> handler function.
_TOOL_HANDLERS: dict[str, Any] = {
    "memory_search": _handle_memory_search,
    "memory_brief": _handle_memory_brief,
    "memory_status": _handle_memory_status,
    "memory_list_sessions": _handle_memory_list_sessions,
}

# ---------------------------------------------------------------------------
# Method routing
# ---------------------------------------------------------------------------


def _handle_request(
    msg: dict[str, Any],
    conn: sqlite3.Connection,
    config: EngramConfig,
) -> dict[str, Any] | None:
    """Route a JSON-RPC request to the appropriate handler.

    Returns a response dict, or ``None`` for notifications (no ``id``).
    """
    msg_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params", {})

    # -- Lifecycle methods --------------------------------------------------

    if method == "initialize":
        return _result_response(msg_id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": _SERVER_INFO,
            "capabilities": _CAPABILITIES,
        })

    if method == "notifications/initialized":
        # Client acknowledgement -- nothing to do.
        return None

    if method == "ping":
        return _result_response(msg_id, {})

    # -- Tool methods -------------------------------------------------------

    if method == "tools/list":
        return _result_response(msg_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler = _TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return _error_response(
                msg_id,
                _INVALID_PARAMS,
                f"Unknown tool: {tool_name}",
            )

        try:
            content = handler(conn, config, arguments)
            return _result_response(msg_id, {
                "content": content,
                "isError": False,
            })
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return _result_response(msg_id, {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            })

    # -- Unknown method -----------------------------------------------------

    if msg_id is not None:
        return _error_response(
            msg_id,
            _METHOD_NOT_FOUND,
            f"Method not found: {method}",
        )

    # Unknown notification -- silently ignore.
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def serve(config: EngramConfig) -> None:
    """Run the MCP server on stdio.

    Blocks until stdin is closed (EOF).  All logging is directed to stderr.

    Parameters
    ----------
    config:
        A fully resolved :class:`~engram.config.EngramConfig` instance.
    """
    from engram.db import connect, ensure_schema

    logger.info("Engram MCP server starting (pid=%d)", __import__("os").getpid())

    conn = connect(config.db_path)
    ensure_schema(conn)

    try:
        while True:
            msg = _read_message()
            if msg is None:
                logger.info("EOF on stdin -- shutting down")
                break

            logger.debug("Received: %s", msg.get("method", "?"))

            response = _handle_request(msg, conn, config)
            if response is not None:
                _write_message(response)
    except KeyboardInterrupt:
        logger.info("Interrupted -- shutting down")
    except Exception:
        logger.exception("Fatal error in MCP server loop")
    finally:
        conn.close()
        logger.info("Engram MCP server stopped")
