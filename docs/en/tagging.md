# Auto-Tagging

Engram can automatically tag indexed entries with descriptive labels like `python`, `docker`, `trading`, or `assistant`. Tags enable filtered search -- find only entries that match specific topics or categories.

## Overview

Tagging runs separately from sync. After entries are indexed, you tag them:

```bash
engram tag
```

Two backends are available:

| Backend | How it works | Cost | Speed |
|---------|-------------|------|-------|
| `keyword` | Rule-based pattern matching (built-in + custom rules) | Free | Instant |
| `cli` | Sends batches to `claude -p` or `codex -q` for AI-powered tagging | Account subscription only (no per-call API cost) | ~10-90s per batch |

You can use either backend alone, or both together (`"both"` mode runs keyword first, then CLI for additional tags).

## Configuration

Add a `[tagging]` section to `.engram/config.toml`:

```toml
[tagging]
enabled = true
provider = "keyword"       # "keyword", "cli", or "both"
batch_size = 50
max_tags = 5

[tagging.cli]
command = "claude"         # "claude" or "codex"
timeout = 120              # seconds per batch

# Custom keyword rules (optional)
[tagging.rules]
python = ["python", "pip", "venv", "pytest"]
trading = ["forex", "gmma", "ema", "bot", "backtest"]
devops = ["docker", "kubernetes", "terraform", "ci/cd"]
```

### Settings reference

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `false` | Enable the tagging feature |
| `provider` | `"keyword"` | Which backend to use: `"keyword"`, `"cli"`, or `"both"` |
| `batch_size` | `50` | Max entries to process per run |
| `max_tags` | `5` | Maximum tags per entry |
| `cli.command` | `"claude"` | CLI tool for AI tagging: `"claude"` or `"codex"` |
| `cli.timeout` | `120` | Timeout (seconds) for each CLI batch call |
| `rules.*` | (built-in) | Custom keyword-to-tag mapping rules |

## Keyword tagger

The keyword tagger assigns tags based on pattern matching with zero external dependencies.

### Tag sources (in order of priority)

1. **Source app**: The tool that produced the entry (`claude`, `codex`, `gemini`, `vault`)
2. **Role**: The entry's role (`user`, `assistant`, `qa`, `document`)
3. **Project name**: Extracted from the source file path (e.g., `obsidian-engram` from `~/.claude/projects/obsidian-engram/...`)
4. **Custom rules**: Your `[tagging.rules]` definitions -- word-boundary regex matching
5. **Built-in rules**: Common technology keywords (python, javascript, docker, git, sql, etc.)

### Built-in keyword categories

| Tag | Matching keywords |
|-----|-------------------|
| `python` | python, pip, venv, pytest, django, flask, fastapi |
| `javascript` | javascript, typescript, node, npm, react, vue, angular |
| `rust` | rust, cargo, crate |
| `go` | golang, go mod |
| `sql` | sql, sqlite, postgres, mysql, database, migration |
| `docker` | docker, container, dockerfile, compose |
| `git` | git, commit, branch, merge, rebase, pull request |
| `api` | api, rest, graphql, endpoint, grpc |
| `testing` | test, unittest, pytest, jest, spec, coverage |
| `devops` | deploy, ci/cd, pipeline, kubernetes, terraform |

### Custom rules

Define your own keyword-to-tag mappings:

```toml
[tagging.rules]
trading = ["forex", "gmma", "ema", "bot", "backtest"]
ml = ["machine learning", "neural", "model training", "dataset"]
```

Keywords use word-boundary matching (`\b`), so `"python"` matches "python" but not "pythonic".

## CLI tagger

The CLI tagger sends entry text to an AI tool for higher-quality tagging. It uses your existing Claude Code or Codex CLI subscription -- no additional API charges.

### How it works

1. Collects a batch of untagged entries
2. Builds a prompt asking the AI to generate tags as JSON
3. Runs `claude -p "..."` or `codex -q "..."` as a subprocess
4. Parses the JSON response and stores the tags
5. If the CLI call fails (timeout, parse error), logs the error and skips the batch

### Prerequisites

- **Claude**: `claude` CLI must be installed and authenticated (`claude auth login`)
- **Codex**: `codex` CLI must be installed and authenticated

The CLI tagger inherits your existing subscription authentication. There is no per-call API cost.

## CLI usage

### Tag untagged entries

```bash
# Use the configured provider
engram tag

# Override the provider
engram tag --provider keyword
engram tag --provider cli
engram tag --provider both

# Process more entries
engram tag --batch-size 200

# Show progress
engram tag --verbose
```

### Search with tag filter

```bash
# Find only entries tagged "python"
engram search "error handling" --tag python

# Multiple tags (OR match)
engram search "deployment" --tag docker,devops
```

### Check tag statistics

```bash
engram status
```

Output includes a `Tagged:` line showing how many entries have been tagged.

## MCP tools

### `memory_tag`

Trigger tagging from any MCP client (Claude Code, Codex, Gemini/Antigravity).

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "provider": {
      "type": "string",
      "enum": ["keyword", "cli", "both"],
      "description": "Tagging method (default: from config)"
    },
    "batch_size": {
      "type": "integer",
      "description": "Max entries to process",
      "default": 50
    }
  }
}
```

**Example**: An AI assistant can call `memory_tag` to ensure entries are tagged before performing a filtered search.

### `memory_search` with tags

The `memory_search` tool accepts an optional `tags` parameter:

```json
{
  "query": "error handling",
  "tags": "python,testing"
}
```

This returns only entries that have at least one of the specified tags.

## Scheduled tagging

For automatic tagging, schedule `engram tag` to run periodically.

### Windows Task Scheduler

Use the provided `scripts/engram-tag.bat`:

```bat
schtasks /create /tn "Engram Tag Morning" /tr "path\to\engram-tag.bat" /sc daily /st 10:30
schtasks /create /tn "Engram Tag Night"   /tr "path\to\engram-tag.bat" /sc daily /st 00:00
```

### Linux/macOS cron

```cron
30 10 * * * engram tag --provider both --batch-size 200
0  0  * * * engram tag --provider both --batch-size 200
```

The batch script runs keyword tagging first (instant), then CLI tagging (uses your subscription).

## Database schema

Tags are stored in the `entry_tags` table:

```sql
CREATE TABLE entry_tags (
    entry_id   TEXT NOT NULL REFERENCES entries(entry_id) ON DELETE CASCADE,
    tag        TEXT NOT NULL,
    method     TEXT NOT NULL DEFAULT 'keyword',  -- 'keyword' or 'cli'
    tagged_at  TEXT NOT NULL,
    PRIMARY KEY (entry_id, tag)
);
```

- Tags are lowercased and deduplicated
- Deleting an entry automatically cascades to its tags
- The `method` column records which backend assigned each tag
