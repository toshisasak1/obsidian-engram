# Getting Started

This guide walks you through installing Engram, initializing it in your Obsidian vault, syncing your first conversation logs, and running your first search.

## Prerequisites

- **Python 3.10 or later**. Check with `python --version`.
- **SQLite with FTS5** (included in all standard CPython builds since 3.6).
- **Obsidian** (optional -- Engram works standalone too).

You will also need at least one AI tool whose conversation logs Engram can index:

| Tool | Data directory |
|------|----------------|
| Claude Code | `~/.claude/projects/` |
| Codex CLI | `~/.codex/` |
| Gemini CLI | `~/.gemini/antigravity/brain/` |

Engram auto-detects these directories during initialization.

## Installation

### Basic install (FTS5 keyword search only)

```bash
pip install obsidian-engram
```

This installs the `engram` CLI with no extra dependencies beyond `click` and (on Python 3.10) `tomli`.

### With local vector embeddings

```bash
pip install obsidian-engram[embeddings]
```

This adds `sentence-transformers`, `sqlite-vec`, and `numpy`. The default model (`all-MiniLM-L6-v2`) is roughly 80 MB and runs on CPU.

### With OpenAI or Voyage API embeddings

```bash
pip install obsidian-engram[openai]
```

You will need to set the `ENGRAM_EMBEDDING_API_KEY` environment variable or add your key to the config file.

### Verify the installation

```bash
engram --version
```

## Initializing your vault

Navigate to your Obsidian vault (or any directory) and run:

```bash
cd ~/my-vault
engram init
```

The `init` command does several things in sequence:

1. **Detects your vault.** If the current directory contains `.obsidian/`, Engram recognizes it as a vault. Otherwise it runs in standalone mode.
2. **Discovers AI tools.** It probes `~/.claude/projects`, `~/.codex`, and `~/.gemini/antigravity/brain` for directories that exist on your machine.
3. **Creates `.engram/config.toml`.** This is the project configuration file. Every setting is documented inline.
4. **Creates the database.** The SQLite file lands at `.engram/engram.db`.
5. **Copies identity templates.** Four files (`SOUL.md`, `USER.md`, `AGENTS.md`, `TOOLS.md`) are placed in the vault root. See the [Identity Framework](identity.md) guide.
6. **Runs the first sync.** All discovered sources are immediately indexed.

### Interactive confirmation

By default, `engram init` asks for confirmation before modifying anything:

```
Detected Obsidian vault: /home/you/my-vault
Discovered AI tool sources: claude, codex

This will:
  - Create .engram/ directory in /home/you/my-vault
  - Initialize database at /home/you/my-vault/.engram/engram.db
  - Copy template files to /home/you/my-vault
  - Run initial sync of 2 source(s)

Proceed? [Y/n]
```

Pass `--yes` (or `-y`) to skip the prompt:

```bash
engram init --yes
```

### Standalone mode (no Obsidian)

If you want to use Engram without an Obsidian vault:

```bash
engram init --no-vault
```

This skips identity template creation and vault knowledge indexing. Everything else works the same.

### Specifying a vault path explicitly

```bash
engram init --vault /path/to/your/vault
```

## After initialization

Your vault now contains:

```
my-vault/
  .engram/
    config.toml          # Edit this to tune behavior
    engram.db            # SQLite database
  SOUL.md                # AI identity guidelines
  USER.md                # Your profile for AI context
  AGENTS.md              # Session startup checklist
  TOOLS.md               # Local environment documentation
```

The `.engram/` directory can safely be added to `.gitignore`. The identity files (`SOUL.md`, `USER.md`, `AGENTS.md`, `TOOLS.md`) are intended for version control.

## Syncing conversation logs

After the initial sync, use `engram sync` whenever you want to pull in new conversations:

```bash
engram sync
```

Output:

```
Sync complete: 47 scanned, 12 indexed, 35 skipped, 0 errors
```

- **scanned**: total files examined
- **indexed**: files that had new or changed content
- **skipped**: files that were unchanged since the last sync
- **errors**: files that could not be parsed

### Sync a single source

```bash
engram sync --source claude
```

### Skip embedding generation

If embeddings are enabled but you want a fast text-only sync:

```bash
engram sync --skip-embeddings
```

### Continuous sync (watch mode)

To keep the index updated in the background:

```bash
engram watch
```

This polls for changes at the interval set in `config.toml` (default: 30 seconds). Press `Ctrl+C` to stop.

You can also log watch output to a file:

```bash
engram watch --log /tmp/engram-watch.log
```

## Searching your memory

```bash
engram search "deployment strategy for the API gateway"
```

Output:

```
--- 1. [claude] Fix API gateway timeout issue (score: 0.847) ---
...we switched from the blue-green deployment to a canary strategy because
the health checks were timing out during the full cutover...

--- 2. [codex] Terraform module for gateway infra (score: 0.612) ---
...the gateway module now supports weighted routing. Set canary_weight to
control traffic split during deployments...
```

### Limit results

```bash
engram search "database migration" --limit 5
```

### Filter by source

```bash
engram search "type hints" --source claude
```

### JSON output

For programmatic use:

```bash
engram search "error handling" --json
```

Returns a JSON array with `entry_id`, `session_key`, `source_app`, `role`, `snippet`, `score`, `timestamp`, and `session_title` for each result.

## Checking database status

```bash
engram status
```

Output:

```
Database:   /home/you/my-vault/.engram/engram.db
Vault:      /home/you/my-vault
Schema:     v1
Sessions:   142
Entries:    3847
FTS rows:   3847
Embeddings: 0
Src files:  89
Sources:
  claude: 98 sessions
  codex: 31 sessions
  vault: 13 sessions
```

For machine-readable output:

```bash
engram status --json
```

## Generating a context brief

The `brief` command creates a workspace-aware summary of recent sessions:

```bash
engram brief
```

This examines the current working directory, finds sessions whose `cwd` or `project` matches, and produces a Markdown summary of recent activity and keyword matches.

### Target a specific workspace

```bash
engram brief --workspace /path/to/project
```

### Add extra search terms

```bash
engram brief -q "migration" -q "rollback plan"
```

### Save to file

```bash
engram brief --output context.md
```

## Next steps

- **[Configuration Reference](configuration.md)** -- customize search tuning, sources, and embeddings.
- **[Auto-Tagging](tagging.md)** -- tag entries with keyword rules or AI-powered CLI tagging.
- **[MCP Integration Guide](mcp.md)** -- connect Engram to Claude Code, Codex, or any MCP client.
- **[Search Algorithm](search.md)** -- understand how FTS5, vector search, RRF fusion, and time decay work together.
- **[Identity Framework](identity.md)** -- set up SOUL.md, USER.md, AGENTS.md, and TOOLS.md.

## Troubleshooting

### "Database not found" error

You need to run `engram init` first, or your current directory is not inside the vault. Engram walks upward from the current directory looking for `.obsidian/` or `.engram/` to find the vault root.

### No sources detected

Engram looks for standard data directories (`~/.claude/projects`, `~/.codex`, `~/.gemini/antigravity/brain`). If your AI tools store data elsewhere, add custom paths in `.engram/config.toml`:

```toml
[sources.claude]
enabled = true
path = "/custom/path/to/claude/projects"
```

### FTS5 not available

This is extremely rare with standard Python builds. If you see a warning about FTS5, your Python was compiled without the FTS5 extension. Reinstall Python from python.org or use `pyenv` to build with the default configuration.

### Sync errors

Run sync with verbose output to see what went wrong:

```bash
engram sync --verbose
```

Common causes:
- Malformed JSONL files (truncated writes, encoding issues)
- Files still being written by another process (the settle timer handles this, but very large files may need a longer `settle_seconds` value in config)
