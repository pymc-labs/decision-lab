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
PyMC, arviz, numpyro, polars, pyarrow, scipy, numpy, matplotlib, and jax.

To install additional packages: `pixi add <package>` (conda-forge) or
`pixi add --pypi <package>` (PyPI).

## Model configuration

Set `default_model` in `config.yaml` to control the orchestrator and data-explorer
model. Set `default_model` and `summarizer_model` in
`opencode/parallel_agents/forecaster.yaml` to control forecaster instances and
the consolidator independently.
