# Parser Reference

Parsers are the components that read source files from AI tools and convert them into Engram's internal data model (sessions and entries). Engram ships with five built-in parsers and supports third-party parsers via Python entry points.

## Built-in parsers

| Parser | Source | File format | Status |
|--------|--------|-------------|--------|
| `claude` | Claude Code | JSONL (`~/.claude/projects/`) | Complete |
| `codex` | Codex CLI | JSONL (`~/.codex/`) | Complete |
| `gemini` | Gemini CLI | Markdown + JSON metadata (`~/.gemini/`) | Complete |
| `vault` | Obsidian vault | Markdown with optional YAML frontmatter | Complete |
| `vscode` | VS Code sidebar chat | -- | Stub (not yet implemented) |

## Data model

Every parser produces two types of records:

### SessionRecord

Represents one conversation or document:

| Field | Type | Description |
|-------|------|-------------|
| `session_key` | string | Unique key in the format `source_app:external_id` |
| `source_app` | string | The source name (e.g., `"claude"`, `"codex"`) |
| `source_path` | string | Absolute path to the source file |
| `external_id` | string | Original session ID from the source tool |
| `title` | string | Human-readable title (derived from first user message or filename) |
| `cwd` | string or null | Working directory at session start (if available) |
| `project` | string or null | Project path (if available) |
| `started_at` | ISO 8601 or null | Timestamp of the first entry |
| `updated_at` | ISO 8601 or null | Timestamp of the last entry |
| `metadata` | dict | Extra key-value data (e.g., git branch, tags) |

### EntryRecord

Represents one indexable unit within a session:

| Field | Type | Description |
|-------|------|-------------|
| `entry_id` | string | Globally unique identifier (UUID or source-provided) |
| `session_key` | string | Links back to the parent session |
| `source_app` | string | The source name |
| `source_kind` | string | Entry type: `"message"`, `"qa_chunk"`, `"artifact_chunk"`, `"vault_section"` |
| `source_path` | string | Absolute path to the source file |
| `ordinal` | integer | Position within the session (0-indexed) |
| `role` | string | `"user"`, `"assistant"`, `"qa"`, `"artifact"`, `"document"` |
| `text` | string | The full text content (indexed by FTS5) |
| `timestamp` | ISO 8601 or null | When this entry was created |
| `title` | string or null | Short title (truncated to 120 characters) |
| `metadata` | dict | Extra key-value data |

## Parser: `claude`

### Source format

Claude Code stores conversation logs as JSONL files at `~/.claude/projects/{hash}/{uuid}.jsonl`. Each line is a JSON object with fields including `type`, `message`, `sessionId`, `cwd`, `gitBranch`, `timestamp`, and `uuid`.

### Discovery

The parser recursively searches for `*.jsonl` files under the configured root, skipping any paths containing `subagents/` in their path components.

### Parsing behavior

1. Each line is parsed as JSON. Lines with `type` in `{"progress", "file-history-snapshot", "bash_progress"}` are skipped.
2. Only entries with a `message` object containing `role` of `"user"` or `"assistant"` are kept.
3. The `content` field is extracted: it can be a plain string or a list of blocks (`[{"type": "text", "text": "..."}]`).
4. Text is normalized (whitespace collapsed, excessive blank lines reduced).
5. The session title is derived from the first user message (truncated to 120 characters).
6. Raw message entries are paired into Q&A chunks: consecutive (user, assistant) pairs become a single entry with `role="qa"` and `source_kind="qa_chunk"`, formatted as `Q: ...\nA: ...`.

### Metadata captured

- `git_branch`: extracted from the first line that includes it

### Default root

`~/.claude/projects` (same on all platforms)

## Parser: `codex`

### Source format

Codex CLI stores two kinds of JSONL files:

1. **`~/.codex/history.jsonl`**: A global history file with one line per user input. Each line has `session_id`, `ts` (Unix timestamp in seconds), and `text`.
2. **`~/.codex/sessions/{id}.jsonl`**: Full session transcripts with `type` fields like `session_meta`, `response_item`, and `event_msg`.

### Discovery

The parser yields:
1. `history.jsonl` if it exists in the root
2. All `*.jsonl` files under `sessions/` (recursive, sorted)

### Parsing behavior

**For `history.jsonl`**:
- Lines are grouped by `session_id`
- Only the first session group is returned per file
- Entries are user-role only (no assistant responses in the history file)
- Unix timestamps are converted to ISO 8601

**For session files**:
- `session_meta` lines provide session-level metadata (cwd, session_id)
- `response_item` lines provide assistant responses; content is extracted from a blocks array (types: `text`, `input_text`, `output_text`)
- `event_msg` lines provide user messages
- Consecutive user/assistant pairs are merged into Q&A chunks (same as Claude parser)

### Default root

`~/.codex` (same on all platforms)

## Parser: `gemini`

### Source format

Gemini CLI stores artifacts as Markdown files with optional `.metadata.json` sidecars in brain directories at `~/.gemini/antigravity/brain/{uuid}/`.

### Discovery

The parser yields **directories** (not individual files). Each directory under `antigravity/brain/` that contains at least one `.md` file is yielded as a single parseable unit.

### Parsing behavior

1. Within each brain directory, `.md` files are collected. If both `foo.md` and `foo.md.resolved` exist, only the resolved version is used.
2. For each Markdown file, the parser looks for a `.metadata.json` sidecar (e.g., `foo.metadata.json` for `foo.md`).
3. Text content is normalized and split into paragraph chunks of up to 4000 characters each.
4. Each chunk becomes an `EntryRecord` with `role="artifact"` and `source_kind="artifact_chunk"`.
5. Timestamps from metadata (the `timestamp` or `created_at` fields) are used to set session timing.

### Metadata captured

All fields from the `.metadata.json` sidecar are attached to each chunk's metadata.

### Default root

`~/.gemini` (the parser expects `antigravity/brain/` subdirectories within this root)

## Parser: `vault`

### Source format

Obsidian vault `.md` files with optional YAML frontmatter delimited by `---`.

### Discovery

The parser uses configurable include/exclude patterns (from `[vault_knowledge]` in config) to find files. By default:

- **Include**: `["**/*.md"]` (all Markdown files recursively)
- **Exclude directories**: `.obsidian`, `.git`, `.trash`, `node_modules`, `__pycache__`

### Parsing behavior

1. YAML frontmatter (between `---` delimiters) is extracted using a minimal key-value parser. Supports simple `key: value` pairs and inline lists `key: [a, b, c]`.
2. The body (after frontmatter) is split into sections at `##` headings.
3. Each section becomes an `EntryRecord` with `role="document"` and `source_kind="vault_section"`.
4. Sections exceeding 4000 characters are further split at paragraph boundaries, with `(part N)` suffixes appended to the heading.
5. Frontmatter fields `title`, `created`/`date`, `updated`/`modified`, and `tags` are used for session metadata.

### Metadata captured

- `tags`: from frontmatter (list or comma-separated string)
- `heading`: the section heading text
- `frontmatter`: the full parsed frontmatter dict (on the session)

### Example

Given this Markdown file:

```markdown
---
title: Deployment Guide
tags: [infra, deploy]
created: 2026-03-15
---

# Deployment Guide

Introduction text here.

## Prerequisites

You need Docker and kubectl...

## Steps

1. Build the image...
2. Push to registry...
```

The parser produces:
- **Session**: title="Deployment Guide", tags=["infra", "deploy"], started_at="2026-03-15"
- **Entry 1**: heading="", text="Introduction text here." (content before the first ## heading)
- **Entry 2**: heading="## Prerequisites", text="You need Docker and kubectl..."
- **Entry 3**: heading="## Steps", text="1. Build the image...\n2. Push to registry..."

## Parser: `vscode`

This parser is a stub. VS Code sidebar chat support is planned but the export format is not yet finalized. The parser discovers no files and raises `NotImplementedError` if called directly.

## Writing a custom parser

### Step 1: Subclass `BaseParser`

Create a Python file with a class that extends `BaseParser`:

```python
# my_parser/parser.py

from collections.abc import Iterable
from pathlib import Path

from engram.models import EntryRecord, SessionRecord
from engram.parsers.base import BaseParser, normalize_text, truncate


class MyToolParser(BaseParser):
    name = "mytool"

    def discover_paths(self, root: Path) -> Iterable[Path]:
        """Find all parseable files under root."""
        for p in sorted(root.rglob("*.json")):
            yield p

    def parse(self, path: Path) -> tuple[SessionRecord, list[EntryRecord]]:
        """Parse a single file into a session and entries."""
        import json
        import uuid

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        session = SessionRecord(
            session_key=f"mytool:{path.stem}",
            source_app="mytool",
            source_path=str(path),
            external_id=path.stem,
            title=truncate(data.get("title", path.stem), 120),
            started_at=data.get("timestamp"),
        )

        entries = []
        for i, msg in enumerate(data.get("messages", [])):
            text = normalize_text(msg.get("text", ""))
            if not text:
                continue
            entries.append(EntryRecord(
                entry_id=str(uuid.uuid4()),
                session_key=session.session_key,
                source_app="mytool",
                source_kind="message",
                source_path=str(path),
                ordinal=i,
                role=msg.get("role", "user"),
                text=text,
                timestamp=msg.get("timestamp"),
                title=truncate(text, 120),
                metadata={},
            ))

        return session, entries

    def default_root(self) -> Path | None:
        return Path.home() / ".mytool" / "data"
```

### Step 2: Register via entry_points

In your package's `pyproject.toml`:

```toml
[project.entry-points."engram.parsers"]
mytool = "my_parser.parser:MyToolParser"
```

### Step 3: Configure in Engram

After installing your package, add the source to `.engram/config.toml`:

```toml
[sources.mytool]
enabled = true
path = "~/.mytool/data"
parser = "mytool"
```

Run `engram sync` and your tool's data will be indexed.

### Available utility functions

The `engram.parsers.base` module provides several helpers for parser authors:

| Function | Description |
|----------|-------------|
| `normalize_text(text)` | Collapse whitespace runs and excessive blank lines |
| `truncate(text, max_len=200)` | Truncate with ellipsis |
| `build_qa_entries(session, entries)` | Pair consecutive user/assistant messages into Q&A chunks |
| `build_paragraph_entries(session, text, source_path, base_title)` | Split long text into 4000-character paragraph chunks |
| `split_markdown_sections(text)` | Split Markdown by `##` headings into `(heading, content)` tuples |

### Tips for parser development

- **Return empty entries gracefully.** If a file has no usable content, return `(session, [])`. The sync engine will skip it.
- **Use `normalize_text`** on all text before storing. This keeps the FTS index clean.
- **Derive titles from content.** A good title (first user message, document heading, filename) makes search results much more useful.
- **Set timestamps.** Time decay depends on accurate timestamps. Use ISO 8601 format with timezone.
- **Use `source_kind` consistently.** This field helps downstream tools understand what kind of content they are looking at.
- **Handle encoding.** Always open files with `encoding="utf-8", errors="replace"` to avoid crashes on malformed files.

## Parser discovery internals

When `engram sync` runs, it calls `get_parser(name)` for each configured source. The lookup order is:

1. Built-in parsers (checked first by name)
2. Entry points in the `engram.parsers` group (checked via `importlib.metadata.entry_points`)

If no parser matches the name, a `ValueError` is raised and the source is skipped with an error.

You can list all built-in parsers programmatically:

```python
from engram.parsers import list_parsers
print(list_parsers())  # ['claude', 'codex', 'gemini', 'vault', 'vscode']
```
