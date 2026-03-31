# OpenCode Reference

## Overview

OpenCode is an open-source AI coding agent CLI tool. It's a multi-provider, multi-interface alternative to Claude Code with MIT licensing.

**Key Stats**: 60k+ GitHub stars, 500+ contributors, 650k+ monthly users

## Architecture

**Client/Server Model**:
- **Client**: Go-based Terminal UI (TUI)
- **Server**: JavaScript backend (Bun runtime) with HTTP server
- **Core**: Strongly-typed event bus for all actions

**The LLM-in-a-loop Pattern**:
1. Prepare conversation history, system prompts, tools
2. Send to LLM API
3. Receive text + tool calls (streamed)
4. Execute tools, feed results back
5. Iterate until completion

---

## Configuration

### Directory Structure

OpenCode searches config in this order (later overrides earlier):
1. `.well-known/opencode` (remote/org defaults)
2. `~/.config/opencode/opencode.json` (global)
3. `OPENCODE_CONFIG` env var path (custom)
4. `opencode.json` in project root (project)
5. `.opencode/` directory (see below)
6. `OPENCODE_CONFIG_CONTENT` env var (inline)

### .opencode/ Directory

```
.opencode/
├── agents/          # Agent definitions (markdown)
├── commands/        # Custom commands (markdown)
├── skills/          # Skill definitions (SKILL.md)
├── tools/           # Custom tools (TypeScript/JavaScript)
├── plugins/         # Plugins with hooks (TypeScript/JavaScript)
└── themes/          # UI themes
```

Singular names (`agent/`, `skill/`) also supported for backwards compatibility.

### Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENCODE_CONFIG_DIR` | Custom config directory |
| `OPENCODE_CONFIG` | Path to custom config file |
| `OPENCODE_CONFIG_CONTENT` | Inline config via env var |
| `SHELL` | Shell for bash tool (default: /bin/bash) |
| `ANTHROPIC_API_KEY` | Anthropic Claude access |
| `OPENAI_API_KEY` | OpenAI access |
| `GITHUB_TOKEN` | GitHub integration |

### Variable Substitution

In config files:
- `{env:VARIABLE_NAME}` - Environment variable
- `{file:path/to/file}` - File contents

---

## opencode.json Schema

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4-5",
  "small_model": "anthropic/claude-haiku",
  "default_agent": "build",

  "tools": {
    "bash": true,
    "edit": true,
    "webfetch": false,
    "my-mcp*": false
  },

  "permission": {
    "bash": "ask",
    "edit": "allow",
    "skill": { "*": "allow" }
  },

  "agent": { },
  "command": { },
  "mcp": { },
  "plugin": [],
  "instructions": ["CONTRIBUTING.md", "docs/*.md"],

  "provider": { },
  "formatter": { },
  "keybinds": { },
  "theme": "default",
  "compaction": { },
  "watcher": { }
}
```

---

## Agents

Two types:
- **Primary Agents**: Main assistants (Tab key to switch). Built-in: Build, Plan
- **Subagents**: Specialized tasks spawned by primary agents

### Agent Definition (Markdown)

Location: `.opencode/agents/<name>.md` or `~/.config/opencode/agents/`

```markdown
---
description: Code review agent
mode: subagent
model: anthropic/claude-sonnet-4
temperature: 0.7
maxSteps: 50
disable: false
hidden: false
tools:
  write: false
  bash: false
  webfetch: true
  my-mcp*: true
permission:
  bash: deny
---

You are a code reviewer. Focus on:
- Best practices
- Security vulnerabilities
- Performance issues
```

### Agent Config Properties

| Property | Type | Description |
|----------|------|-------------|
| `description` | string | **Required.** Short description for agent selection |
| `mode` | string | `primary`, `subagent`, or `all` |
| `model` | string | LLM model identifier (e.g., `anthropic/claude-sonnet-4-5`) |
| `temperature` | float | Response creativity (0.0-1.0) |
| `maxSteps` | number | Maximum agentic iterations |
| `disable` | boolean | Disable the agent |
| `hidden` | boolean | Hide from @ autocomplete (subagents only) |
| `tools` | object | Tool availability override (see Tools section) |
| `permission` | object | Per-tool permission override |
| `prompt` | string | Custom system prompt or `{file:path}` reference |

### Agent in opencode.json

```json
{
  "agent": {
    "reviewer": {
      "description": "Reviews code for best practices",
      "mode": "subagent",
      "model": "anthropic/claude-sonnet-4-5",
      "tools": { "write": false },
      "permission": { "bash": "deny" }
    }
  }
}
```

---

## Tools

### Built-in Tools

| Tool | Permission Key | Purpose |
|------|----------------|---------|
| `read` | - | Read file contents |
| `write` | `edit` | Create/overwrite files |
| `edit` | `edit` | Modify existing files |
| `patch` | `edit` | Apply patches |
| `bash` | `bash` | Execute shell commands |
| `glob` | - | Pattern-match files |
| `grep` | - | Search file contents |
| `list` | - | List directory contents |
| `lsp` | - | Code intelligence |
| `skill` | `skill` | Load skill documentation |
| `task` | - | Spawn subagents |
| `todowrite` | - | Task management |
| `todoread` | - | Read tasks |
| `webfetch` | `webfetch` | Fetch web content |
| `question` | - | Ask user questions |

### Tool Configuration Hierarchy

**1. Global (opencode.json)**
```json
{
  "tools": {
    "bash": true,
    "webfetch": false,
    "my-mcp*": false
  },
  "permission": {
    "bash": "ask",
    "edit": "allow"
  }
}
```

**2. Per-Agent Override**
```json
{
  "tools": { "webfetch": false },
  "agent": {
    "researcher": {
      "tools": { "webfetch": true }
    }
  }
}
```

Or in agent markdown frontmatter:
```yaml
tools:
  webfetch: true
  my-mcp*: true
```

### Permission Levels

| Level | Description |
|-------|-------------|
| `"allow"` | Execute without approval |
| `"ask"` | Require user approval |
| `"deny"` | Completely blocked |

Bash permissions support glob patterns for command-specific rules.

---

## Custom Tools

Custom tools let you define functions the LLM can call. **Definitions must be TypeScript/JavaScript**, but can invoke any language (Python, etc.) via shell.

Location: `.opencode/tools/<name>.ts` or `~/.config/opencode/tools/`

### Basic Structure

```typescript
import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Tool description for the LLM",
  args: {
    paramName: tool.schema.string().describe("Parameter description"),
    optional: tool.schema.number().optional().describe("Optional param"),
  },
  async execute({ paramName, optional }, context) {
    // context has: agent, sessionID, messageID
    return "result string"
  },
})
```

### Invoking Python from Custom Tools

```typescript
import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Run PyMC analysis on data",
  args: {
    dataFile: tool.schema.string().describe("Path to CSV data"),
    model: tool.schema.string().describe("Model type: linear, hierarchical"),
  },
  async execute({ dataFile, model }) {
    // Shell out to Python — use .nothrow() so errors return stderr instead of throwing
    const result = await Bun.$`python /workspace/scripts/analyze.py ${dataFile} --model ${model}`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()
    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }
    return stdout
  },
})
```

### Multiple Tools per File

```typescript
export const toolOne = tool({ ... })
export const toolTwo = tool({ ... })
// Creates tools named: filename_toolOne, filename_toolTwo
```

---

## MCP Servers

Model Context Protocol servers add external tools (databases, APIs, services).

### Local MCP Server

```json
{
  "mcp": {
    "postgres": {
      "type": "local",
      "command": ["npx", "-y", "@mcp/postgres"],
      "enabled": true,
      "environment": {
        "DATABASE_URL": "{env:DATABASE_URL}"
      },
      "timeout": 5000
    }
  }
}
```

### Remote MCP Server

```json
{
  "mcp": {
    "github": {
      "type": "remote",
      "url": "https://mcp.github.com",
      "enabled": true,
      "headers": {
        "Authorization": "Bearer {env:GITHUB_TOKEN}"
      }
    }
  }
}
```

### OAuth Authentication

```json
{
  "mcp": {
    "oauth-server": {
      "type": "remote",
      "url": "https://mcp.example.com",
      "oauth": {
        "clientId": "{env:CLIENT_ID}",
        "clientSecret": "{env:CLIENT_SECRET}",
        "scope": "tools:read tools:execute"
      }
    }
  }
}
```

Disable OAuth for API-key auth:
```json
{
  "oauth": false,
  "headers": { "Authorization": "Bearer {env:API_KEY}" }
}
```

### Per-Agent MCP Tools

Disable globally, enable for specific agents:

```json
{
  "tools": {
    "postgres*": false
  },
  "agent": {
    "data-analyst": {
      "tools": {
        "postgres*": true
      }
    }
  }
}
```

---

## Skills

Reusable instruction sets loaded on-demand via the `skill` tool.

### Skill Locations (searched in order)
1. `.opencode/skills/<name>/SKILL.md` (project)
2. `~/.config/opencode/skills/<name>/SKILL.md` (global)
3. `.claude/skills/<name>/SKILL.md` (Claude compat)

### SKILL.md Format

```markdown
---
name: pymc-modeling
description: PyMC Bayesian modeling best practices and patterns
---

## Instructions

When building PyMC models:
1. Always use `pm.Model()` context manager
2. Define priors before likelihood
3. Use ArviZ for diagnostics
4. Check convergence with `az.summary()`

## Common Patterns

### Hierarchical Model
```python
with pm.Model() as model:
    mu = pm.Normal("mu", 0, 1)
    sigma = pm.HalfNormal("sigma", 1)
    obs = pm.Normal("obs", mu, sigma, observed=data)
```
```

### Skill Name Requirements

- 1-64 characters
- Lowercase alphanumeric with single hyphens
- Regex: `^[a-z0-9]+(-[a-z0-9]+)*$`
- Must match containing directory name

### Skill Permissions

```json
{
  "permission": {
    "skill": {
      "*": "allow",
      "internal-*": "deny"
    }
  }
}
```

---

## Commands

Reusable prompt templates triggered by `/command-name`.

Location: `.opencode/commands/<name>.md` or `~/.config/opencode/commands/`

### Command Definition (Markdown)

```markdown
---
description: Run tests and fix failures
agent: debug
model: anthropic/claude-sonnet-4
subtask: true
---

Run the test suite: `pytest $ARGUMENTS`

If tests fail:
1. Analyze the failure
2. Fix the code
3. Re-run tests until green
```

### Command Properties

| Property | Type | Description |
|----------|------|-------------|
| `description` | string | Brief description |
| `agent` | string | Which agent executes (triggers subagent if subagent type) |
| `model` | string | Override default model |
| `subtask` | boolean | Force subagent invocation |

### Template Placeholders

| Placeholder | Description |
|-------------|-------------|
| `$ARGUMENTS` | All command arguments |
| `$1`, `$2`, `$3` | Individual positional arguments |
| `` !`command` `` | Bash command output injection |
| `@filename` | File content inclusion |

### Command in opencode.json

```json
{
  "command": {
    "test": {
      "template": "Run pytest: $ARGUMENTS",
      "description": "Run tests",
      "agent": "debug",
      "subtask": true
    }
  }
}
```

---

## Plugins

JavaScript/TypeScript modules with 32+ hook events.

Location: `.opencode/plugins/<name>.ts` or `~/.config/opencode/plugins/`

### Plugin Structure

```typescript
export const MyPlugin = async (ctx) => {
  // ctx: { project, directory, worktree, client, $ }
  return {
    "session.created": async (event) => {
      console.log("Session started:", event.sessionID)
    },
    "tool.execute.before": async (event) => {
      console.log("Tool called:", event.tool, event.args)
    },
    "tool.execute.after": async (event) => {
      console.log("Tool result:", event.result)
    },
  }
}
```

### Available Hook Events

**Session**: `session.created`, `session.updated`, `session.compacted`, `session.deleted`, `session.diff`, `session.error`, `session.idle`, `session.status`

**Tools**: `tool.execute.before`, `tool.execute.after`

**Files**: `file.edited`, `file.watcher.updated`

**Messages**: `message.part.removed`, `message.part.updated`, `message.removed`, `message.updated`

**Permissions**: `permission.replied`, `permission.updated`

**Commands**: `command.executed`

**LSP**: `lsp.client.diagnostics`, `lsp.updated`

**TUI**: `tui.prompt.append`, `tui.command.execute`, `tui.toast.show`

**Server**: `server.connected`

**Installation**: `installation.updated`

### Loading npm Plugins

```json
{
  "plugin": ["opencode-helicone-session", "@my-org/custom-plugin"]
}
```

### Plugin Dependencies

Create `.opencode/package.json` for external packages:
```json
{
  "dependencies": {
    "axios": "^1.0.0"
  }
}
```
OpenCode runs `bun install` at startup.

---

## Rules (AGENTS.md)

Project-level instructions included in LLM context.

### File Locations

| Location | Scope |
|----------|-------|
| `AGENTS.md` (project root) | Project-specific |
| `~/.config/opencode/AGENTS.md` | Global |
| `CLAUDE.md` | Legacy fallback |

### Extended Instructions

```json
{
  "instructions": [
    "CONTRIBUTING.md",
    "docs/guidelines.md",
    ".cursor/rules/*.md",
    "https://example.com/shared-rules.md"
  ]
}
```

Supports glob patterns and remote URLs.

---

## Supported Providers

- Anthropic (Claude)
- OpenAI
- Google Gemini
- AWS Bedrock
- Groq
- Azure OpenAI
- OpenRouter
- Local models (Ollama, etc.)
- Any OpenAI-compatible API

---

## decision-pack Directory Structure (for dlab)

```
my-dpack/
├── config.yaml              # dlab decision-pack config
├── docker/
│   └── Dockerfile           # Base image
└── opencode/
    ├── opencode.json        # Main OpenCode config
    ├── AGENTS.md            # Project rules
    ├── agents/              # Agent definitions
    │   ├── analyst.md
    │   └── reviewer.md
    ├── skills/              # Skill definitions
    │   └── pymc/SKILL.md
    ├── commands/            # Custom commands
    │   └── test.md
    ├── tools/               # Custom tools (JS/TS)
    │   └── run-model.ts
    └── plugins/             # Hooks (JS/TS)
        └── logger.ts
```

---

## References

- Docs: https://opencode.ai/docs/
- Config: https://opencode.ai/docs/config/
- Agents: https://opencode.ai/docs/agents/
- Skills: https://opencode.ai/docs/skills/
- Commands: https://opencode.ai/docs/commands/
- Tools: https://opencode.ai/docs/tools/
- Custom Tools: https://opencode.ai/docs/custom-tools/
- MCP Servers: https://opencode.ai/docs/mcp-servers/
- Plugins: https://opencode.ai/docs/plugins/
- Rules: https://opencode.ai/docs/rules/
- GitHub: https://github.com/opencode-ai/opencode
