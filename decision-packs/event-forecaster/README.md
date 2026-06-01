# event-forecaster

A dlab decision pack for probabilistic event forecasting.

Given a question of the form *"When will X happen?"* or *"What is the probability
that Y occurs by date Z?"*, this pack runs multiple structurally different Bayesian
forecasting methods in parallel and synthesises a defensible probability estimate
with credible intervals.

## Usage

```bash
# With local data
dlab --dpack . --data path/to/data --prompt "When will X happen? Horizons: ..."

# Without data (domain knowledge only)
dlab --dpack . --prompt "When will X happen? Horizons: ..."
```

## What it does

1. **Data exploration** — inspects provided data files and writes a structural summary
2. **Parallel forecasting** — spawns N independent forecasters, each choosing its own
   method from the event-forecasting skill reference
3. **Synthesis** — consolidator scores all forecasters by evidence quality and
   technical calibration; orchestrator selects the headline estimate

## Methods available

See `opencode/skills/event-forecasting/SKILL.md` for the full method menu:

- `HazardModel` — Bayesian survival analysis (N ≥ 5 historical durations)
- `ReferenceClassModel` — base rate from historical analogues
- `IndicatorModel` — leading indicator regression
- `ScenarioDecomposition` — explicit scenario tree
- `CausalMechanismModel` — structural causal model
- `ContinuousDriverModel` — continuous driver + first-passage time (OU/RWD/SV/LL/LLT)
- `JumpDiffusionModel` — jump-diffusion driver + first-passage time, with EVT/POT tail cross-check
- `ThresholdCrossingModel` — latent threshold from N≥1 historical cases
- `MarkovStateModel` — continuous-time Markov / multi-state transitions across discrete regimes
- `CureRateModel` — long-term survivor (event may never occur)

## Python environment

`python` inside the container routes to a pre-installed pixi environment with
PyMC (>=6), ArviZ (>=1), nutpie, numpyro, polars, pyarrow, scipy, numpy, matplotlib, and jax.

To install additional packages: `pixi add <package>` (conda-forge) or
`pixi add --pypi <package>` (PyPI).

## Model configuration

All roles default to `default_model`. Uncomment optional overrides in `config.yaml`:

```yaml
default_model: anthropic/claude-sonnet-4-5

# models:
#   forecaster: anthropic/claude-haiku-4-5      # parallel instances only
#   consolidator: anthropic/claude-sonnet-4-5   # consolidator only
```

| Role | Config key | Default |
|------|------------|---------|
| Orchestrator & data-explorer | `default_model` | set in config |
| Parallel forecaster instances | `models.forecaster` | same as `default_model` |
| Consolidator (summarizer) | `models.consolidator` | same as `default_model` |

Example — use Haiku for cheap forecaster testing while keeping Sonnet elsewhere:

```yaml
default_model: anthropic/claude-sonnet-4-5

models:
  forecaster: anthropic/claude-haiku-4-5
```

At session setup, dlab injects `models.forecaster` and `models.consolidator` into
`opencode/parallel_agents/forecaster.yaml`. Override the orchestrator for a single
run with `dlab --model ...`.
