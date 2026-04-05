"""Parser for Claude Code JSONL conversation logs.

Handles files at ``~/.claude/projects/{hash}/{uuid}.jsonl``.
Each line is a JSON object with fields like *type*, *message*,
*sessionId*, *cwd*, *gitBranch*, *timestamp*, and *uuid*.
"""

from __future__ import annotations

import json
import logging
import platform
import uuid
from collections.abc import Iterable
from pathlib import Path

from engram.models import EntryRecord, SessionRecord
from engram.parsers.base import (
    BaseParser,
    build_qa_entries,
    normalize_text,
    truncate,
)

logger = logging.getLogger(__name__)

_SKIP_TYPES = frozenset({"progress", "file-history-snapshot", "bash_progress"})


def _extract_text(content: str | list | None) -> str:
    """Extract plain text from a Claude message content field.

    *content* can be a plain string or a list of blocks such as
    ``[{"type": "text", "text": "..."}, ...]``.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


class ClaudeParser(BaseParser):
    """Parse Claude Code ``*.jsonl`` conversation logs."""

    name = "claude"

    # ---- discovery --------------------------------------------------------

    def discover_paths(self, root: Path) -> Iterable[Path]:
        """Yield ``.jsonl`` files under *root*, skipping ``subagents/``."""
        for p in sorted(root.rglob("*.jsonl")):
            if "subagents" in p.parts:
                continue
            yield p

    def default_root(self) -> Path | None:
        if platform.system() == "Windows":
            return Path.home() / ".claude" / "projects"
        return Path.home() / ".claude" / "projects"

    # ---- parsing ----------------------------------------------------------

    def parse(self, path: Path) -> tuple[SessionRecord, list[EntryRecord]]:
        raw_entries: list[dict] = []
        first_meta: dict = {}

        with path.open(encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "claude: skipping malformed JSON at %s:%d", path, lineno
                    )
                    continue

                msg_type = obj.get("type", "")
                if msg_type in _SKIP_TYPES:
                    continue

                message = obj.get("message")
                if not isinstance(message, dict):
                    continue

                role = message.get("role")
                if role not in ("user", "assistant"):
                    continue

                text = _extract_text(message.get("content"))
                text = normalize_text(text)
                if not text:
                    continue

                if not first_meta:
                    first_meta = {
                        "session_id": obj.get("sessionId", ""),
                        "cwd": obj.get("cwd"),
                        "git_branch": obj.get("gitBranch"),
                        "timestamp": obj.get("timestamp"),
                    }

                raw_entries.append(
                    {
                        "role": role,
                        "text": text,
                        "timestamp": obj.get("timestamp"),
                        "uuid": obj.get("uuid", ""),
                    }
                )

        # -- Build SessionRecord --------------------------------------------
        external_id = first_meta.get("session_id") or path.stem
        session_key = f"claude:{external_id}"
        first_ts = first_meta.get("timestamp")
        last_ts = raw_entries[-1]["timestamp"] if raw_entries else first_ts

        # Derive a title from the first user message
        first_user = next(
            (e["text"] for e in raw_entries if e["role"] == "user"), ""
        )
        title = truncate(first_user, 120) or path.stem

        session = SessionRecord(
            session_key=session_key,
            source_app="claude",
            source_path=str(path),
            external_id=external_id,
            title=title,
            cwd=first_meta.get("cwd"),
            project=first_meta.get("cwd"),
            started_at=first_ts,
            updated_at=last_ts,
            metadata={
                k: v
                for k, v in {
                    "git_branch": first_meta.get("git_branch"),
                }.items()
                if v is not None
            },
        )

        # -- Build raw EntryRecords -----------------------------------------
        entries: list[EntryRecord] = []
        for idx, raw in enumerate(raw_entries):
            entries.append(
                EntryRecord(
                    entry_id=raw["uuid"] or str(uuid.uuid4()),
                    session_key=session_key,
                    source_app="claude",
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
