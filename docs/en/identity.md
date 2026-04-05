# Identity Framework

Engram's identity framework is a set of four Markdown files placed in your vault root during `engram init`. They provide persistent context that AI tools read at the start of every session, bridging the gap between sessions where the AI would otherwise start from zero.

## The four files

| File | Purpose | Audience |
|------|---------|----------|
| `SOUL.md` | AI identity and behavioral guidelines | The AI reads this to know how to behave |
| `USER.md` | About you -- your profile for AI context | The AI reads this to know who it is helping |
| `AGENTS.md` | Session startup checklist | The AI reads this to know what to do first |
| `TOOLS.md` | Local environment documentation | The AI reads this to know what tools are available |

These files are templates. They are yours to edit, extend, or replace entirely. Engram provides starting points; you make them useful.

## How AI tools discover these files

AI tools that operate inside your vault (Claude Code, Codex CLI, etc.) typically read top-level Markdown files as part of their context window. By placing identity files at the vault root, they are naturally picked up without any special configuration.

If the AI tool supports Engram via MCP, the `memory_brief` tool also references session history from the workspace, complementing the static identity files with dynamic recall.

## SOUL.md -- AI identity

This file defines how the AI should behave when working in your vault. The default template establishes five core principles:

### Default template content

**Be genuinely helpful.** Skip filler. Get to the answer.

**Be resourceful.** Before asking, try to find the answer by reading files, searching memory, and checking context.

**Earn trust through competence.** Be careful with anything leaving the machine. Be bold with everything inside it.

**Have opinions.** If the AI sees a better way, it should say so. Disagree respectfully.

**Remember you are a guest.** The workspace contains personal and professional data. Treat it with respect.

### Customization ideas

The default is deliberately opinionated. Here are ways to adapt it:

**For a coding-focused workflow**:
```markdown
## Code Principles
- Follow existing conventions in the codebase
- Write tests for new functionality
- Prefer small, focused commits
- Never push to main without asking
```

**For a writing-focused workflow**:
```markdown
## Writing Style
- Match my voice: direct, informal, no corporate speak
- First drafts can be rough -- I will refine
- Cite sources when making factual claims
- Default language: English, unless I write in Japanese
```

**For a research workflow**:
```markdown
## Research Guidelines
- Always note the source of information
- Distinguish between facts and speculation
- When uncertain, say so explicitly
- Prefer primary sources over summaries
```

### Memory integration

The template includes a Memory section that tells the AI about the four identity files and Engram's MCP tools:

```markdown
## Memory

You forget between sessions. These files are your continuity:
- `SOUL.md` -- Who you are (this file)
- `USER.md` -- Who you're helping
- `AGENTS.md` -- How to start a session
- `TOOLS.md` -- What's available in this environment

If engram is installed, use `memory_search` and `memory_brief` to recall past conversations.
```

### Boundaries

The template sets explicit boundaries:

```markdown
## Boundaries
- Private things stay private
- Ask before sending emails, posting online, or any external action
- Prefer `trash` over permanent `delete`
- When unsure, ask
```

Customize these based on your comfort level. If you want the AI to be more autonomous, relax them. If you want tighter control, make them stricter.

## USER.md -- Your profile

This file tells the AI who you are. It starts mostly empty because only you know this information.

### Template structure

```markdown
# USER.md -- About Me

## Name
<!-- Your name or preferred handle -->

## Work
<!-- What you do. What you're building. What matters to you right now. -->

## Preferences
<!-- How you like to communicate. Your timezone. Languages. Tools you use daily. -->

## Notes
<!-- Anything else that would help AI understand your context. -->
```

### Example of a filled-in USER.md

```markdown
# USER.md -- About Me

## Name
Alex

## Work
Backend engineer at a startup building developer tools. Currently focused on
a Rust CLI for database migrations. Side project: an Obsidian plugin for
time tracking.

## Preferences
- Timezone: JST (UTC+9)
- Languages: English primary, Japanese for documentation
- Communication: direct, no small talk, code examples over descriptions
- Editor: VS Code with Vim bindings
- Shell: zsh on macOS, bash in CI

## Notes
- I context-switch between the migration CLI and the Obsidian plugin daily
- Pet peeve: unnecessary abstractions and premature optimization
- Currently learning Nix for reproducible builds
- Recurring meetings: standup 10am, arch review Wednesdays
```

### Why this matters

Without USER.md, the AI makes generic assumptions. With it, the AI can:
- Write code examples in your preferred language and style
- Adjust timestamps to your timezone
- Understand your current priorities and context-switch with you
- Avoid suggesting tools or approaches you dislike

## AGENTS.md -- Session startup

This file is a checklist the AI should follow at the start of every session.

### Default template

```markdown
# AGENTS.md -- Session Startup

## Checklist
1. Read `SOUL.md` -- your identity and principles
2. Read `USER.md` -- who you're helping
3. If engram MCP is available, call `memory_brief` for this workspace
4. Check for `memory/` daily notes if they exist

## Memory Rules
- If something is worth remembering, **write it to a file**
- "Mental notes" don't survive session restarts
- Use `memory/YYYY-MM-DD.md` for daily activity logs
- Important decisions and lessons go in dedicated notes

## When in Doubt
- Read before writing
- Search before asking
- Think before acting
- Ask before anything external
```

### Customization ideas

**Add project-specific context**:
```markdown
## Current Focus
- Sprint goal: ship v2.0 of the migration CLI by April 15
- Blocked on: schema diff algorithm performance (see memory/2026-04-01.md)
- Recent decision: switched from SQLx to rusqlite (see decision-log.md)
```

**Add workflow-specific steps**:
```markdown
## Before Writing Code
1. Check `CHANGELOG.md` for recent changes
2. Run `git log --oneline -10` to see recent commits
3. Search memory for related past discussions
4. Read the relevant test files before modifying source
```

**Add recurring reminders**:
```markdown
## Weekly Tasks
- Monday: review and triage GitHub issues
- Friday: update STATUS.md with week summary
```

## TOOLS.md -- Environment documentation

This file documents what tools, scripts, and infrastructure are available on your machine.

### Template structure

```markdown
# TOOLS.md -- Local Environment

## System
<!-- OS, shell, package managers, Python version -->

## AI Tools
<!-- Which AI CLIs do you use? Claude Code, Codex, Gemini? -->

## Active Projects
<!-- What are you working on? Where are the repos? -->

## Custom Tools
<!-- Scripts, aliases, MCP servers, browser automation, etc. -->
```

### Example of a filled-in TOOLS.md

```markdown
# TOOLS.md -- Local Environment

## System
- macOS 15.2 (M3 Pro)
- Shell: zsh with oh-my-zsh
- Homebrew, nix (experimental), rustup
- Python 3.13 via pyenv
- Node 22 via nvm

## AI Tools
- Claude Code (latest, global install)
- Codex CLI (latest)
- Engram MCP server registered in Claude Code

## Active Projects
- `~/code/migrate-cli` -- Rust CLI for DB migrations (main project)
- `~/code/obsidian-timetrack` -- Obsidian plugin for time tracking
- `~/vault` -- This Obsidian vault

## Custom Tools
- `~/scripts/deploy.sh` -- Deploy migration CLI to staging
- `~/scripts/bench.sh` -- Run benchmarks and save results
- MCP servers: engram, filesystem, git-tools
- Tailscale for remote access to dev server (100.x.x.x)

## Database Access
- Local Postgres: localhost:5432, user=dev, db=migrate_dev
- Staging: via `ssh staging-01` then `psql`
- Never touch production directly

## Notes
- The migration CLI repo uses `just` instead of `make`
- CI runs on GitHub Actions, secrets in 1Password
```

### Why this matters

Without TOOLS.md, the AI might suggest installing software you already have, use the wrong package manager, or miss custom scripts that would save time. With it, the AI operates within your actual environment.

## Version control

The identity files are designed to be version-controlled:

```bash
git add SOUL.md USER.md AGENTS.md TOOLS.md
git commit -m "Add Engram identity files"
```

The `.engram/` directory (containing the database and config) should typically be in `.gitignore`:

```
.engram/
```

Tracking the identity files lets you:
- See how your AI configuration evolves over time
- Share baseline configurations with teammates
- Roll back to a previous version if something breaks

## Updating identity files

You can edit these files at any time with any text editor. Changes take effect immediately -- the next time an AI tool reads the file, it sees the updated content.

If you delete an identity file and want to restore the template:

```python
from engram.identity import install_identity_files
from pathlib import Path

install_identity_files(Path("/path/to/vault"), overwrite=False)
```

This only creates files that do not exist. Pass `overwrite=True` to replace existing files with the defaults.

## Checking identity file status

```python
from engram.identity import check_identity_files
from pathlib import Path

status = check_identity_files(Path("/path/to/vault"))
print(status)
# {'SOUL.md': True, 'USER.md': True, 'AGENTS.md': True, 'TOOLS.md': False}
```

## Multi-vault setups

If you have multiple vaults (personal, work, project-specific), each vault gets its own set of identity files. This lets you maintain different AI behavior profiles:

- **Personal vault**: Casual tone, broad autonomy, personal context
- **Work vault**: Professional tone, stricter boundaries, work-specific tools
- **Project vault**: Focused on a single project, detailed TOOLS.md for that stack

Each vault also gets its own Engram database, so searches are scoped to the conversations and documents relevant to that context.

## Tips

- **Start small.** Fill in USER.md and TOOLS.md with the basics. You can always add more later.
- **Update after decisions.** When you and the AI make an important decision, add it to AGENTS.md or a dedicated decision log.
- **Keep SOUL.md short.** The AI reads it at every session start. Long files consume context window space.
- **Use TOOLS.md for gotchas.** Document things like "the staging server requires VPN" or "use `just` not `make` in this repo". These save time on every session.
- **Do not put secrets in these files.** No API keys, passwords, or tokens. Use environment variables or secret managers instead.
