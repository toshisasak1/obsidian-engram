"""Abstract base class and shared utilities for all parsers."""

from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from engram.models import EntryRecord, SessionRecord


class BaseParser(ABC):
    """Base class that every parser must subclass."""

    name: str

    @abstractmethod
    def discover_paths(self, root: Path) -> Iterable[Path]:
        """Find all parseable files under *root*."""
        ...

    @abstractmethod
    def parse(self, path: Path) -> tuple[SessionRecord, list[EntryRecord]]:
        """Parse a single source file into a session and its entries."""
        ...

    def default_root(self) -> Path | None:
        """Return the platform-default root path, or ``None``."""
        return None


# ---------------------------------------------------------------------------
# Shared utility functions
# ---------------------------------------------------------------------------

_WS_RUN = re.compile(r"[ \t]+")
_NL_RUN = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Collapse runs of whitespace / blank lines into single instances."""
    text = _WS_RUN.sub(" ", text)
    text = _NL_RUN.sub("\n\n", text)
    return text.strip()


def truncate(text: str, max_len: int = 200) -> str:
    """Truncate *text* to *max_len* characters, adding an ellipsis if cut."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


def build_qa_entries(
    session: SessionRecord,
    entries: list[EntryRecord],
) -> list[EntryRecord]:
    """Pair sequential user/assistant entries into Q&A chunks.

    Consecutive (user, assistant) pairs are merged into a single entry with
    ``role="qa"`` and ``source_kind="qa_chunk"``.  Unpaired entries (e.g. a
    trailing user message) are kept as-is.
    """
    qa: list[EntryRecord] = []
    i = 0
    ordinal = 0
    while i < len(entries):
        cur = entries[i]
        # Try to pair user + assistant
        if (
            cur.role == "user"
            and i + 1 < len(entries)
            and entries[i + 1].role == "assistant"
        ):
            nxt = entries[i + 1]
            qa.append(
                EntryRecord(
                    entry_id=str(uuid.uuid4()),
                    session_key=session.session_key,
                    source_app=session.source_app,
                    source_kind="qa_chunk",
                    source_path=session.source_path,
                    ordinal=ordinal,
                    role="qa",
                    text=f"Q: {cur.text}\nA: {nxt.text}",
                    timestamp=cur.timestamp or nxt.timestamp,
                    title=truncate(cur.text, 120),
                    metadata={},
                )
            )
            i += 2
        else:
            qa.append(
                EntryRecord(
                    entry_id=cur.entry_id,
                    session_key=session.session_key,
                    source_app=session.source_app,
                    source_kind=cur.source_kind,
                    source_path=cur.source_path,
                    ordinal=ordinal,
                    role=cur.role,
                    text=cur.text,
                    timestamp=cur.timestamp,
                    title=cur.title,
                    metadata=cur.metadata,
                )
            )
            i += 1
        ordinal += 1
    return qa


def build_paragraph_entries(
    session: SessionRecord,
    text: str,
    source_path: str,
    base_title: str = "",
) -> list[EntryRecord]:
    """Split *text* into paragraph chunks (max 4000 chars each)."""
    paragraphs = re.split(r"\n{2,}", text.strip())
    entries: list[EntryRecord] = []
    buf = ""
    ordinal = 0

    def _flush(buf: str) -> None:
        nonlocal ordinal
        if not buf.strip():
            return
        entries.append(
            EntryRecord(
                entry_id=str(uuid.uuid4()),
                session_key=session.session_key,
                source_app=session.source_app,
                source_kind="artifact_chunk",
                source_path=source_path,
                ordinal=ordinal,
                role="artifact",
                text=buf.strip(),
                timestamp=session.started_at,
                title=truncate(base_title or buf.strip(), 120),
                metadata={},
            )
        )
        ordinal += 1

    for para in paragraphs:
        if len(buf) + len(para) + 2 > 4000:
            _flush(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para

    _flush(buf)
    return entries


def split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown *text* by ``##`` headings.

    Returns a list of ``(heading, content)`` tuples.  Content before the
    first heading uses an empty-string heading.  Each section is capped at
    4000 characters; oversized sections are split at paragraph boundaries.
    """
    parts = re.split(r"(?m)^(##\s+.+)$", text)
    sections: list[tuple[str, str]] = []
    heading = ""
    content_buf = ""

    def _emit(heading: str, content: str) -> None:
        content = content.strip()
        if not content:
            return
        if len(content) <= 4000:
            sections.append((heading, content))
        else:
            # Split oversized section at paragraph boundaries
            chunks = re.split(r"\n{2,}", content)
            buf = ""
            idx = 0
            for chunk in chunks:
                if len(buf) + len(chunk) + 2 > 4000:
                    if buf.strip():
                        suffix = f" (part {idx + 1})" if idx > 0 else ""
                        sections.append((heading + suffix, buf.strip()))
                        idx += 1
                    buf = chunk
                else:
                    buf = f"{buf}\n\n{chunk}" if buf else chunk
            if buf.strip():
                suffix = f" (part {idx + 1})" if idx > 0 else ""
                sections.append((heading + suffix, buf.strip()))

    for part in parts:
        if part.startswith("## "):
            _emit(heading, content_buf)
            heading = part.strip()
            content_buf = ""
        else:
            content_buf += part

    _emit(heading, content_buf)
    return sections
