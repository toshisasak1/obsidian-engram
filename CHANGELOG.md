# Changelog

## [0.1.0] - 2026-04-05

### Added
- Initial release
- FTS5 full-text search with trigram tokenizer (CJK support)
- Hybrid search: FTS5 + vector with RRF fusion and time decay
- Parsers: Claude Code, Codex CLI, Gemini CLI, Obsidian vault
- CLI: `engram init`, `sync`, `search`, `brief`, `status`, `watch`, `mcp`
- MCP server with 4 tools (memory_search, memory_brief, memory_status, memory_list_sessions)
- Optional vector embeddings (local or API-based)
- One-command setup with auto-discovery
- Vault template with identity framework (SOUL.md, USER.md, AGENTS.md, TOOLS.md)
- Bilingual documentation (English / Japanese)
