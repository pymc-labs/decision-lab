# modal-example decision-pack

Minimal example showing how to outsource compute to [Modal](https://modal.com) from a dlab agent.

## What it does

The orchestrator has a `run-on-modal` custom tool that calls a serverless function on Modal. The pre-run hook deploys the Modal app automatically.

## Setup

Create a `.env` file:

```bash
# LLM API key
ANTHROPIC_API_KEY=sk-ant-...

# Modal credentials
MODAL_TOKEN_ID=ak-...
MODAL_TOKEN_SECRET=as-...
```

Get Modal tokens at https://modal.com/settings/tokens.

## Run

```bash
dlab --dpack decision-packs/modal-example --env-file .env --prompt "Run a test computation on Modal"
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MODAL_TOKEN_ID` | Yes | Modal authentication |
| `MODAL_TOKEN_SECRET` | Yes | Modal authentication |
| `DLAB_RUN_MODAL_TOOL_LOCALLY` | No | Set to `1` to skip Modal deploy (default: `1`, Modal is opt-in) |

If `DLAB_RUN_MODAL_TOOL_LOCALLY` is unset or `1`, the pre-run hook skips Modal deployment. Set to `0` to enable Modal.

All `DLAB_*` environment variables are automatically forwarded from the host to the Docker container by the dlab CLI.
