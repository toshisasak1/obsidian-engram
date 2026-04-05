"""Click-based CLI for Engram.

Provides commands for initializing, syncing, searching, and managing
the Engram persistent memory database.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import click

from engram import __version__

if TYPE_CHECKING:
    from engram.config import EngramConfig

logger = logging.getLogger(__name__)

# Names of template files to copy during ``engram init`` (vault mode).
_VAULT_TEMPLATES = ("SOUL.md", "USER.md", "AGENTS.md", "TOOLS.md")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool = False) -> None:
    """Configure root logging for CLI output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(levelname)-8s %(message)s",
        level=level,
        stream=sys.stderr,
    )


def _load_config_or_exit(vault: str | None = None) -> EngramConfig:
    """Load configuration, exiting with an error message on failure."""
    from engram.config import load_config

    vault_path = Path(vault) if vault else _detect_vault()
    try:
        return load_config(vault_path=vault_path)
    except Exception as exc:
        click.echo(f"Error loading config: {exc}", err=True)
        sys.exit(1)


def _detect_vault() -> Path | None:
    """Walk upward from CWD looking for an .obsidian/ or .engram/ directory."""
    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        if (parent / ".obsidian").is_dir() or (parent / ".engram").is_dir():
            return parent
    return None


def _get_conn(cfg: EngramConfig) -> sqlite3.Connection:
    """Open a database connection and ensure schema is current."""
    from engram.db import connect, ensure_schema

    conn = connect(cfg.db_path)
    ensure_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Engram - Persistent memory for AI tools."""
    pass


# ---------------------------------------------------------------------------
# engram init
# ---------------------------------------------------------------------------


@main.command()
@click.option("--vault", type=click.Path(exists=True), help="Path to Obsidian vault")
@click.option("--no-vault", is_flag=True, help="Standalone mode (no Obsidian integration)")
@click.option("--yes", "-y", is_flag=True, help="Accept defaults without prompting")
def init(vault: str | None, no_vault: bool, yes: bool) -> None:
    """Initialize engram in the current directory or vault."""
    from engram.config import (
        EngramConfig,
        discover_sources,
        generate_config_toml,
        load_config,
    )

    _setup_logging()
    cwd = Path.cwd()

    # -- Determine vault path --------------------------------------------
    if no_vault:
        vault_path: Path | None = None
        click.echo("Standalone mode (no Obsidian integration).")
    elif vault:
        vault_path = Path(vault).resolve()
    elif (cwd / ".obsidian").is_dir():
        vault_path = cwd
        click.echo(f"Detected Obsidian vault: {vault_path}")
    else:
        vault_path = None
        click.echo("No .obsidian/ directory found. Using standalone mode.")

    # -- Discover sources ------------------------------------------------
    sources = discover_sources()
    if sources:
        click.echo(f"Discovered AI tool sources: {', '.join(sources.keys())}")
    else:
        click.echo("No AI tool sources auto-detected.")

    # -- Confirmation prompt ---------------------------------------------
    if not yes:
        anchor = vault_path or cwd
        db_loc = anchor / ".engram" / "engram.db"
        click.echo("\nThis will:")
        click.echo(f"  - Create .engram/ directory in {anchor}")
        click.echo(f"  - Initialize database at {db_loc}")
        if vault_path and not no_vault:
            click.echo(f"  - Copy template files to {vault_path}")
        click.echo(f"  - Run initial sync of {len(sources)} source(s)")
        if not click.confirm("\nProceed?", default=True):
            click.echo("Aborted.")
            return

    # -- Create .engram/ directory and config ----------------------------
    anchor = vault_path or cwd
    engram_dir = anchor / ".engram"
    engram_dir.mkdir(parents=True, exist_ok=True)

    cfg = EngramConfig(
        db_path=Path(".engram/engram.db"),
        vault_path=vault_path,
        sources=sources,
    )
    config_file = engram_dir / "config.toml"
    if not config_file.exists():
        config_file.write_text(generate_config_toml(cfg), encoding="utf-8")
        click.echo(f"Created {config_file}")
    else:
        click.echo(f"Config already exists: {config_file}")

    # -- Copy vault templates (only if vault mode) -----------------------
    if vault_path and not no_vault:
        template_dir = Path(__file__).resolve().parent.parent.parent / "vault_template"
        if template_dir.is_dir():
            for name in _VAULT_TEMPLATES:
                src = template_dir / name
                dst = vault_path / name
                if src.is_file() and not dst.exists():
                    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                    click.echo(f"  Created {dst.name}")
                elif dst.exists():
                    click.echo(f"  Skipped {dst.name} (already exists)")
        else:
            logger.debug("vault_template directory not found at %s", template_dir)

    # -- Load resolved config and create database ------------------------
    resolved_cfg = load_config(vault_path=vault_path)
    conn = _get_conn(resolved_cfg)

    # -- Run initial sync ------------------------------------------------
    try:
        from engram.sync import SyncEngine

        engine = SyncEngine(resolved_cfg)
        stats = engine.sync_once()
        click.echo(
            f"\nInitial sync complete: "
            f"{stats.scanned} scanned, {stats.indexed} indexed, "
            f"{stats.skipped} skipped, {stats.errors} errors"
        )
    except ImportError:
        click.echo("Sync engine not yet available; skipping initial sync.")
    except Exception as exc:
        click.echo(f"Initial sync failed: {exc}", err=True)

    conn.close()

    # -- Print MCP registration instructions -----------------------------
    click.echo("\n--- MCP Registration ---")
    click.echo("Add to your AI tool's MCP config:")
    click.echo("")
    click.echo('  {')
    click.echo('    "mcpServers": {')
    click.echo('      "engram": {')
    click.echo('        "command": "engram",')
    click.echo('        "args": ["mcp"],')
    click.echo('        "env": {}')
    click.echo("      }")
    click.echo("    }")
    click.echo("  }")
    click.echo("")
    click.echo("Done! Run `engram status` to verify.")


# ---------------------------------------------------------------------------
# engram sync
# ---------------------------------------------------------------------------


@main.command()
@click.option("--verbose", "-v", is_flag=True)
@click.option("--skip-embeddings", is_flag=True)
@click.option("--source", type=str, help="Sync only this source")
def sync(verbose: bool, skip_embeddings: bool, source: str | None) -> None:
    """Sync conversation logs into the database."""
    _setup_logging(verbose)

    cfg = _load_config_or_exit()

    try:
        from engram.sync import SyncEngine

        engine = SyncEngine(cfg)
        stats = engine.sync_once(
            skip_embeddings=skip_embeddings,
            source_filter=source,
        )
        click.echo(
            f"Sync complete: "
            f"{stats.scanned} scanned, {stats.indexed} indexed, "
            f"{stats.skipped} skipped, {stats.errors} errors"
        )
        if stats.embedded:
            click.echo(f"Embeddings: {stats.embedded} entries embedded")
    except ImportError:
        click.echo("Error: sync engine not available. Is the package installed?", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Sync failed: {exc}", err=True)
        logger.debug("Sync traceback:", exc_info=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# engram search
# ---------------------------------------------------------------------------


@main.command()
@click.argument("query")
@click.option("--limit", "-n", default=10, type=int)
@click.option("--source", type=str, help="Filter by source app")
@click.option("--tag", type=str, help="Filter by tags (comma-separated)")
@click.option("--json", "as_json", is_flag=True)
def search(query: str, limit: int, source: str | None, tag: str | None, as_json: bool) -> None:
    """Search across all indexed conversations."""
    _setup_logging()

    cfg = _load_config_or_exit()
    conn = _get_conn(cfg)

    try:
        from engram.search import search as hybrid_search

        results = hybrid_search(
            conn,
            query=query,
            config=cfg.search,
            limit=limit,
            source_app=source,
            tags=tag,
        )
    except ImportError:
        click.echo("Error: search module not available.", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Search failed: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()

    if not results:
        click.echo("No results found.")
        return

    if as_json:
        serialisable = []
        for r in results:
            serialisable.append({
                "entry_id": r.entry_id,
                "session_key": r.session_key,
                "source_app": r.source_app,
                "role": r.role,
                "snippet": r.snippet,
                "score": r.score,
                "timestamp": r.timestamp,
                "session_title": r.session_title,
            })
        click.echo(json.dumps(serialisable, indent=2, ensure_ascii=False))
    else:
        for i, r in enumerate(results, 1):
            title = r.session_title or r.entry_title or ""
            click.echo(f"\n--- {i}. [{r.source_app}] {title} (score: {r.score:.3f}) ---")
            click.echo(r.snippet)


# ---------------------------------------------------------------------------
# engram tag
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--provider",
    type=click.Choice(["keyword", "cli", "both"]),
    default=None,
    help="Tagging method (default: from config)",
)
@click.option("--batch-size", type=int, default=None, help="Max entries to process")
@click.option("--verbose", "-v", is_flag=True)
def tag(provider: str | None, batch_size: int | None, verbose: bool) -> None:
    """Tag untagged entries in the database."""
    _setup_logging(verbose)

    cfg = _load_config_or_exit()

    try:
        from engram.tagging import TagEngine

        engine = TagEngine(cfg)
        stats = engine.tag_untagged(provider=provider, batch_size=batch_size)
        click.echo(
            f"Tagging complete: "
            f"{stats.processed} processed, {stats.tagged} tagged, "
            f"{stats.skipped} skipped, {stats.errors} errors"
        )
    except Exception as exc:
        click.echo(f"Tagging failed: {exc}", err=True)
        logger.debug("Tagging traceback:", exc_info=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# engram brief
# ---------------------------------------------------------------------------


@main.command()
@click.option("--workspace", type=click.Path(), default=None)
@click.option("--query", "-q", multiple=True)
@click.option("--json", "as_json", is_flag=True)
@click.option("--output", "-o", type=click.Path())
def brief(
    workspace: str | None,
    query: tuple[str, ...],
    as_json: bool,
    output: str | None,
) -> None:
    """Generate a session context brief."""
    _setup_logging()

    cfg = _load_config_or_exit()
    conn = _get_conn(cfg)

    ws = Path(workspace).resolve() if workspace else Path.cwd()
    queries = list(query) if query else None

    try:
        from engram.brief import generate_brief, render_brief

        payload = generate_brief(conn, workspace=ws, queries=queries)

        if as_json:
            text = json.dumps(payload, indent=2, ensure_ascii=False)
        else:
            text = render_brief(payload)

        if output:
            Path(output).write_text(text, encoding="utf-8")
            click.echo(f"Brief written to {output}")
        else:
            click.echo(text)
    except Exception as exc:
        click.echo(f"Brief generation failed: {exc}", err=True)
        logger.debug("Brief traceback:", exc_info=True)
        sys.exit(1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# engram status
# ---------------------------------------------------------------------------


@main.command()
@click.option("--json", "as_json", is_flag=True)
def status(as_json: bool) -> None:
    """Show database statistics."""
    _setup_logging()

    cfg = _load_config_or_exit()

    if not cfg.db_path.exists():
        click.echo("Database not found. Run `engram init` first.", err=True)
        sys.exit(1)

    conn = _get_conn(cfg)

    try:
        from engram.db import get_stats

        stats = get_stats(conn)

        # Add source breakdown.
        try:
            source_rows = conn.execute(
                "SELECT source_app, COUNT(*) AS cnt "
                "FROM sessions GROUP BY source_app"
            ).fetchall()
            stats["sources"] = {row["source_app"]: row["cnt"] for row in source_rows}
        except Exception:
            stats["sources"] = {}

        stats["db_path"] = str(cfg.db_path)
        stats["vault_path"] = str(cfg.vault_path) if cfg.vault_path else None

        if as_json:
            click.echo(json.dumps(stats, indent=2, ensure_ascii=False))
        else:
            click.echo(f"Database:   {stats['db_path']}")
            if stats["vault_path"]:
                click.echo(f"Vault:      {stats['vault_path']}")
            click.echo(f"Schema:     v{stats['schema_version']}")
            click.echo(f"Sessions:   {stats['sessions']}")
            click.echo(f"Entries:    {stats['entries']}")
            click.echo(f"FTS rows:   {stats['fts_rows']}")
            click.echo(f"Embeddings: {stats['embeddings']}")
            click.echo(f"Tagged:     {stats['tagged_entries']}")
            click.echo(f"Src files:  {stats['source_files']}")
            if stats["sources"]:
                click.echo("Sources:")
                for app, cnt in sorted(stats["sources"].items()):
                    click.echo(f"  {app}: {cnt} sessions")
    except Exception as exc:
        click.echo(f"Status check failed: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# engram watch
# ---------------------------------------------------------------------------


@main.command()
@click.option("--log", type=click.Path(), default=None)
def watch(log: str | None) -> None:
    """Watch for changes and sync continuously."""
    _setup_logging(verbose=True)

    if log:
        handler = logging.FileHandler(log, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(handler)

    cfg = _load_config_or_exit()
    interval = cfg.sync.poll_interval_seconds

    click.echo(f"Watching for changes (poll every {interval}s). Press Ctrl+C to stop.")

    try:
        from engram.sync import SyncEngine

        engine = SyncEngine(cfg)
    except ImportError:
        click.echo("Error: sync engine not available.", err=True)
        sys.exit(1)

    try:
        while True:
            try:
                stats = engine.sync_once()
                if stats.indexed or stats.errors:
                    click.echo(
                        f"[{_now_local()}] "
                        f"indexed={stats.indexed} errors={stats.errors}"
                    )
            except Exception as exc:
                click.echo(f"[{_now_local()}] Sync error: {exc}", err=True)
                logger.debug("Watch sync error:", exc_info=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("\nStopped.")


# ---------------------------------------------------------------------------
# engram mcp
# ---------------------------------------------------------------------------


@main.command()
def mcp() -> None:
    """Start the MCP stdio server."""
    _setup_logging()

    try:
        from engram.mcp.server import serve
    except ImportError:
        click.echo(
            "Error: MCP server module not available. "
            "Ensure the package is installed with MCP support.",
            err=True,
        )
        sys.exit(1)

    cfg = _load_config_or_exit()
    try:
        serve(cfg)
    except Exception as exc:
        click.echo(f"MCP server error: {exc}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _now_local() -> str:
    """Return a short local-time string for log output."""
    from datetime import datetime

    return datetime.now().strftime("%H:%M:%S")
