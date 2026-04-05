"""Parser for Codex CLI JSONL history and session files.

Handles:
- ``~/.codex/history.jsonl``  (one line per user input)
- ``~/.codex/sessions/{id}.jsonl``  (full session transcripts)
"""

from __future__ import annotations

import json
import logging
import platform
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from engram.models import EntryRecord, SessionRecord
from engram.parsers.base import (
    BaseParser,
    build_qa_entries,
    normalize_text,
    truncate,
)

logger = logging.getLogger(__name__)


def _ts_to_iso(ts: float | int | str | None) -> str | None:
    """Convert a Unix timestamp (seconds) to ISO 8601, or return None."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _extract_text_from_content(content: list | str | None) -> str:
    """Extract plain text from a Codex content array or string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") in ("text", "input_text", "output_text"):
                    parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


class CodexParser(BaseParser):
    """Parse Codex CLI JSONL files."""

    name = "codex"

    # ---- discovery --------------------------------------------------------

    def discover_paths(self, root: Path) -> Iterable[Path]:
        """Yield ``history.jsonl`` and session JSONL files under *root*."""
        history = root / "history.jsonl"
        if history.is_file():
            yield history

        sessions_dir = root / "sessions"
        if sessions_dir.is_dir():
            yield from sorted(sessions_dir.rglob("*.jsonl"))

    def default_root(self) -> Path | None:
        if platform.system() == "Windows":
            return Path.home() / ".codex"
        return Path.home() / ".codex"

    # ---- parsing ----------------------------------------------------------

    def parse(self, path: Path) -> tuple[SessionRecord, list[EntryRecord]]:
        if path.name == "history.jsonl":
            return self._parse_history(path)
        return self._parse_session(path)

    # -- history.jsonl ------------------------------------------------------

    def _parse_history(
        self, path: Path
    ) -> tuple[SessionRecord, list[EntryRecord]]:
        """Parse the global history file.

        Each line has ``session_id``, ``ts`` (unix seconds), ``text``.
        Lines are grouped by ``session_id`` and only user inputs are
        present, so we create simple message entries (no QA pairing).
        """
        groups: dict[str, list[dict]] = defaultdict(list)

        with path.open(encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "codex: skipping malformed JSON at %s:%d", path, lineno
                    )
                    continue
                sid = obj.get("session_id", "unknown")
                groups[sid].append(obj)

        # Pick the first session group (or synthesize one)
        if not groups:
            sid = path.stem
            session = SessionRecord(
                session_key=f"codex:{sid}",
                source_app="codex",
                source_path=str(path),
                external_id=sid,
                title=path.name,
            )
            return session, []

        # If the history file contains multiple sessions we still return
        # one SessionRecord per file call.  Use the first session.
        sid = next(iter(groups))
        items = groups[sid]

        first_ts = _ts_to_iso(items[0].get("ts")) if items else None
        last_ts = _ts_to_iso(items[-1].get("ts")) if items else first_ts
        first_text = normalize_text(items[0].get("text", "")) if items else ""

        session = SessionRecord(
            session_key=f"codex:{sid}",
            source_app="codex",
            source_path=str(path),
            external_id=sid,
            title=truncate(first_text, 120) or path.name,
            started_at=first_ts,
            updated_at=last_ts,
            metadata={"history_sessions": list(groups.keys())},
        )

        entries: list[EntryRecord] = []
        for idx, item in enumerate(items):
            text = normalize_text(item.get("text", ""))
            if not text:
                continue
            entries.append(
                EntryRecord(
                    entry_id=str(uuid.uuid4()),
                    session_key=session.session_key,
                    source_app="codex",
                    source_kind="message",
                    source_path=str(path),
                    ordinal=idx,
                    role="user",
                    text=text,
                    timestamp=_ts_to_iso(item.get("ts")),
                    title=truncate(text, 120),
                    metadata={},
                )
            )

        return session, entries

    # -- session files ------------------------------------------------------

    def _parse_session(
        self, path: Path
    ) -> tuple[SessionRecord, list[EntryRecord]]:
        """Parse a single session JSONL file from ``sessions/``."""
        raw_entries: list[dict] = []
        session_meta: dict = {}

        with path.open(encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "codex: skipping malformed JSON at %s:%d", path, lineno
                    )
                    continue

                obj_type = obj.get("type", "")

                if obj_type == "session_meta":
                    session_meta = obj
                    continue

                if obj_type == "response_item":
                    role = obj.get("role", "assistant")
                    text = _extract_text_from_content(obj.get("content"))
                    text = normalize_text(text)
                    if text:
                        raw_entries.append(
                            {
                                "role": role,
                                "text": text,
                                "timestamp": _ts_to_iso(obj.get("ts")),
                                "id": obj.get("id", ""),
                            }
                        )
                    continue

                if obj_type == "event_msg":
                    text = normalize_text(obj.get("text", ""))
                    role = obj.get("role", "user")
                    if text:
                        raw_entries.append(
                            {
                                "role": role,
                                "text": text,
                                "timestamp": _ts_to_iso(obj.get("ts")),
                                "id": obj.get("id", ""),
                            }
                        )

        # -- Build SessionRecord --------------------------------------------
        external_id = session_meta.get("session_id", "") or path.stem
        session_key = f"codex:{external_id}"

        first_ts = raw_entries[0]["timestamp"] if raw_entries else None
        last_ts = raw_entries[-1]["timestamp"] if raw_entries else first_ts

        first_user = next(
            (e["text"] for e in raw_entries if e["role"] == "user"), ""
        )
        title = truncate(first_user, 120) or path.stem

        session = SessionRecord(
            session_key=session_key,
            source_app="codex",
            source_path=str(path),
            external_id=external_id,
            title=title,
            cwd=session_meta.get("cwd"),
            project=session_meta.get("cwd"),
            started_at=first_ts,
            updated_at=last_ts,
            metadata={
                k: v
                for k, v in session_meta.items()
                if k not in ("type", "session_id", "cwd")
                and v is not None
            },
        )

        # -- Build raw EntryRecords -----------------------------------------
        entries: list[EntryRecord] = []
        for idx, raw in enumerate(raw_entries):
            entries.append(
                EntryRecord(
                    entry_id=raw["id"] or str(uuid.uuid4()),
                    session_key=session_key,
                    source_app="codex",
                    source_kind="message",
                    source_path=str(path),
                    ordinal=idx,
                    role=raw["role"],
                    text=raw["text"],
                    timestamp=raw["timestamp"],
                    title=truncate(raw["text"], 120),
                    metadata={},
                )
            )

        qa_entries = build_qa_entries(session, entries)
        return session, qa_entries
