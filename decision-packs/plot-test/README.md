# plot-test decision-pack

A minimal pack for exercising the **decision-lab figure style** end to end:
an orchestrator explores a CSV, produces overview figures, fans out three
`plotter` instances with different visualization briefs, and writes a final
report referencing the best figures.

The environment deliberately includes **seaborn** — the classic way for an
agent to destroy a house style is `sns.set_theme()`, which the injected
`dlab-figure-style` skill forbids. The agent prompts intentionally say
nothing about styling; the style must hold through the injected
matplotlibrc, the `dlab_plotstyle` module, and the skill alone.

## Run

```bash
echo "ANTHROPIC_API_KEY=your-key" > .env

dlab run --dpack decision-packs/plot-test \
  --data decision-packs/plot-test/example-data/weekly_marketing.csv \
  --env-file .env \
  --work-dir ./plot-test-run \
  --prompt "Explore this dataset and produce a short visual report"
```

Watch live with `dlab connect ./plot-test-run`.

## What to check afterwards

- **Palette**: every figure (orchestrator + all three instances +
  `parallel/run-*/instance-*/fig_*.png`) uses the house cycle
  (blue/orange/teal/yellow/...), not matplotlib defaults or seaborn themes.
- **Style survives the fan-out**: instance figures match the orchestrator's
  figures (spines, fonts, marker edges) — this verifies `MATPLOTLIBRC` and
  the skill propagate through the instance env allowlist.
- **Skill obedience**: grep the produced scripts for violations:
  `grep -rnE "set_theme|set_style|plt\.style\.use" plot-test-run --include='*.py'`
- **Consolidator note**: `consolidated_summary.md` should describe the
  approaches without any instance having gone off-style.

## Opting out

Set `use_dlab_plot_style: false` in `config.yaml` and rerun: figures revert to
matplotlib/seaborn defaults. Useful as an A/B baseline.
