"""Parser registry with entry_points discovery for third-party parsers."""

from __future__ import annotations

import importlib.metadata

from engram.parsers.base import BaseParser
from engram.parsers.claude import ClaudeParser
from engram.parsers.codex import CodexParser
from engram.parsers.gemini import GeminiParser
from engram.parsers.vault import VaultParser
from engram.parsers.vscode import VSCodeParser

_BUILTIN: dict[str, type[BaseParser]] = {
    "claude": ClaudeParser,
    "codex": CodexParser,
    "gemini": GeminiParser,
    "vault": VaultParser,
    "vscode": VSCodeParser,
}


def get_parser(name: str) -> BaseParser:
    """Return an instantiated parser by name.

    Checks built-in parsers first, then falls back to
    ``engram.parsers`` entry_points for third-party plugins.
    """
    if name in _BUILTIN:
        return _BUILTIN[name]()

    for ep in importlib.metadata.entry_points(group="engram.parsers"):
        if ep.name == name:
            return ep.load()()

    raise ValueError(f"Unknown parser: {name}")


def list_parsers() -> list[str]:
    """Return the names of all built-in parsers."""
    return list(_BUILTIN.keys())
