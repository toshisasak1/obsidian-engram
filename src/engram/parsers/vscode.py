"""Parser for VS Code sidebar chat history.

This is a stub for v1 -- the actual implementation will follow once
the VS Code chat export format is finalized.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from engram.models import EntryRecord, SessionRecord
from engram.parsers.base import BaseParser


class VSCodeParser(BaseParser):
    """Stub parser for VS Code sidebar chat. Not yet implemented."""

    name = "vscode"

    def discover_paths(self, root: Path) -> Iterable[Path]:
        return []  # Not yet implemented

    def parse(self, path: Path) -> tuple[SessionRecord, list[EntryRecord]]:
        raise NotImplementedError("VS Code parser is not yet implemented")

    def default_root(self) -> Path | None:
        return None
