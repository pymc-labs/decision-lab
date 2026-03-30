# dhub Command Reference

Complete reference for every dhub command, flag, and option.

## dhub login

Authenticate with Decision Hub via GitHub Device Flow.

```
dhub login [--api-url URL]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--api-url` | string | from config | Override the API URL for this login |

**Flow:**
1. POST `/auth/github/code` → receives device code + user code
2. Display user code and `https://github.com/login/device` URL
3. Poll POST `/auth/github/token` every 5s (HTTP 428 = pending, 200 = done)
4. Save token to `~/.dhub/config.{env}.json`
5. Timeout: 300 seconds

**Config after login:**
```json
{"api_url": "https://lfiaschi--api.modal.run", "token": "<oauth_token>"}
```

---

## dhub logout

Remove stored authentication token.

```
dhub logout
```

No options. Sets token to null in the config file.

---

## dhub env

Show active environment, config file path, and API URL.

```
dhub env
```

No options. Displays the current `DHUB_ENV` value, resolved config path, and API URL.

---

## dhub init

Scaffold a new skill project with SKILL.md and src/ directory.

```
dhub init [PATH]
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `PATH` | no | current directory | Where to create the skill |

Interactive — prompts for skill name and description. Validates name against pattern `^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$`.

**Creates:**
```
skill-name/
  SKILL.md
  src/
```

---

## dhub publish

Publish a skill to the registry.

```
dhub publish [SKILL_REF] [PATH] [--version VER] [--patch] [--minor] [--major] [--ref REF]
```

| Argument/Option | Required | Default | Description |
|----------------|----------|---------|-------------|
| `SKILL_REF` | no | auto-detect from SKILL.md | Org/skill reference, path, or git URL |
| `PATH` | no | `.` | Path to skill directory |
| `--version` | no | auto-bump | Explicit semver (e.g. `1.2.3`) |
| `--patch` | no | true (default bump) | Bump patch version |
| `--minor` | no | false | Bump minor version |
| `--major` | no | false | Bump major version |
| `--ref` | no | default branch | Branch/tag/commit (git URLs only) |

**Positional argument disambiguation:**
- Git URL (starts with `https://`, `http://`, `git@`, `ssh://`, `git://`, or ends with `.git`) → clone repo and publish all discovered skills
- Starts with `.`, `/`, `~`, or is an existing directory → treated as PATH
- Contains `/` but not a directory → treated as SKILL_REF (org/skill)

**Auto-detection:**
- **Name**: from SKILL.md frontmatter `name` field
- **Org**: auto-detected if user belongs to exactly one org
- **Version**: fetches latest from `/v1/skills/{org}/{name}/latest-version`, bumps patch. First publish → `0.1.0`

**Error codes:**
- HTTP 409 → version already exists
- HTTP 422 → Grade F, safety checks failed
- HTTP 503 → server LLM judge not configured

**Output:** Published reference with safety grade (A/B/C). If evals are configured, the CLI automatically attaches to the eval log stream (see `dhub logs`).

**Git repository mode:**

When the first argument is a git URL, publish clones the repo and discovers all skills:

```bash
dhub publish https://github.com/myorg/skills-repo
dhub publish git@github.com:myorg/repo.git --ref main
dhub publish https://github.com/myorg/repo --minor
```

Steps:
1. Clone the repository (shallow, `--depth 1`) into a temporary directory
2. Recursively find all `SKILL.md` files, skipping hidden dirs, `node_modules`, `__pycache__`
3. Validate each `SKILL.md` — only directories with valid frontmatter are included
4. Publish each discovered skill, reading names from SKILL.md frontmatter
5. Clean up the temporary clone

If one skill fails to publish, the remaining skills still get published. A summary is printed at the end: X published, Y skipped, Z failed.

---

## dhub install

Install a skill from the registry.

```
dhub install ORG/SKILL [--version VER] [--agent AGENT] [--allow-risky]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--version`, `-v` | string | `"latest"` | Version spec |
| `--agent` | string | none | Target agent (e.g. `claude-code`, `cursor`, `codex`, `windsurf`) or `all`. See README for full list. |
| `--allow-risky` | flag | false | Allow installing Grade C skills |

**Steps:**
1. Resolve version via GET `/v1/resolve/{org}/{skill}?spec={version}`
2. Download zip from signed S3 URL
3. Verify SHA-256 checksum
4. Extract to `~/.dhub/skills/{org}/{skill}/`
5. Create agent symlinks if `--agent` specified

**Symlink naming:** `{skill}` in the agent's skill directory.

---

## dhub uninstall

Remove a locally installed skill and all its agent symlinks.

```
dhub uninstall ORG/SKILL
```

Removes:
1. Agent symlinks from all agent directories
2. The canonical directory at `~/.dhub/skills/{org}/{skill}/`
3. Empty org directory if no other skills remain

---

## dhub list

List all published skills on the registry, sorted by download count (most popular first).

```
dhub list
dhub list --org ORG          # filter by organization
dhub list --skill NAME       # filter by skill name (substring match)
dhub list --page-size 20     # items per page (default 50, max 100)
dhub list --all              # dump all pages without prompting
```

Displays a table with columns: Org, Skill, Category, Version, Updated (YYYY-MM-DD), Safety (grade), Downloads, Author, Description.

---

## dhub delete

Delete a skill version (or all versions) from the registry.

```
dhub delete ORG/SKILL [--version VER]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--version`, `-v` | string | none | Specific version to delete. Omit to delete ALL versions (with confirmation prompt). |

**Error codes:**
- HTTP 404 → skill or version not found
- HTTP 403 → no permission to delete

---

## dhub run

Run a locally installed skill using its configured runtime.

```
dhub run ORG/SKILL [-- EXTRA_ARGS...]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `ORG/SKILL` | yes | Installed skill reference |
| `EXTRA_ARGS` | no | Extra arguments passed to the entrypoint script |

**Requirements:**
- Skill must be installed locally
- SKILL.md must have a `runtime` block with `language: python`
- `uv` must be on PATH
- Lockfile must exist (if declared in runtime config)
- Entrypoint file must exist
- Required env vars (from `runtime.env`) must be set

**Execution:**
1. `uv sync --directory {skill_dir}` — install/sync dependencies
2. `uv run --directory {skill_dir} python {entrypoint} [extra_args]` — run the skill
3. Exit code from the entrypoint is propagated

---

## dhub ask

Natural language skill search.

```
dhub ask "QUERY"
```

Searches across all published skills. Returns markdown-formatted results in a Rich panel.

**API:** GET `/v1/search?q={query}`

---

## dhub eval-report

View the agent evaluation report for a skill version.

```
dhub eval-report ORG/SKILL@VERSION
```

The `@VERSION` is required. Format: `myorg/my-skill@1.0.0`.

**Output:**
- Agent and judge model used
- Overall status: passed / failed / error / pending
- Pass/fail count
- Per-case results with verdicts and reasoning

**Verdict values:** `pass`, `fail`, `error`
**Stages:** `sandbox` (execution failed), `agent` (non-zero exit), `judge` (LLM evaluation)

---

## dhub logs

View or tail eval run logs in real-time.

```
dhub logs [SKILL_REF] [--follow|-f]
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `SKILL_REF` | string | None | Skill ref (org/skill[@version]) or eval run ID |
| `--follow` / `-f` | flag | False | Tail logs in real-time |

**Usage patterns:**
- `dhub logs` — list recent eval runs (table with ID, status, agent, cases, stage)
- `dhub logs org/skill --follow` — tail latest run for the latest version
- `dhub logs org/skill@1.0.0 --follow` — tail latest run for a specific version
- `dhub logs <run-id> --follow` — tail a specific eval run by its UUID

**Log events:**
- `setup` — sandbox provisioning
- `case_start` — case N/M starting
- `log` — agent stdout/stderr (truncated to 200 chars for display)
- `judge_start` — LLM judge invoked
- `case_result` — PASS/FAIL/ERROR with reasoning
- `report` — final summary (passed/total, duration)

**Publish auto-attach:** When publishing a skill with evals, the CLI automatically starts tailing the eval run logs. Press Ctrl-C to detach; re-attach later with `dhub logs <run-id> --follow`.

---

## dhub org list

List namespaces you can publish to.

```
dhub org list
```

Shows organization slugs derived from your GitHub account and org memberships.

---

## dhub config default-org

Set the default namespace for publishing so you don't have to specify it each time.

```
dhub config default-org
```

Interactive — prompts you to choose from your available namespaces. The selection is saved to `~/.dhub/config.{env}.json`.

---

## dhub keys add

Store an API key for agent evaluations.

```
dhub keys add KEY_NAME
```

Prompts securely for the key value (hidden input). Keys are stored server-side (encrypted) and injected into eval sandbox environments.

**Error:** HTTP 409 if key name already exists. Remove it first with `dhub keys remove`.

---

## dhub keys list

List stored API key names.

```
dhub keys list
```

Displays a table with key names and creation dates. Does not show key values.

---

## dhub keys remove

Remove a stored API key.

```
dhub keys remove KEY_NAME
```

**Error:** HTTP 404 if key name not found.

---

## dhub --version

Show the installed CLI version.

```
dhub --version
dhub -V
```

---

## dhub doctor

Check CLI configuration, authentication, and API connectivity.

```
dhub doctor
```

Reports: environment, CLI version, authentication status, default org, API reachability with latency.

---

## Global Behavior

**Output format:** All data-returning commands support `--output json` (global flag):

```bash
dhub --output json list                    # JSON to stdout
dhub --output json ask "query"             # JSON to stdout
dhub --output json info org/skill          # JSON to stdout
dhub --output json doctor                  # JSON to stdout
```

In JSON mode: no Rich markup, no banners, no interactive prompts. Errors go to stderr as structured JSON. Default is `text` (existing Rich-formatted output).

**Dry-run:** Mutating commands support `--dry-run`:

```bash
dhub publish ./skill --dry-run             # show what would be published
dhub delete org/skill --dry-run            # show what would be deleted
dhub access grant org/skill partner --dry-run  # validate without granting
```

**Timeouts:** All HTTP requests use 60-second timeouts to handle Modal cold starts.

**Headers:** Every request includes:
- `X-DHub-Client-Version: {version}` — CLI version for compatibility checking
- `Authorization: Bearer {token}` — when authenticated

**Environment:** `DHUB_ENV` controls dev/prod. `DHUB_API_URL` overrides the API URL entirely.

**Config priority:**
1. `DHUB_API_URL` env var (highest)
2. Saved config file (`~/.dhub/config.{env}.json`)
3. Default URL for environment

**Error codes (JSON mode):**

Errors in `--output json` mode are structured JSON on stderr:
```json
{"error": true, "code": "NOT_FOUND", "message": "...", "status": 404}
```

| Code | Meaning |
|------|---------|
| `AUTH_REQUIRED` | Not logged in |
| `PERMISSION_DENIED` | No permission for this action |
| `NOT_FOUND` | Skill/version/key not found |
| `VERSION_EXISTS` | Version already published |
| `GAUNTLET_FAILED` | Safety checks failed (Grade F) |
| `UPGRADE_REQUIRED` | CLI too old for server |
| `VALIDATION_ERROR` | Invalid input |
| `SERVICE_UNAVAILABLE` | Server not configured |
