"""Parser for Gemini antigravity brain artifacts.

Handles directories at ``~/.gemini/antigravity/brain/{uuid}/``.
Each brain directory may contain ``.md`` artifacts with optional
``.metadata.json`` sidecars.  Files with a ``.resolved`` suffix are
preferred over their base counterparts.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from engram.models import EntryRecord, SessionRecord
from engram.parsers.base import (
    BaseParser,
    build_paragraph_entries,
    normalize_text,
    truncate,
)

logger = logging.getLogger(__name__)


class GeminiParser(BaseParser):
    """Parse Gemini antigravity brain directories."""

    name = "gemini"

    # ---- discovery --------------------------------------------------------

    def discover_paths(self, root: Path) -> Iterable[Path]:
        """Yield brain directories (not individual files) under *root*.

        Each yielded path is a directory that contains at least one
        ``.md`` file.
        """
        brain_dir = root / "antigravity" / "brain"
        if not brain_dir.is_dir():
            # Fall back: maybe root itself is the brain directory
            if root.is_dir() and any(root.glob("*.md")):
                yield root
                return
            return

        for child in sorted(brain_dir.iterdir()):
            if child.is_dir() and any(child.glob("*.md")):
                yield child

    def default_root(self) -> Path | None:
        return Path.home() / ".gemini"

    # ---- parsing ----------------------------------------------------------

    def parse(self, path: Path) -> tuple[SessionRecord, list[EntryRecord]]:
        """Parse a single brain directory into a session and entries.

        *path* should point to a brain directory (e.g.
        ``~/.gemini/antigravity/brain/{uuid}/``).
        """
        if not path.is_dir():
            raise ValueError(f"Expected a directory, got: {path}")

        md_files = self._collect_md_files(path)
        external_id = path.name
        session_key = f"gemini:{external_id}"

        # Collect all entries across files
        all_entries: list[EntryRecord] = []
        earliest_ts: str | None = None
        latest_ts: str | None = None
        combined_title = ""

        for md_path in md_files:
            meta = self._load_metadata(md_path)
            text = self._read_text(md_path)
            if not text:
                continue

            ts = meta.get("timestamp") or meta.get("created_at")
            if ts:
                if earliest_ts is None or ts < earliest_ts:
                    earliest_ts = ts
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts

            file_title = meta.get("title", "") or md_path.stem
            if not combined_title:
                combined_title = file_title

            # Build a temporary session for the paragraph builder
            tmp_session = SessionRecord(
                session_key=session_key,
                source_app="gemini",
                source_path=str(md_path),
                external_id=external_id,
                title=file_title,
                started_at=ts,
            )

            chunks = build_paragraph_entries(
                tmp_session,
                text,
                source_path=str(md_path),
                base_title=file_title,
            )
            # Attach file-level metadata to each chunk
            for chunk in chunks:
                chunk.metadata = {
                    k: v
                    for k, v in meta.items()
                    if v is not None
                }
            all_entries.extend(chunks)

        # Re-number ordinals sequentially
        for idx, entry in enumerate(all_entries):
            entry.ordinal = idx

        session = SessionRecord(
            session_key=session_key,
            source_app="gemini",
            source_path=str(path),
            external_id=external_id,
            title=truncate(combined_title, 120) or path.name,
            started_at=earliest_ts,
            updated_at=latest_ts,
            metadata={},
        )

        return session, all_entries

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _collect_md_files(brain_dir: Path) -> list[Path]:
        """Return markdown files, preferring ``.resolved`` variants.

        If both ``foo.md`` and ``foo.md.resolved`` exist, only the
        resolved version is returned.
        """
        all_md = sorted(brain_dir.glob("*.md"))
        all_resolved = sorted(brain_dir.glob("*.md.resolved"))

        # Build a set of base stems that have resolved versions
        resolved_bases: set[str] = set()
        for rp in all_resolved:
            # "foo.md.resolved" -> base is "foo.md"
            base = rp.name.removesuffix(".resolved")
            resolved_bases.add(base)

        result: list[Path] = []
        for md in all_md:
            if md.name in resolved_bases:
                continue  # Skip; resolved version will be added
            if md.name.endswith(".metadata.json"):
                continue  # Not a content file
            result.append(md)

        # Add resolved files
        result.extend(all_resolved)
        return sorted(result, key=lambda p: p.name)

    @staticmethod
    def _load_metadata(md_path: Path) -> dict:
        """Load the ``.metadata.json`` sidecar for *md_path*, if present."""
        # Try "{name}.metadata.json" as sidecar
        meta_path = md_path.parent / f"{md_path.stem}.metadata.json"
        if not meta_path.is_file():
            # For .resolved files: "foo.md.resolved" -> "foo.metadata.json"
            base_name = md_path.name
            if base_name.endswith(".resolved"):
                base_name = base_name.removesuffix(".resolved")
            stem = Path(base_name).stem
            meta_path = md_path.parent / f"{stem}.metadata.json"

        if not meta_path.is_file():
            return {}

        try:
            with meta_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("gemini: failed to read metadata %s: %s", meta_path, exc)
            return {}

    @staticmethod
    def _read_text(md_path: Path) -> str:
        """Read and normalize the text content of a markdown file."""
        try:
            raw = md_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("gemini: failed to read %s: %s", md_path, exc)
            return ""
        return normalize_text(raw)
