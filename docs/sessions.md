# Sessions

A **session** represents a single execution of opencode with a specific data set and prompt. Sessions provide isolation, state tracking, and reproducibility.

## Session Directory

Each session creates a work directory:

```
analysis-001/
  data/              # Copied from --data argument
  .opencode/         # Copied from decision-pack's opencode/ directory
  _opencode_logs/    # Log output from opencode
  _hooks/            # Copied hook scripts (if decision-pack has hooks)
  .state.json        # Session metadata
  .git/              # Auto-initialized (prevents opencode config traversal)
  parallel/          # Created by parallel agents (if used)
```

### Location

By default, sessions are created in the **current working directory**:
```
./analysis-001/
```

You can specify a custom location with `--work-dir`:
```bash
dlab --dpack ./my-dpack --data ./data \
         --prompt "Test" --work-dir ./my-custom-session
```

### Naming

Session directories are auto-numbered: `analysis-001`, `analysis-002`, etc. The sequence number auto-increments based on existing directories.

## .state.json

Each session stores metadata:

```json
{
  "dpack_name": "my-dpack",
  "config_dir": "/path/to/dpack",
  "work_dir": "/path/to/analysis-001",
  "data_dir": "/path/to/original/data",
  "status": "created"
}
```

| Field | Description |
|-------|-------------|
| `dpack_name` | Name from the decision-pack's config.yaml |
| `config_dir` | Absolute path to the decision-pack config |
| `work_dir` | Absolute path to this session's work directory |
| `data_dir` | Original data path(s) before copying |
| `status` | Session status (`created`) |

## Session Lifecycle

### 1. Config Loaded

- decision-pack directory validated (config.yaml, docker/, opencode/)
- `.env` auto-detected from decision-pack directory
- Hooks normalized (string to list)

### 2. Session Created

- Work directory created with auto-numbered name
- Data copied from `--data` to `{session}/data/`
- opencode config copied from decision-pack to `{session}/.opencode/`
- Hook scripts copied to `{session}/_hooks/`
- Git repo initialized (prevents opencode config traversal)
- `.state.json` written

### 3. Image Built

- Docker image built from decision-pack's Dockerfile (or cached)
- Dangling image warning shown if old images exist

### 4. Container Started

- Named after session directory
- Work directory mounted at `/workspace`
- Logs mounted at `/_opencode_logs`
- Environment file passed if provided

### 5. Hooks & Agent

- Pre-run hooks execute inside container
- opencode runs with prompt and model
- Post-run hooks execute inside container

### 6. Cleanup

- File ownership fixed (`chown` to host user inside container)
- Container stopped and removed

## Data Handling

### Directory Input

Data is **copied** to the session, not symlinked:

```bash
dlab --dpack ./my-dpack --data ./my-data-dir --prompt "Analyze"
```

This copies the entire directory to `{session}/data/`.

### Multiple Files

You can pass multiple files instead of a directory:

```bash
dlab --dpack ./my-dpack --data file1.csv file2.csv config.json --prompt "Compare"
```

Each file is copied into `{session}/data/`.

### Mixed Files and Directories

```bash
dlab --dpack ./my-dpack --data ./images/ report.csv --prompt "Process"
```

Directories are copied as subdirectories, files are copied directly into `data/`.

### No Data

If the decision-pack sets `requires_data: false`, `--data` is optional:

```bash
dlab --dpack ./prompt-only-dpack --prompt "Write a poem"
```

## Continue Mode

Resume an interrupted session:

```bash
dlab --dpack ./my-dpack --continue-dir ./analysis-001 --prompt "Continue"
```

This:
1. Refreshes `.opencode/` config from the decision-pack (agent prompts may have changed)
2. Refreshes hook scripts from the decision-pack
3. Runs opencode in the existing work directory (data preserved)

Cannot be combined with `--data`.

## Session Artifacts

After a session, you'll find:

```
analysis-001/
  data/                    # Your original data
  .opencode/               # opencode config
  _opencode_logs/
    main.log               # Primary agent log
  .state.json
  # Files created by the agent:
  analysis.py
  results.csv
  summary.md
  # If parallel agents were used:
  parallel/
    run-{timestamp}/
      instance-1/
        summary.md
      instance-2/
        summary.md
      consolidator/
      consolidated_summary.md
```

## Managing Sessions

```bash
# List sessions
ls -la analysis-*

# View session state
cat analysis-001/.state.json | python -m json.tool

# Remove a session (may need sudo for Docker-created files)
sudo rm -rf analysis-001

# Monitor a session
dlab connect analysis-001

# View timeline
dlab timeline analysis-001
```

## Error Handling

### Work directory already exists

```
Error: Work directory already exists
```

Use a different `--work-dir` or remove the existing directory.

### Data path not found

```
Error: Data path does not exist: /path/to/data
```

Check the path. With multiple `--data` paths, each is validated independently.

### Permission errors

Docker creates files as root inside the container. dlab runs `chown` before stopping the container to fix ownership. If a session was interrupted before cleanup, use:

```bash
sudo chown -R $(id -u):$(id -g) ./analysis-001
```
