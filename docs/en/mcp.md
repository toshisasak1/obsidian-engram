# MCP Integration Guide

Engram exposes its search capabilities through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) so that AI tools can query your indexed conversations and vault documents during a session. This guide covers setup, tool details, and usage patterns for Claude Code, Codex CLI, and other MCP-compatible clients.

## What is MCP?

MCP is a JSON-RPC 2.0-based protocol that lets AI assistants call external tools during a conversation. Engram's MCP server runs as a stdio subprocess: the AI client launches it, sends JSON-RPC requests over stdin, and reads responses from stdout. All diagnostic logging goes to stderr to avoid contaminating the transport.

Engram implements the `2024-11-05` protocol version.

## Quick setup

### 1. Install Engram

```bash
pip install obsidian-engram
```

### 2. Initialize and sync

```bash
cd ~/my-vault
engram init
engram sync
```

### 3. Register the MCP server

Add the following to your AI tool's MCP configuration (details for each tool below):

```json
{
  "mcpServers": {
    "engram": {
      "command": "engram",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

That is it. The AI tool will start the Engram MCP server automatically when it needs to call a memory tool.

## Setup by AI tool

### Claude Code

Add to `~/.claude/settings.json` (global) or `.claude/settings.json` (per-project):

```json
{
  "mcpServers": {
    "engram": {
      "command": "engram",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

After saving, start a new Claude Code session. You should see Engram's five tools available. You can verify by asking Claude to run `memory_status`.

**Tip**: If you installed Engram in a virtual environment, use the full path to the `engram` binary:

```json
{
  "mcpServers": {
    "engram": {
      "command": "/home/you/.local/bin/engram",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

### Codex CLI

Codex CLI supports MCP servers via its configuration. Add Engram in the same format:

```json
{
  "mcpServers": {
    "engram": {
      "command": "engram",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

Consult the Codex CLI documentation for the exact config file location for your version.

### Other MCP clients

Any tool that supports the MCP stdio transport can use Engram. The essential configuration is:

- **Command**: `engram`
- **Arguments**: `["mcp"]`
- **Transport**: stdio (stdin/stdout with Content-Length framing)
- **Protocol**: JSON-RPC 2.0, MCP version `2024-11-05`

## MCP tools reference

Engram exposes five tools. Below is the complete specification for each.

### `memory_search`

Search across all indexed AI conversation history and vault documents.

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query (keywords or natural language)"
    },
    "limit": {
      "type": "integer",
      "description": "Maximum results to return",
      "default": 10
    },
    "source_app": {
      "type": "string",
      "description": "Filter by source: claude, codex, gemini, vault"
    },
    "tags": {
      "type": "string",
      "description": "Comma-separated tags to filter results (e.g. 'python,trading')"
    }
  },
  "required": ["query"]
}
```

**Output**: Markdown-formatted search results with ranked entries. Each entry includes:
- Source app and session title
- Score (fused RRF + time decay)
- Timestamp
- Session key
- Text snippet

**Example response**:

```markdown
### 1. [claude] Fix API gateway timeout issue
- Score: 0.847
- Time: 2026-04-03T14:22:00Z
- Session: claude:abc123

...we switched from the blue-green deployment to a canary strategy because
the health checks were timing out during the full cutover...

### 2. [vault] Deployment Guide
- Score: 0.612
- Time: 2026-03-15
- Session: vault:/home/you/my-vault/deploy-guide.md

...the gateway module now supports weighted routing...
```

### `memory_brief`

Generate a context brief for the current workspace. Returns recent sessions and keyword matches relevant to the working directory.

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "workspace": {
      "type": "string",
      "description": "Workspace path (defaults to current directory)"
    },
    "queries": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Additional search terms"
    }
  }
}
```

**Output**: A Markdown document with two sections:

1. **Recent Sessions**: Sessions whose `cwd`, `project`, or `source_path` matches the workspace, with highlight snippets.
2. **Keyword Matches**: FTS search results for workspace-derived terms plus any extra queries.

**When to use**: At the start of a session to get context about what was discussed recently in this workspace.

### `memory_status`

Show knowledge base statistics.

**Input schema**:

```json
{
  "type": "object",
  "properties": {}
}
```

**Output**: JSON with counts of sessions, entries, FTS rows, embeddings, source files, per-source session counts, and paths.

**Example response**:

```json
{
  "sessions": 142,
  "entries": 3847,
  "source_files": 89,
  "fts_rows": 3847,
  "embeddings": 0,
  "schema_version": 1,
  "sources": {
    "claude": 98,
    "codex": 31,
    "vault": 13
  },
  "db_path": "/home/you/my-vault/.engram/engram.db",
  "vault_path": "/home/you/my-vault"
}
```

### `memory_tag`

Tag untagged entries in the database using keyword rules and/or AI CLI tools.

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
      "description": "Maximum entries to process",
      "default": 50
    }
  }
}
```

**Output**: A summary of the tagging run with counts of processed, tagged, skipped, and errored entries.

**When to use**: Before a filtered search (`memory_search` with `tags`) to ensure entries are tagged. Also useful as a periodic maintenance operation.

### `memory_list_sessions`

List recent conversation sessions with titles and timestamps.

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "default": 20,
      "description": "Maximum sessions to return"
    },
    "source_app": {
      "type": "string",
      "description": "Filter by source app"
    }
  }
}
```

**Output**: A Markdown list of sessions, each with source app, title, last-updated timestamp, working directory, and session key.

## How AI tools use Engram

Once registered, the AI tool can call Engram's tools automatically during conversation. Here are common patterns:

### Pattern: Session startup recall

At the start of a conversation, the AI calls `memory_brief` to get context:

```
AI internally calls: memory_brief(workspace="/home/you/project-x")
```

The AI receives a summary of recent sessions related to `project-x` and can reference past decisions without you re-explaining.

### Pattern: Mid-conversation search

When you mention something discussed in a previous session:

```
You: "What was the migration approach we settled on last week?"
AI internally calls: memory_search(query="migration approach")
```

The AI finds the relevant conversation snippet and synthesizes an answer.

### Pattern: Cross-tool knowledge

You discussed architecture with Claude, wrote Terraform with Codex, and documented decisions in Obsidian. A single `memory_search` query searches across all three.

### Pattern: Source-specific lookup

When you know which tool the conversation happened in:

```
You: "Find the Codex session where we set up the CI pipeline"
AI internally calls: memory_search(query="CI pipeline setup", source_app="codex")
```

## Running the MCP server manually

For debugging or testing, you can run the server directly:

```bash
engram mcp
```

The server reads JSON-RPC messages from stdin and writes responses to stdout. Use Content-Length framing:

```
Content-Length: 123\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
```

### Testing with a simple script

```python
import json
import subprocess
import sys

proc = subprocess.Popen(
    ["engram", "mcp"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)

def send(msg):
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n"
    proc.stdin.write(header.encode() + body)
    proc.stdin.flush()

def recv():
    # Read Content-Length header
    line = proc.stdout.readline().decode()
    length = int(line.split(":")[1].strip())
    proc.stdout.readline()  # blank line
    body = proc.stdout.read(length)
    return json.loads(body)

# Initialize
send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
print(recv())

# Search
send({
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "memory_search",
        "arguments": {"query": "deployment strategy"}
    }
})
print(recv())
```

## Server lifecycle

1. **initialize**: The client sends `initialize`. Engram responds with its server info and capabilities.
2. **notifications/initialized**: The client acknowledges. Engram ignores this (no-op).
3. **tools/list**: The client requests available tools. Engram returns all four tool definitions.
4. **tools/call**: The client invokes a tool. Engram executes it and returns the result.
5. **ping**: Health check. Engram responds with an empty result.
6. **EOF**: When stdin closes, the server shuts down cleanly.

## Environment and path resolution

The MCP server loads configuration using the same layered resolution as the CLI:

1. Global config
2. Project config (from the vault path)
3. Environment variables

When the server is started by an AI tool, it inherits the environment of the parent process. Make sure `ENGRAM_DB_PATH` or `ENGRAM_VAULT_PATH` are set if your vault is not in the current directory.

If your AI tool changes the working directory per session (as Claude Code does), Engram auto-detects the vault by walking upward from `cwd` looking for `.obsidian/` or `.engram/`.

## Troubleshooting

### "MCP server module not available"

The `engram` package is installed but the MCP module cannot be imported. Reinstall:

```bash
pip install --force-reinstall obsidian-engram
```

### "Database not found"

The MCP server could not locate the database. This usually means the vault path is not set. Solutions:

1. Set `ENGRAM_VAULT_PATH` in the `env` block of your MCP config:

```json
{
  "mcpServers": {
    "engram": {
      "command": "engram",
      "args": ["mcp"],
      "env": {
        "ENGRAM_VAULT_PATH": "/home/you/my-vault"
      }
    }
  }
}
```

2. Or set `ENGRAM_DB_PATH` directly:

```json
{
  "env": {
    "ENGRAM_DB_PATH": "/home/you/my-vault/.engram/engram.db"
  }
}
```

### No results returned

- Run `engram status` to verify the database has entries.
- Run `engram sync` to pull in recent conversations.
- Try a simple keyword search with `engram search "test"` from the CLI to confirm the index is working.

### Server logs

All MCP server logs go to stderr. To capture them, redirect stderr:

```bash
engram mcp 2>/tmp/engram-mcp.log
```

Or in your MCP config, set a wrapper script that captures logs.

### Virtual environment issues

If `engram` is installed in a virtual environment that the AI tool does not activate, use the absolute path to the binary:

```json
{
  "command": "/home/you/venvs/engram/bin/engram",
  "args": ["mcp"]
}
```

On Windows:

```json
{
  "command": "C:\\Users\\you\\venvs\\engram\\Scripts\\engram.exe",
  "args": ["mcp"]
}
```
