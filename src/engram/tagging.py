"""Auto-tagging engine for Engram entries.

Supports two backends:

* **keyword** -- zero-dependency rule-based tagging (source, role, path
  patterns, and configurable keyword rules).
* **cli** -- high-quality tagging via ``claude -p`` or ``codex`` CLI
  (uses existing OAuth subscription, no extra API cost).

The ``TagEngine`` orchestrator reads from the database, applies the
selected backend(s), and writes tags back.  It can be invoked from
the CLI (``engram tag``) or MCP (``memory_tag``).
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from engram.config import EngramConfig, TaggingConfig
from engram.db import connect, ensure_schema, get_untagged_entry_ids, upsert_tags
from engram.models import TagStats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in keyword patterns (language / framework detection)
# ---------------------------------------------------------------------------

_BUILTIN_RULES: dict[str, list[str]] = {
    "python": ["python", "pip", "venv", "pytest", "django", "flask", "fastapi"],
    "javascript": ["javascript", "node", "npm", "react", "vue", "typescript"],
    "rust": ["rust", "cargo", "tokio", "serde"],
    "go": ["golang", "goroutine"],
    "sql": ["sqlite", "postgres", "mysql", "database", "sql"],
    "docker": ["docker", "container", "dockerfile", "compose"],
    "git": ["git", "commit", "branch", "merge", "rebase"],
    "api": ["api", "rest", "graphql", "endpoint", "webhook"],
    "testing": ["test", "unittest", "pytest", "jest", "spec"],
    "devops": ["ci", "cd", "pipeline", "deploy", "kubernetes"],
}


# ---------------------------------------------------------------------------
# KeywordTagger
# ---------------------------------------------------------------------------


class KeywordTagger:
    """Zero-dependency rule-based tagger.

    Extracts tags from:
    1. ``source_app`` (claude, codex, gemini, vault)
    2. ``role`` (user, assistant, qa, document)
    3. Path components (project name from source_path)
    4. Custom rules from config
    5. Built-in language/framework keyword patterns
    """

    def __init__(self, config: TaggingConfig) -> None:
        self.max_tags = config.max_tags
        # Merge built-in + custom rules
        self.rules: dict[str, list[str]] = {**_BUILTIN_RULES}
        for tag_name, keywords in config.custom_rules.items():
            self.rules[tag_name] = [k.lower() for k in keywords]

    def tag(
        self,
        text: str,
        source_app: str,
        role: str,
        source_path: str,
    ) -> list[str]:
        """Generate tags for a single entry. Returns deduplicated list."""
        tags: list[str] = []

        # 1. Source app
        if source_app:
            tags.append(source_app.lower())

        # 2. Role
        if role and role not in ("qa",):
            tags.append(role.lower())

        # 3. Path-based project name
        project = _extract_project_from_path(source_path)
        if project:
            tags.append(project.lower())

        # 4. Keyword rule matching
        text_lower = text.lower()
        for tag_name, keywords in self.rules.items():
            if tag_name in tags:
                continue
            for kw in keywords:
                # Word boundary match to avoid false positives
                if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                    tags.append(tag_name)
                    break

        # Deduplicate while preserving order, limit count
        seen: set[str] = set()
        unique: list[str] = []
        for t in tags:
            t = t.strip().lower()
            if t and t not in seen:
                seen.add(t)
                unique.append(t)
        return unique[: self.max_tags]


def _extract_project_from_path(source_path: str) -> str:
    """Extract a project name from a source file path.

    Heuristic: find the last meaningful directory component that isn't
    a well-known system directory.
    """
    if not source_path:
        return ""

    _SKIP = {
        "projects", "sessions", "brain", ".claude", ".codex", ".gemini",
        "antigravity", "home", "users", "mnt", "tmp",
    }

    # Handle both Windows and POSIX paths
    try:
        parts = PureWindowsPath(source_path).parts
    except Exception:
        parts = PurePosixPath(source_path).parts

    # Walk from the end, find the first non-system directory
    for part in reversed(parts):
        # Skip file names (with extensions) and system dirs
        if "." in part and part != ".engram":
            continue
        low = part.lower()
        if low in _SKIP or len(low) <= 1:
            continue
        return low

    return ""


# ---------------------------------------------------------------------------
# CliTagger
# ---------------------------------------------------------------------------


class CliTagger:
    """Tag entries via CLI tool (claude -p / codex) using account subscription.

    Batches entries together for efficiency.  Falls back gracefully on
    timeout, missing CLI, or parse errors.
    """

    def __init__(self, config: TaggingConfig) -> None:
        self.command = config.cli_command
        self.timeout = config.cli_timeout
        self.max_tags = config.max_tags

    def tag_batch(
        self,
        entries: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        """Tag a batch of entries via CLI. Returns {entry_id: [tags]}.

        Each entry dict must have ``entry_id`` and ``text`` keys.
        """
        if not entries:
            return {}

        # Build the prompt
        prompt = self._build_prompt(entries)

        # Execute CLI
        try:
            result = self._run_cli(prompt)
        except Exception as exc:
            logger.warning("CLI tagger failed: %s", exc)
            return {}

        # Parse response
        return self._parse_response(result, entries)

    def _build_prompt(self, entries: list[dict[str, Any]]) -> str:
        """Build the tagging prompt for the CLI tool."""
        entry_texts: list[str] = []
        for e in entries:
            # Truncate long entries
            text = e["text"][:500]
            entry_texts.append(f"[{e['entry_id']}]\n{text}")

        batch_text = "\n\n---\n\n".join(entry_texts)

        return (
            "You are a tagging assistant. For each entry below, generate "
            f"up to {self.max_tags} lowercase, single-word or hyphenated tags. "
            "Return ONLY a JSON object mapping entry_id to a list of tags. "
            "Example: {\"id1\": [\"python\", \"api\"], \"id2\": [\"docker\"]}.\n\n"
            f"Entries:\n\n{batch_text}"
        )

    def _run_cli(self, prompt: str) -> str:
        """Execute the CLI tool and return stdout."""
        if self.command == "claude":
            cmd = ["claude", "-p", prompt]
        elif self.command == "codex":
            cmd = ["codex", "-q", prompt]
        else:
            raise ValueError(f"Unknown CLI command: {self.command}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )

        if result.returncode != 0:
            logger.warning(
                "CLI tagger returned %d: %s",
                result.returncode,
                result.stderr[:200],
            )
            return ""

        return result.stdout

    def _parse_response(
        self,
        response: str,
        entries: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        """Parse JSON response from CLI tool."""
        if not response.strip():
            return {}

        # Try to find JSON in the response (may have surrounding text)
        json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
        if not json_match:
            # Try multiline JSON
            json_match = re.search(r"\{.*\}", response, re.DOTALL)

        if not json_match:
            logger.warning("No JSON found in CLI response")
            return {}

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse CLI response JSON: %s", exc)
            return {}

        # Validate and clean
        result: dict[str, list[str]] = {}
        valid_ids = {e["entry_id"] for e in entries}

        for entry_id, tags in data.items():
            if entry_id not in valid_ids:
                continue
            if not isinstance(tags, list):
                continue
            cleaned = [
                t.lower().strip()
                for t in tags
                if isinstance(t, str) and t.strip()
            ]
            result[entry_id] = cleaned[: self.max_tags]

        return result


# ---------------------------------------------------------------------------
# TagEngine (orchestrator)
# ---------------------------------------------------------------------------


class TagEngine:
    """Orchestrates tagging across configured backends.

    Opens its own database connection (like ``SyncEngine``).
    """

    def __init__(self, config: EngramConfig) -> None:
        self.config = config
        self.db_path = config.db_path

    def tag_untagged(
        self,
        *,
        provider: str | None = None,
        batch_size: int | None = None,
    ) -> TagStats:
        """Tag entries that don't have tags yet.

        Parameters
        ----------
        provider:
            Override the configured provider ("keyword", "cli", "both").
        batch_size:
            Override the configured batch size.
        """
        stats = TagStats()
        prov = provider or self.config.tagging.provider
        bs = batch_size or self.config.tagging.batch_size

        conn = connect(self.db_path)
        try:
            ensure_schema(conn)

            if prov in ("keyword", "both"):
                self._tag_keyword(conn, bs, stats)

            if prov in ("cli", "both"):
                self._tag_cli(conn, bs, stats)

        except Exception:
            logger.exception("Tagging pass failed")
            stats.errors += 1
        finally:
            conn.close()

        return stats

    def _tag_keyword(
        self,
        conn: Any,
        batch_size: int,
        stats: TagStats,
    ) -> None:
        """Run keyword tagger on untagged entries."""
        entries = get_untagged_entry_ids(conn, method="keyword", limit=batch_size)
        if not entries:
            return

        tagger = KeywordTagger(self.config.tagging)

        for entry in entries:
            stats.processed += 1
            tags = tagger.tag(
                text=entry["text"],
                source_app=entry["source_app"],
                role=entry["role"],
                source_path=entry["source_path"],
            )
            if tags:
                upsert_tags(conn, entry["entry_id"], tags, method="keyword")
                stats.tagged += 1
            else:
                stats.skipped += 1

    def _tag_cli(
        self,
        conn: Any,
        batch_size: int,
        stats: TagStats,
    ) -> None:
        """Run CLI tagger on entries without CLI tags."""
        entries = get_untagged_entry_ids(conn, method="cli", limit=batch_size)
        if not entries:
            return

        tagger = CliTagger(self.config.tagging)

        # Process in sub-batches to keep CLI prompt size manageable
        sub_batch = min(10, batch_size)
        for i in range(0, len(entries), sub_batch):
            batch = entries[i : i + sub_batch]
            stats.processed += len(batch)

            try:
                tag_map = tagger.tag_batch(batch)
            except Exception as exc:
                logger.warning("CLI tagger batch failed: %s", exc)
                stats.errors += len(batch)
                continue

            for entry in batch:
                eid = entry["entry_id"]
                tags = tag_map.get(eid, [])
                if tags:
                    upsert_tags(conn, eid, tags, method="cli")
                    stats.tagged += 1
                else:
                    stats.skipped += 1
