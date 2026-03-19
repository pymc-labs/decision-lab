# Log Processing Reference

This document describes how OpenCode log files are structured and processed by the `dlab connect` TUI and `dlab timeline` commands.

## Log File Format

OpenCode writes logs as **NDJSON** (newline-delimited JSON). Each line is a complete JSON object representing a single event.

### File Organization

```
_opencode_logs/
├── main.log                              # Primary agent execution
└── {agent}-parallel-run-{timestamp}/     # Parallel agent execution
    ├── instance-1.log                    # First parallel instance
    ├── instance-2.log                    # Second parallel instance
    ├── instance-N.log                    # Nth parallel instance
    └── consolidator.log                  # Consolidator agent
```

### Source Name Derivation

| Log File Path | Source Name |
|---------------|-------------|
| `main.log` | `main` |
| `consolidator.log` | `consolidator` |
| `poet-parallel-run-123/instance-1.log` | `poet-parallel-run-123/instance-1` |
| `poet-parallel-run-123/consolidator.log` | `poet-parallel-run-123/consolidator` |

---

## Event Types

### step_start

Marks the beginning of an agent thinking step.

**Raw JSON:**
```json
{
  "type": "step_start",
  "timestamp": 1769011728617,
  "sessionID": "ses_41eaf371affeev9CR0EqK6e6tZ",
  "part": {
    "id": "prt_be150d0e8001pkRHPmTX0nfZy0",
    "sessionID": "ses_41eaf371affeev9CR0EqK6e6tZ",
    "messageID": "msg_be150c9830019jERyh8FsUa7UO",
    "type": "step-start"
  }
}
```

**Key Fields:**
- `timestamp`: Unix milliseconds when the step began
- `sessionID`: Unique session identifier (format: `ses_` + alphanumeric)
- `part.messageID`: The message this step belongs to

**TUI Display:** `Step started`

---

### step_finish

Marks the end of an agent thinking step with cost and token usage.

**Raw JSON:**
```json
{
  "type": "step_finish",
  "timestamp": 1769011739640,
  "sessionID": "ses_41eaf371affeev9CR0EqK6e6tZ",
  "part": {
    "id": "prt_be150fbf80011hl6ugfdWcY4A4",
    "sessionID": "ses_41eaf371affeev9CR0EqK6e6tZ",
    "messageID": "msg_be150c9830019jERyh8FsUa7UO",
    "type": "step-finish",
    "reason": "tool-calls",
    "cost": 0.0285735,
    "tokens": {
      "input": 2,
      "output": 166,
      "reasoning": 0,
      "cache": {
        "read": 0,
        "write": 6954
      }
    }
  }
}
```

**Key Fields:**
- `part.reason`: Why the step finished
  - `"stop"` - Agent completed its task
  - `"tool-calls"` - Agent is waiting on tool execution
  - `"max-tokens"` - Hit token limit
- `part.cost`: API cost in dollars
- `part.tokens`: Detailed token breakdown

**TUI Display:** `Step finished ({reason})`

**Completion Detection:** A log is considered complete if the last `step_finish` has `reason: "stop"`.

---

### text

Agent text output (reasoning, responses, etc.).

**Raw JSON:**
```json
{
  "type": "text",
  "timestamp": 1769011729962,
  "sessionID": "ses_41eaf371affeev9CR0EqK6e6tZ",
  "part": {
    "id": "prt_be150d0ea0010Y9OiknHtifuoI",
    "sessionID": "ses_41eaf371affeev9CR0EqK6e6tZ",
    "messageID": "msg_be150c9830019jERyh8FsUa7UO",
    "type": "text",
    "text": "I'll help you create the perfect poem about that beautiful, slightly melancholic bathroom scene. Let me follow my workflow and start by consulting POPO the Poet, the old legend.",
    "time": {
      "start": 1769011729960,
      "end": 1769011729960
    }
  }
}
```

**Key Fields:**
- `part.text`: The actual text content
- `part.time`: When text generation started/ended

**TUI Display:** Raw text rendered as **Markdown** (headers, code blocks, lists, etc.)

---

### tool_use

A tool call made by the agent. Structure varies by tool type.

**Raw JSON (task tool):**
```json
{
  "type": "tool_use",
  "timestamp": 1769011739640,
  "sessionID": "ses_41eaf371affeev9CR0EqK6e6tZ",
  "part": {
    "id": "prt_be150d6290010SyS7cG1Bn2g4U",
    "sessionID": "ses_41eaf371affeev9CR0EqK6e6tZ",
    "messageID": "msg_be150c9830019jERyh8FsUa7UO",
    "type": "tool",
    "callID": "toolu_01Mg3doaZEHVSd7NXZW73zkq",
    "tool": "task",
    "state": {
      "status": "completed",
      "input": {
        "subagent_type": "popo-poet",
        "description": "POPO writes bathroom poem",
        "prompt": "Write a poem about how when the light shines..."
      },
      "output": "Oh boy, oh BOY! This is gonna be my BEST poem yet!...",
      "title": "POPO writes bathroom poem",
      "metadata": {
        "summary": [],
        "sessionId": "ses_41eaf2565ffecbXtwtW3ysNdn7",
        "truncated": false
      },
      "time": {
        "start": 1769011731097,
        "end": 1769011739639
      }
    }
  }
}
```

**Common Fields:**
- `part.tool`: Tool name (`task`, `read`, `write`, `edit`, `bash`, `parallel-agents`, etc.)
- `part.callID`: Unique identifier (format: `toolu_` + alphanumeric)
- `part.state.status`: `"completed"`, `"failed"`, etc.
- `part.state.input`: Parameters passed to the tool
- `part.state.output`: Result from tool execution
- `part.state.time`: Execution timing (start/end in milliseconds)

---

## TUI Display Formatting

The TUI (`dlab connect`) uses the monokai theme with custom hex colors:

| Event Type | Color |
|------------|-------|
| `step_start` | Cyan `#66D9EF` |
| `step_finish` | Green `#A6E22E` |
| `text` | Foreground `#F8F8F2` |
| `tool_use` | Orange `#FD971F` |
| `task_start` | Orange `#FD971F` |
| `task_finish` | Green `#A6E22E` |
| `error` | Red `#F92672` |

Agent indicators use text labels instead of emoji (e.g., `md`, `py`, `csv` for file types in the artifacts pane).

### Event Type Transformations

| Event Type | Display Format |
|------------|----------------|
| `step_start` | "Step started" |
| `step_finish` | "Step finished ({reason})" |
| `text` | Raw text rendered as Markdown |
| `tool_use` | Tool-specific (see below) |

### Tool-Specific Formatting

| Tool | Display Format | Truncation |
|------|----------------|------------|
| `bash` | `bash: {description or command}`<br>`--- output ---`<br>`{output}` | 500 chars |
| `read` | `read: {filename}` | - |
| `write` | `write: {filename}`<br>`{content}` | 300 chars (full for `.md` files) |
| `edit` | `edit: {filename}`<br>`-{oldString}`<br>`+{newString}` | 100 chars each |
| `task` | `task: {subagent_type} - {description}`<br>`--- output ---`<br>`{output}` | 1000 chars |
| `parallel-agents` | `parallel-agents: {agent} x{count}`<br>`--- output ---`<br>`{output}` | 1000 chars |
| Other | `{tool} ({status})`<br>`{output}` | 200 chars |

### Markdown Rendering

The following content types are rendered as Markdown when expanded:
- All `text` events
- `write` tool output for `.md` files

---

## Agent Name Display

The TUI shortens long agent names for the sidebar.

### Main Agent Renaming

The main agent is renamed to include the default agent from `opencode.json`:

| Original | Display (if default_agent="literary-agent") |
|----------|---------------------------------------------|
| `main` | `main-literary-agent` |

### Parallel Run Shortening

Long parallel run names are compressed:

| Original | Display |
|----------|---------|
| `poet-parallel-run-1769011747728/instance-1` | `⟝ poet …28/ inst-1` |
| `poet-parallel-run-1769011747728/instance-4` | `⟝ poet …28/ inst-4` |
| `poet-parallel-run-1769011747728/consolidator` | `⟝ poet …28/ cnsldtr` |

**Pattern:** `⟝ {agent} …{last 2 digits}/ {shortened suffix}`

Suffix transformations:
- `instance-N` → `inst-N`
- `consolidator` → `cnsldtr`

---

## Timeline Command Processing

The `dlab timeline` command builds execution visualizations from logs.

### Key Functions (timeline.py)

| Function | Purpose |
|----------|---------|
| `parse_log_file(path)` | Parse NDJSON, extract events with metadata |
| `is_log_complete(path)` | Check if last step_finish has `reason="stop"` |
| `discover_agents(dir)` | Find agent definitions in `.opencode/agents/*.md` |
| `build_timeline(logs_dir)` | Construct timeline with Gantt visualization |
| `natural_sort_key(name)` | Sort: main → tasks → instances → consolidator |

### Idle Period Tracking

When agents call `task` or `parallel-agents`, the waiting time is tracked:
- Extracted from `state.time.start` and `state.time.end`
- Visualized as grey bars (░) in Gantt charts
- Shows when an agent is blocked waiting on subprocesses

### Virtual Task Entries

Task subagents (called via `task` tool) get synthetic timeline entries:
- Appear with `(task)` suffix in source name (e.g., `popo-poet (task)`)
- Two synthetic events: `task_start` and `task_finish`
- Timing extracted from the calling `tool_use` event

---

## Timestamp Notes

- All timestamps are **Unix milliseconds** (not seconds)
- Convert to datetime: `datetime.fromtimestamp(timestamp / 1000)`
- Duration calculations: `(end_ms - start_ms) / 1000` for seconds

---

## ID Formats

| ID Type | Format | Example |
|---------|--------|---------|
| Session | `ses_` + alphanumeric | `ses_41eaf371affeev9CR0EqK6e6tZ` |
| Part | `prt_` + alphanumeric | `prt_be150d0e8001pkRHPmTX0nfZy0` |
| Message | `msg_` + alphanumeric | `msg_be150c9830019jERyh8FsUa7UO` |
| Tool Call | `toolu_` + alphanumeric | `toolu_01Mg3doaZEHVSd7NXZW73zkq` |
