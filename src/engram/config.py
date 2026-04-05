"""TOML-based configuration with layered resolution.

Resolution order (later wins):
    built-in defaults -> global config -> project config -> env vars -> CLI flags

Platform-aware paths and auto-discovery of AI tool directories.
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef,import-not-found]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _home() -> Path:
    return Path.home()


def _global_config_path() -> Path:
    """Return the platform-appropriate global config file path.

    - Linux / macOS: ``~/.config/engram/config.toml``
    - Windows: ``%APPDATA%/engram/config.toml``
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", _home() / ".config"))
    return base / "engram" / "config.toml"


def _default_source_paths() -> dict[str, Path]:
    """Auto-discover standard AI tool directories that exist on this system."""
    home = _home()
    candidates = {
        "claude": home / ".claude" / "projects",
        "codex": home / ".codex",
        "gemini": home / ".gemini" / "antigravity" / "brain",
    }
    return {k: v for k, v in candidates.items() if v.exists()}


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SourceConfig:
    """A single AI-tool source."""

    enabled: bool = True
    path: str = ""
    parser: str = ""  # Auto-detected from source name if empty


@dataclass
class SearchConfig:
    """Parameters for hybrid FTS5 + vector search."""

    fts_limit_multiplier: int = 5
    vector_limit_multiplier: int = 5
    rrf_k: int = 60
    half_life_days: float = 30.0


@dataclass
class EmbeddingConfig:
    """Vector-embedding backend configuration."""

    enabled: bool = False
    provider: str = "local"  # "local", "openai", "voyage", "none"
    model: str = "all-MiniLM-L6-v2"
    batch_size: int = 16
    max_characters: int = 4000
    api_key: str = ""  # Or use ENGRAM_EMBEDDING_API_KEY env var


@dataclass
class SyncConfig:
    """Filesystem watcher / poll settings."""

    poll_interval_seconds: int = 30
    settle_seconds: int = 8


@dataclass
class VaultConfig:
    """Obsidian vault knowledge ingestion settings."""

    enabled: bool = True
    include: list[str] = field(default_factory=lambda: ["**/*.md"])
    exclude: list[str] = field(default_factory=lambda: [
        "**/node_modules/**",
        "**/.obsidian/**",
        "**/.engram/**",
        "**/.smart-env/**",
        "**/.git/**",
    ])


@dataclass
class EngramConfig:
    """Top-level configuration object."""

    db_path: Path = field(default_factory=lambda: Path(".engram/engram.db"))
    vault_path: Path | None = None
    sources: dict[str, SourceConfig] = field(default_factory=dict)
    search: SearchConfig = field(default_factory=SearchConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    vault_knowledge: VaultConfig = field(default_factory=VaultConfig)


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------

def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into a deep copy of *base*.

    - dict values are merged recursively.
    - All other types in *override* replace the base value.
    """
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


# ---------------------------------------------------------------------------
# TOML -> dataclass hydration
# ---------------------------------------------------------------------------

def _hydrate_source(raw: dict[str, Any]) -> SourceConfig:
    return SourceConfig(
        enabled=raw.get("enabled", True),
        path=str(raw.get("path", "")),
        parser=str(raw.get("parser", "")),
    )


def _hydrate_search(raw: dict[str, Any]) -> SearchConfig:
    cfg = SearchConfig()
    for f in fields(cfg):
        if f.name in raw:
            setattr(cfg, f.name, f.type(raw[f.name]) if isinstance(f.type, type) else raw[f.name])
    return cfg


def _hydrate_flat_dataclass(cls: type, raw: dict[str, Any]) -> Any:
    """Hydrate a flat (non-nested) dataclass from a dict, casting types."""
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in raw:
            continue
        val = raw[f.name]
        # Handle basic type casting for primitives
        if f.type in ("bool", bool):
            kwargs[f.name] = bool(val)
        elif f.type in ("int", int):
            kwargs[f.name] = int(val)
        elif f.type in ("float", float):
            kwargs[f.name] = float(val)
        elif f.type in ("str", str):
            kwargs[f.name] = str(val)
        else:
            kwargs[f.name] = val
    return cls(**kwargs)


def _hydrate_config(raw: dict[str, Any], vault_path: Path | None = None) -> EngramConfig:
    """Build an ``EngramConfig`` from a merged raw TOML dict."""

    cfg = EngramConfig()

    # -- scalar top-level ------------------------------------------------
    if "db_path" in raw:
        cfg.db_path = Path(raw["db_path"])
    if "vault_path" in raw:
        cfg.vault_path = Path(raw["vault_path"])
    elif vault_path is not None:
        cfg.vault_path = vault_path

    # -- sources ---------------------------------------------------------
    sources_raw: dict[str, Any] = raw.get("sources", {})
    for name, src_dict in sources_raw.items():
        if isinstance(src_dict, dict):
            cfg.sources[name] = _hydrate_source(src_dict)

    # -- nested sections -------------------------------------------------
    if "search" in raw and isinstance(raw["search"], dict):
        cfg.search = _hydrate_flat_dataclass(SearchConfig, raw["search"])
    if "embedding" in raw and isinstance(raw["embedding"], dict):
        cfg.embedding = _hydrate_flat_dataclass(EmbeddingConfig, raw["embedding"])
    if "sync" in raw and isinstance(raw["sync"], dict):
        cfg.sync = _hydrate_flat_dataclass(SyncConfig, raw["sync"])
    if "vault_knowledge" in raw and isinstance(raw["vault_knowledge"], dict):
        vk = raw["vault_knowledge"]
        cfg.vault_knowledge = VaultConfig(
            enabled=vk.get("enabled", True),
            include=vk.get("include", cfg.vault_knowledge.include),
            exclude=vk.get("exclude", cfg.vault_knowledge.exclude),
        )

    return cfg


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------

def discover_sources() -> dict[str, SourceConfig]:
    """Probe the filesystem for known AI tool directories.

    Returns ``SourceConfig`` objects only for tools whose standard data
    directories actually exist on the current machine.
    """
    found: dict[str, SourceConfig] = {}
    for name, path in _default_source_paths().items():
        found[name] = SourceConfig(enabled=True, path=str(path), parser=name)
    return found


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _read_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file, returning an empty dict if it doesn't exist."""
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _apply_env_overrides(cfg: EngramConfig) -> None:
    """Apply environment-variable overrides in-place."""
    if val := os.environ.get("ENGRAM_DB_PATH"):
        cfg.db_path = Path(val)
    if val := os.environ.get("ENGRAM_VAULT_PATH"):
        cfg.vault_path = Path(val)
    if val := os.environ.get("ENGRAM_EMBEDDING_API_KEY"):
        cfg.embedding.api_key = val


def _resolve_paths(cfg: EngramConfig, anchor: Path) -> None:
    """Resolve relative ``db_path`` against *anchor* (typically vault root)."""
    if not cfg.db_path.is_absolute():
        cfg.db_path = (anchor / cfg.db_path).resolve()
    if cfg.vault_path is not None and not cfg.vault_path.is_absolute():
        cfg.vault_path = (anchor / cfg.vault_path).resolve()


def load_config(
    vault_path: Path | None = None,
    config_path: Path | None = None,
) -> EngramConfig:
    """Load configuration with layered resolution.

    Resolution order (each layer overrides the previous):

    1. Built-in defaults (dataclass defaults + auto-discovered sources)
    2. Global config   ``~/.config/engram/config.toml``
    3. Project config  ``<vault>/.engram/config.toml``  (or *config_path*)
    4. Environment variables (``ENGRAM_DB_PATH``, ``ENGRAM_VAULT_PATH``,
       ``ENGRAM_EMBEDDING_API_KEY``)

    Parameters
    ----------
    vault_path:
        Root of the Obsidian vault.  Used to locate the project config and
        to resolve relative paths.  When ``None``, only global config and
        env vars apply.
    config_path:
        Explicit path to a TOML config file.  When given, this replaces the
        project-level config lookup (the global config is still loaded).

    Returns
    -------
    EngramConfig
        Fully resolved configuration object.
    """
    # -- Layer 1: built-in defaults (as dict for merging) ----------------
    merged: dict[str, Any] = {}

    # -- Layer 2: global config ------------------------------------------
    global_raw = _read_toml(_global_config_path())
    if global_raw:
        merged = _merge_config(merged, global_raw)

    # -- Layer 3: project config -----------------------------------------
    if config_path is not None:
        project_raw = _read_toml(config_path)
    elif vault_path is not None:
        project_raw = _read_toml(vault_path / ".engram" / "config.toml")
    else:
        project_raw = {}
    if project_raw:
        merged = _merge_config(merged, project_raw)

    # -- Hydrate ---------------------------------------------------------
    cfg = _hydrate_config(merged, vault_path=vault_path)

    # -- Auto-discovered sources (fill in anything not already specified) -
    for name, src in discover_sources().items():
        if name not in cfg.sources:
            cfg.sources[name] = src

    # -- Layer 4: env vars -----------------------------------------------
    _apply_env_overrides(cfg)

    # -- Path resolution -------------------------------------------------
    anchor = vault_path if vault_path is not None else Path.cwd()
    _resolve_paths(cfg, anchor)

    return cfg


# ---------------------------------------------------------------------------
# TOML generation (for `engram init`)
# ---------------------------------------------------------------------------

def generate_config_toml(config: EngramConfig) -> str:
    """Render a commented TOML string from an ``EngramConfig``.

    The output is intended to be written as ``.engram/config.toml`` by
    ``engram init``.  Every section includes a short comment explaining its
    purpose.
    """
    lines: list[str] = [
        "# Engram configuration",
        "# https://github.com/toshi/obsidian-engram",
        "#",
        "# This file was auto-generated by `engram init`.",
        "# Edit freely -- comments are preserved on re-generation.",
        "",
        "# Path to the SQLite database (relative to vault root).",
        f'db_path = "{_posix(config.db_path)}"',
        "",
    ]

    if config.vault_path is not None:
        lines.append("# Absolute path to the Obsidian vault root.")
        lines.append(f'vault_path = "{_posix(config.vault_path)}"')
        lines.append("")

    # -- sources ---------------------------------------------------------
    if config.sources:
        lines.append("# AI tool sources to index.")
        lines.append("# Each [sources.<name>] section defines one tool.")
        for name, src in sorted(config.sources.items()):
            lines.append("")
            lines.append(f"[sources.{name}]")
            lines.append(f"enabled = {_toml_bool(src.enabled)}")
            lines.append(f'path = "{_posix_str(src.path)}"')
            if src.parser:
                lines.append(f'parser = "{src.parser}"')
        lines.append("")

    # -- search ----------------------------------------------------------
    lines.extend([
        "# Hybrid search tuning.",
        "[search]",
        f"fts_limit_multiplier = {config.search.fts_limit_multiplier}",
        f"vector_limit_multiplier = {config.search.vector_limit_multiplier}",
        f"rrf_k = {config.search.rrf_k}",
        f"half_life_days = {config.search.half_life_days}",
        "",
    ])

    # -- embedding -------------------------------------------------------
    lines.extend([
        '# Embedding backend.  Set enabled = true and choose a provider',
        '# ("local", "openai", "voyage", "none").',
        "[embedding]",
        f"enabled = {_toml_bool(config.embedding.enabled)}",
        f'provider = "{config.embedding.provider}"',
        f'model = "{config.embedding.model}"',
        f"batch_size = {config.embedding.batch_size}",
        f"max_characters = {config.embedding.max_characters}",
        "# api_key = \"\"  # Or set ENGRAM_EMBEDDING_API_KEY env var.",
        "",
    ])

    # -- sync ------------------------------------------------------------
    lines.extend([
        "# File-system watcher / poll settings.",
        "[sync]",
        f"poll_interval_seconds = {config.sync.poll_interval_seconds}",
        f"settle_seconds = {config.sync.settle_seconds}",
        "",
    ])

    # -- vault_knowledge -------------------------------------------------
    lines.extend([
        "# Obsidian vault knowledge ingestion.",
        "[vault_knowledge]",
        f"enabled = {_toml_bool(config.vault_knowledge.enabled)}",
        f"include = {_toml_str_list(config.vault_knowledge.include)}",
        f"exclude = {_toml_str_list(config.vault_knowledge.exclude)}",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TOML formatting helpers
# ---------------------------------------------------------------------------

def _toml_bool(val: bool) -> str:
    return "true" if val else "false"


def _toml_str_list(items: list[str]) -> str:
    """Format a Python list of strings as a TOML inline array."""
    inner = ", ".join(f'"{s}"' for s in items)
    return f"[{inner}]"


def _posix(p: Path) -> str:
    """Return a forward-slash path string (readable on all platforms)."""
    return p.as_posix()


def _posix_str(s: str) -> str:
    """Normalise an arbitrary path string to forward slashes."""
    return s.replace("\\", "/")
