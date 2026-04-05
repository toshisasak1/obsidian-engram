"""Parser for Obsidian vault markdown files.

Handles ``.md`` files with optional YAML frontmatter (between ``---``
delimiters) and splits the remaining content into sections by ``##``
headings.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from pathlib import Path

from engram.models import EntryRecord, SessionRecord
from engram.parsers.base import (
    BaseParser,
    normalize_text,
    split_markdown_sections,
    truncate,
)

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?\n)---\s*\n",
    re.DOTALL,
)

# Directories commonly excluded from Obsidian indexing
_DEFAULT_EXCLUDES = frozenset({
    ".obsidian",
    ".git",
    ".trash",
    "node_modules",
    "__pycache__",
})


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from *text*.

    Returns ``(metadata_dict, remaining_body)``.  If no frontmatter is
    present, returns ``({}, text)``.

    Uses a simple key-value parser to avoid a hard dependency on PyYAML.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    raw_yaml = m.group(1)
    body = text[m.end():]

    # Minimal YAML-like parser: handles "key: value" and "key: [a, b]"
    meta: dict = {}
    for line in raw_yaml.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        # Inline list: [a, b, c]
        if value.startswith("[") and value.endswith("]"):
            items = [
                item.strip().strip("\"'")
                for item in value[1:-1].split(",")
                if item.strip()
            ]
            meta[key] = items
        else:
            # Strip surrounding quotes
            if (
                len(value) >= 2
                and value[0] in "\"'"
                and value[-1] == value[0]
            ):
                value = value[1:-1]
            meta[key] = value

    return meta, body


class VaultParser(BaseParser):
    """Parse Obsidian vault ``.md`` files."""

    name = "vault"

    def __init__(
        self,
        *,
        include_patterns: list[str] | None = None,
        exclude_dirs: set[str] | None = None,
    ) -> None:
        self._include_patterns = include_patterns or ["**/*.md"]
        self._exclude_dirs = exclude_dirs or _DEFAULT_EXCLUDES

    # ---- discovery --------------------------------------------------------

    def discover_paths(self, root: Path) -> Iterable[Path]:
        """Yield ``.md`` files under *root*, respecting include/exclude."""
        for pattern in self._include_patterns:
            for p in sorted(root.rglob(pattern) if "**" in pattern else root.glob(pattern)):
                try:
                    if not p.is_file():
                        continue
                except OSError:
                    continue  # Skip inaccessible paths
                # Skip excluded directories
                try:
                    rel_parts = p.relative_to(root).parts
                except ValueError:
                    continue
                if any(part in self._exclude_dirs for part in rel_parts):
                    continue
                yield p

    def default_root(self) -> Path | None:
        return None  # Vault path must be supplied by the user

    # ---- parsing ----------------------------------------------------------

    def parse(self, path: Path) -> tuple[SessionRecord, list[EntryRecord]]:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("vault: failed to read %s: %s", path, exc)
            raise

        frontmatter, body = _parse_frontmatter(raw)

        # Derive identifiers
        external_id = str(path)
        session_key = f"vault:{external_id}"

        # Extract useful frontmatter fields
        tags: list[str] = []
        raw_tags = frontmatter.get("tags", [])
        if isinstance(raw_tags, list):
            tags = raw_tags
        elif isinstance(raw_tags, str):
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

        title = frontmatter.get("title", "") or path.stem
        created = frontmatter.get("created") or frontmatter.get("date")
        updated = frontmatter.get("updated") or frontmatter.get("modified")

        session = SessionRecord(
            session_key=session_key,
            source_app="vault",
            source_path=str(path),
            external_id=external_id,
            title=truncate(str(title), 120),
            started_at=str(created) if created else None,
            updated_at=str(updated) if updated else None,
            metadata={
                k: v
                for k, v in {
                    "tags": tags or None,
                    "frontmatter": frontmatter or None,
                }.items()
                if v is not None
            },
        )

        # Split body into sections
        sections = split_markdown_sections(body)
        entries: list[EntryRecord] = []

        for idx, (heading, content) in enumerate(sections):
            content = normalize_text(content)
            if not content:
                continue

            section_title = heading.lstrip("# ").strip() if heading else title
            entries.append(
                EntryRecord(
                    entry_id=str(uuid.uuid4()),
                    session_key=session_key,
                    source_app="vault",
                    source_kind="vault_section",
                    source_path=str(path),
                    ordinal=idx,
                    role="document",
                    text=content,
                    timestamp=str(created) if created else None,
                    title=truncate(str(section_title), 120),
                    metadata={
                        k: v
                        for k, v in {
                            "heading": heading or None,
                            "tags": tags or None,
                        }.items()
                        if v is not None
                    },
                )
            )

        return session, entries
