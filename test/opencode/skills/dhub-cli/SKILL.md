---
name: dhub-cli
description: Guide for using the dhub CLI — the AI skill manager for data science agents. Covers authentication, publishing, installing, running skills, managing API keys, eval reports, and troubleshooting. Use when users ask about dhub commands, skill publishing workflows, or need help with the Decision Hub CLI.
---
# dhub CLI Guide

`dhub` is the AI skill manager for data science agents. It publishes, discovers, installs, and runs Skills — modular packages (code + prompts) that agents like Claude Code, Cursor, Codex, and Windsurf can use.

## Installation

```bash
uv tool install dhub-cli    # via uv (recommended)
pipx install dhub-cli       # via pipx
```

## Command Overview

```
dhub login              Authenticate via GitHub
dhub logout             Remove stored token
dhub env                Show active environment, config path, API URL
dhub init [path]        Scaffold a new skill project
dhub publish [ref]      Publish skill(s) — from dir or git repo
dhub install org/skill  Install a skill from the registry
dhub uninstall org/skill  Remove a locally installed skill
dhub list               List all published skills
dhub delete org/skill   Delete skill versions from registry
dhub run org/skill      Run a locally installed skill
dhub ask "query"        Natural language skill search
dhub eval-report org/skill@version  View eval report
dhub logs [ref] [-f]    View or tail eval run logs
dhub org list           List your namespaces
dhub config default-org Set default namespace for publishing
dhub keys add <name>    Store an API key for evals
dhub keys list          List stored API key names
dhub keys remove <name> Remove a stored API key
dhub doctor             Check auth, API connectivity, version
dhub --version          Show CLI version
dhub --output json CMD  Machine-readable JSON output for any command
```

See `references/command_reference.md` for full details on every command, flag, and option.

## Environments (Dev / Prod)

dhub supports two independent stacks controlled by `DHUB_ENV`:

| Env | API URL | Config File |
|-----|---------|-------------|
| `prod` (default) | `https://lfiaschi--api.modal.run` | `~/.dhub/config.prod.json` |
| `dev` | `https://lfiaschi--api-dev.modal.run` | `~/.dhub/config.dev.json` |

Always prefix commands with `DHUB_ENV=dev` when working against the dev stack:

```bash
DHUB_ENV=dev dhub login
DHUB_ENV=dev dhub list
DHUB_ENV=dev dhub publish
```

The `dhub env` command shows the currently active environment, config path, and API URL.

## Authentication

dhub uses GitHub Device Flow (OAuth2). Run `dhub login` and follow the prompts:

1. dhub requests a device code from the server
2. You open `https://github.com/login/device` and enter the displayed code
3. dhub polls until you authorize (up to 5 minutes)
4. Token is saved to `~/.dhub/config.{env}.json`

All subsequent commands use this token automatically. Run `dhub logout` to clear it.

You can override the API URL with `dhub login --api-url <url>` for custom deployments.

## Publishing Workflow

### Quick publish (auto-detect everything)

From a directory containing a valid SKILL.md:

```bash
dhub publish              # auto-detects org, name, bumps patch version
dhub publish --minor      # bump minor version instead
dhub publish --major      # bump major version
dhub publish --version 2.0.0  # explicit version
```

### Explicit publish

```bash
dhub publish myorg/my-skill          # specify org/skill, auto-bump patch
dhub publish myorg/my-skill ./path   # specify path to skill directory
```

### How auto-detection works

1. **Skill name** — read from `name` field in SKILL.md frontmatter
2. **Organization** — auto-detected if you belong to exactly one org. If you have multiple, specify explicitly: `dhub publish myorg/my-skill`
3. **Version** — fetches latest version from registry, bumps patch by default. First publish uses `0.1.0`

### Argument disambiguation

The first positional argument is interpreted as:
- A **path** if it starts with `.`, `/`, `~`, or is an existing directory
- An **org/skill reference** otherwise

So `dhub publish .` and `dhub publish myorg/skill` both work as expected.

### Safety grading

After publishing, the server runs safety checks and assigns a grade:

| Grade | Meaning | Effect |
|-------|---------|--------|
| **A** | Clean — no elevated permissions or risky patterns | Normal installation |
| **B** | Elevated permissions detected | Warning shown on install |
| **C** | Ambiguous/risky patterns | Users need `--allow-risky` flag to install |
| **F** | Rejected — fails safety checks | Publish is rejected (HTTP 422) |

If the skill has an `evals` block, agent evaluation runs after publish and the CLI automatically attaches to the live log stream. Press Ctrl-C to detach; re-attach later with `dhub logs`.

### What gets zipped

The publish command creates a zip of the skill directory, excluding:
- Hidden files (names starting with `.`)
- `__pycache__/` directories

## Publishing from a Git Repository

You can pass a git URL directly to `dhub publish`:

```bash
dhub publish https://github.com/myorg/my-skills-repo
dhub publish git@github.com:myorg/my-skills-repo.git --ref v2.0
dhub publish https://github.com/myorg/repo --minor
```

The command detects that the argument is a git URL (HTTPS, SSH, or `.git` suffix), clones the repository, recursively discovers all directories containing a valid SKILL.md, and publishes each one. This is useful for monorepos containing multiple skills.

### How discovery works

1. The repo is cloned (shallow clone with `--depth 1`)
2. All `SKILL.md` files are found recursively
3. Hidden directories (`.git`, etc.), `node_modules`, and `__pycache__` are skipped
4. Each `SKILL.md` is validated — only directories with valid frontmatter (name + description) are published
5. Skills are published one by one; failures don't stop the remaining skills

### Git-specific options

- `--ref` — branch, tag, or commit to checkout (only valid with git URLs)

## Installing Skills

```bash
dhub install myorg/my-skill                          # latest version
dhub install myorg/my-skill --version 1.2.0          # specific version
dhub install myorg/my-skill --agent claude-code        # install + link to Claude Code
dhub install myorg/my-skill --agent all                # link to all agents
dhub install myorg/my-skill --allow-risky             # allow Grade C skills
```

### Where skills get installed

- **Canonical path**: `~/.dhub/skills/{org}/{skill}/`
- **Agent symlinks** (when using `--agent`):

| Agent | `--agent` | Symlink Location |
|-------|-----------|-----------------|
| Claude Code | `claude-code` | `~/.claude/skills/{skill}` |
| Cursor | `cursor` | `~/.cursor/skills/{skill}` |
| Codex | `codex` | `~/.codex/skills/{skill}` |
| Windsurf | `windsurf` | `~/.codeium/windsurf/skills/{skill}` |
| Gemini CLI | `gemini-cli` | `~/.gemini/skills/{skill}` |
| GitHub Copilot | `github-copilot` | `~/.copilot/skills/{skill}` |
| Roo Code | `roo` | `~/.roo/skills/{skill}` |
| OpenCode | `opencode` | `~/.config/opencode/skills/{skill}` |

40+ agents supported. Run `dhub install org/skill --agent all` to link to every agent. See the README for the full list.

Symlinks point to the canonical `~/.dhub/skills/` path, so the skill is stored once and shared across agents.

### After installation: load the skill immediately

When you install a skill on behalf of the user, **always read it into the current conversation** so it's usable right away. Don't tell the user to start a new session.

After `dhub install` succeeds:
1. Read the installed skill's `SKILL.md` from `~/.dhub/skills/{org}/{skill}/SKILL.md`
2. Confirm to the user that the skill is loaded and ready to use now

Don't read reference files upfront — the SKILL.md itself will tell you when to consult specific references.

The user installed a skill because they want to use it — treat installation as implicit activation.

### Integrity verification

Downloads are verified via SHA-256 checksum before extraction. If the checksum doesn't match, installation aborts.

## Running Skills Locally

```bash
dhub run myorg/my-skill              # run the skill
dhub run myorg/my-skill -- --flag    # pass extra args to the entrypoint
```

### Prerequisites

- The skill must be installed locally (`dhub install` first)
- The skill must have a `runtime` block in its SKILL.md
- `uv` must be available on PATH
- Required environment variables (from `runtime.env`) must be set
- Only `language: python` is supported

### What happens

1. Parses SKILL.md to get runtime config
2. Validates prerequisites (uv, lockfile, entrypoint, env vars)
3. Runs `uv sync --directory {skill_dir}` to install dependencies
4. Runs `uv run --directory {skill_dir} python {entrypoint} [extra_args]`

## Eval Reports

View evaluation results for a published skill version:

```bash
dhub eval-report myorg/my-skill@1.0.0
```

The report shows:
- **Agent** used for the eval run
- **Judge model** that evaluated the output
- **Status**: passed, failed, error, pending
- **Results**: pass/fail count and per-case details with reasoning

Evals run automatically in the background after publishing a skill that has an `evals` block. Use `dhub eval-report` to check results.

## Eval Logs (Real-Time Streaming)

Tail eval run logs in real-time, or view recent runs:

```bash
dhub logs                              # list recent eval runs
dhub logs myorg/my-skill --follow      # tail latest run for latest version
dhub logs myorg/my-skill@1.0.0 -f      # tail latest run for specific version
dhub logs <run-id> --follow            # tail a specific run by ID
```

When you publish a skill with evals, the CLI automatically attaches to the log stream. Press Ctrl-C to detach — you can re-attach later with `dhub logs`.

Events include: sandbox setup, agent stdout/stderr, judge start, case verdicts (PASS/FAIL), and a final summary.

## API Key Management

Skills that use third-party APIs during evaluation need API keys stored in Decision Hub:

```bash
dhub keys add OPENAI_API_KEY        # prompts securely for the value
dhub keys list                      # show stored key names
dhub keys remove OPENAI_API_KEY     # delete a stored key
```

Keys are stored server-side (encrypted) and injected into eval sandbox environments. Key names must match the `runtime.env` entries in SKILL.md.

## Organization Management

```bash
dhub org list    # list namespaces you can publish to
```

Your namespaces are derived from your GitHub account and org memberships. Run `dhub login` to refresh memberships after joining new GitHub orgs.

## Skill Discovery

```bash
dhub ask "analyze A/B test results"
dhub ask "generate presentation slides"
```

Natural language search across all published skills. Returns matching skills with descriptions and install instructions.

## Scaffolding a New Skill

```bash
dhub init                  # interactive — prompts for name and description
dhub init ./my-skill       # create in a specific directory
```

Creates:
```
my-skill/
  SKILL.md     # frontmatter + body skeleton
  src/         # source code directory
```

## SKILL.md Format (Quick Reference)

```yaml
---
name: my-skill                 # 1-64 chars, lowercase + hyphens
description: What it does      # 1-1024 chars, triggers skill activation
license: MIT                   # optional
runtime:                       # optional — for executable skills
  language: python
  entrypoint: src/main.py
  env: [OPENAI_API_KEY]
  dependencies:
    package_manager: uv
    lockfile: uv.lock
evals:                         # optional — for testable skills
  agent: claude
  judge_model: claude-sonnet-4-5-20250929
---
System prompt for the agent goes here.
```

## Agent Usage (Scripting & Automation)

### Global `--output` flag

Always use `--output json` when calling dhub programmatically:

```bash
dhub --output json list
dhub --output json ask "find data science skills"
dhub --output json info acme/my-skill
dhub --output json doctor
```

JSON goes to stdout; errors go to stderr as structured JSON. Never parse the default text output — it contains ANSI escape codes and Rich markup.

### `--dry-run` for mutations

Preview destructive operations before executing:

```bash
dhub publish ./my-skill --dry-run          # see what would be published
dhub delete acme/my-skill --dry-run        # see what would be deleted
dhub access grant acme/skill partner --dry-run  # validate without granting
```

### Pre-flight checks

Run `dhub --output json doctor` before any workflow to verify auth, connectivity, and version:

```bash
dhub --output json doctor
# {"env": "prod", "cli_version": "0.7.0", "authenticated": true, "org": "acme", "api_reachable": true, ...}
```

### Idempotency

| Command | Safe to retry? | Notes |
|---------|---------------|-------|
| `install` | Yes | Overwrites existing installation |
| `publish` | Yes | Same checksum = skip (no-op) |
| `delete` | No | Second call returns 404 |
| `ask` | Yes | Pure query, no side effects |
| `list` | Yes | Pure query |
| `info` | Yes | Pure query |
| `doctor` | Yes | Pure diagnostic |

### Atomicity

| Command | Atomic? | Notes |
|---------|---------|-------|
| `install` | Yes | Download + verify + extract all succeed or none |
| `publish` | Partial | Skill published even if tracker creation fails |
| `delete` | Yes | Single API call |

### Error codes

In `--output json` mode, errors are structured JSON on stderr:

```json
{"error": true, "code": "NOT_FOUND", "message": "Skill 'acme/foo' not found.", "status": 404}
```

Codes: `AUTH_REQUIRED`, `PERMISSION_DENIED`, `NOT_FOUND`, `VERSION_EXISTS`, `GAUNTLET_FAILED`, `UPGRADE_REQUIRED`, `VALIDATION_ERROR`, `SERVICE_UNAVAILABLE`

## Troubleshooting

### "Connection timed out" or slow first request
Modal cold starts take 30-60s. Retry after a minute. All dhub HTTP calls use 60s timeouts internally.

### "No namespaces available"
Run `dhub login` to refresh GitHub org memberships. You need at least one org to publish.

### "You have multiple namespaces"
Specify the org explicitly: `dhub publish myorg/my-skill` instead of `dhub publish`.

### "Version X already exists"
Versions are immutable. Bump the version: `dhub publish --patch` (or `--minor`, `--major`), or use `--version` with a new number.

### "Rejected (Grade F)"
The skill failed safety checks. Review your SKILL.md and scripts for dangerous patterns (shell injection, credential exfiltration, etc.).

### "Skill not installed" when running
Install first with `dhub install org/skill`, then `dhub run org/skill`.

### "This skill has no runtime configuration"
Only skills with a `runtime` block can be run via `dhub run`. Prompt-only skills don't need `dhub run`.

### "Checksum mismatch"
Download was corrupted. Retry `dhub install`. If it persists, the server package may be damaged — try re-publishing.

### Wrong environment
Check with `dhub env`. Set `DHUB_ENV=dev` or `DHUB_ENV=prod` before commands.

### Config file location
- Dev: `~/.dhub/config.dev.json`
- Prod: `~/.dhub/config.prod.json`
- Override API URL: `DHUB_API_URL` env var (highest priority)
