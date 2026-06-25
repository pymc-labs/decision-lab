# netforensics — graph ML done right

A decision-pack for supervised graph learning. Hand it any node-classification dataset and a question; it returns a defensible written assessment of whether the data supports a deployable predictive model, what the model's honest performance actually is, and whether the graph structure is doing any of the work.

## Why this exists

A coding agent given a graph + a labels file will write a syntactically correct GNN, evaluate it the easy way, and report 95%+ accuracy. The accuracy is often a fiction — produced by training-test data leakage that an entire research subfield has been making for years on benchmarks like Elliptic Bitcoin. The model the agent recommends would fail in deployment.

`netforensics` runs the same data through four orthogonal methodological lenses simultaneously:

1. **Three evaluation protocols** (transductive / temporal / inductive) on the same model to detect the leakage gap.
2. **Three model families** (XGBoost / GCN / GraphSAGE) on the same data to verify the no-graph baseline floor.
3. **Three feature regimes** (raw local / full / topology-only) to localize where the signal lives.
4. **An edge-shuffle ablation** to prove the graph is actually contributing — not just per-node features in disguise.

The convergence (or divergence) of these four lenses *is* the answer. Conclusions only get headlined if they survive.

## What you get back

Every run produces two reports at the work directory root:

- **`business_report.md`** — plain-language deploy / use-baseline / don't-deploy verdict, with the honest F1 number and the gap from the naive evaluation.
- **`technical_report.md`** — full diagnostics with tables, seeds, spread, and references to the methodological standards being applied.

Plus three `consolidated_summary.md` files from the parallel-agent fan-outs and one `edge_shuffle_result.json`.

## Install

Requires Docker. From the dlab repo:

```bash
pip install dlab-cli
echo "ANTHROPIC_API_KEY=..." > .env
```

## Run

```bash
# On the included synthetic example (homophilic — some graph signal, smoke test)
dlab --dpack netforensics \
  --data netforensics/example-data \
  --env-file .env \
  --work-dir ./synth-run \
  --prompt "Evaluate whether this dataset supports a deployable node-classification model and whether the graph structure is contributing useful signal."

# On the negative-control synthetic (label-independent edges — graph should
# contribute nothing; this is the test that the pack will SAY so)
dlab --dpack netforensics \
  --data netforensics/example-data-negcontrol \
  --env-file .env \
  --work-dir ./synth-run-negcontrol \
  --prompt "Evaluate whether this dataset supports a deployable node-classification model and whether the graph structure is contributing useful signal."

# Then watch
dlab connect ./synth-run
```

Both synthetic datasets have ~25-30 positive examples in the test fold, which is well below the pack's deploy-decision power threshold (100). The pack will report methodological findings (leakage gap, where signal lives, whether the graph contributes) but will refuse to issue a deploy verdict on this little data — that is the correct behavior. Use these runs to verify the pack's machinery, not to extract a deployment recommendation.

## The canonical demo: Elliptic Bitcoin

The dpack is designed around the Elliptic Bitcoin transaction dataset — 200k transactions, 234k money-flow edges, with ~2% labeled illicit. Elliptic has been the benchmark dataset for crypto AML graph-ML research since 2019, and the standard evaluation methodology used in published papers has a leakage trap that inflates reported F1 by 20–40 points on the illicit class.

To run the demo on Elliptic:

1. Download the dataset:

   ```bash
   # Option A: Kaggle (requires ~/.kaggle/kaggle.json)
   kaggle datasets download -d ellipticco/elliptic-data-set
   unzip elliptic-data-set.zip -d ./elliptic

   # Option B: programmatic download via PyG
   python -c "from torch_geometric.datasets import EllipticBitcoinDataset; EllipticBitcoinDataset(root='./elliptic')"

   # Option C: Kaggle UI download
   # https://www.kaggle.com/datasets/ellipticco/elliptic-data-set
   ```

   The dpack auto-detects Elliptic's filenames (`elliptic_txs_features.csv`, `elliptic_txs_edgelist.csv`, `elliptic_txs_classes.csv`), so any layout works.

2. Run:

   ```bash
   dlab --dpack netforensics \
     --data ./elliptic \
     --env-file .env \
     --work-dir ./elliptic-run \
     --prompt "Evaluate whether this dataset supports a deployable illicit-transaction detector. Use n_raw_features=94 for the feature-regime fan-out (94 per-transaction features, 71 1-hop aggregates — see elliptic-dataset skill)."
   ```

3. Open the resulting `business_report.md`. The pack will report what the data shows under its convergence checks; it will not pre-suppose the answer. Multiple reanalyses (arXiv 2411.10957, 2602.23599) have documented a 20–40 F1 point drop on the positive class when evaluation moves from random split to temporal split on Elliptic — the pack is built to surface that gap if it is present in your run, and to localize whether the remaining signal comes from the graph or from the pre-aggregated features.

## How it works

```
netforensics/
  config.yaml                              — pack metadata, model, opencode version pin
  docker/
    Dockerfile, requirements.txt           — locked CPU torch + torch-geometric + xgboost env
    netforensics_lib/                      — Python primitives
      loader.py                            — load any Elliptic-format CSVs
      splits.py                            — transductive / temporal / inductive
      models.py                            — train_xgboost / train_gcn / train_graphsage
      eval.py                              — F1, precision_at_k, edge_shuffle_ablation
      inspect_graph.py                     — first-pass dataset description
      train_cli.py, edge_shuffle_cli.py    — CLI bridges called by the agent tools
  opencode/
    opencode.json                          — default_agent: orchestrator
    agents/
      orchestrator.md                      — 7-step workflow (see Step list below)
      data-explorer.md                     — single subagent for first-pass inspection
      protocol-evaluator.md                — parallel-fan-out worker
      model-trainer.md                     — parallel-fan-out worker
      feature-ablator.md                   — parallel-fan-out worker
    parallel_agents/
      protocol-evaluator.yaml              — 3-way fan-out: split protocols
      model-trainer.yaml                   — 3-way fan-out: model families
      feature-ablator.yaml                 — 3-way fan-out: feature regimes
    skills/
      graph-ml-evaluation/SKILL.md         — methodology: leakage, metrics under imbalance
      graph-baselines/SKILL.md             — no-graph-baseline doctrine, ablation reading
      elliptic-dataset/SKILL.md            — Elliptic schema and known pitfalls
    tools/
      inspect-graph.ts                     — wraps inspect_graph_cli
      train-model.ts                       — wraps train_cli
      eval-edge-shuffle.ts                 — wraps edge_shuffle_cli
  example-data/
    generate_synthetic.py                  — small synthetic graph with homophily
    features.csv, edges.csv, labels.csv    — generated synthetic dataset
  example-data-negcontrol/
    generate_negcontrol.py                 — same shape, label-independent edges
    features.csv, edges.csv, labels.csv    — generated negative-control dataset
```

The orchestrator's workflow (full prompt at `opencode/agents/orchestrator.md`):

1. **Inspect** the dataset — shape, class balance, temporal range.
2. **Decide** the canonical evaluation protocol from Step 1's facts.
3. **Protocol fan-out** — 3 splits × XGBoost. Detect the leakage gap.
4. **Model family fan-out** — 3 model families × honest split. Compare GNN to no-graph baseline.
5. **Feature regime fan-out** — 3 feature modes × XGBoost. Localize where signal lives.
6. **Edge-shuffle ablation** on whichever model claimed to win Step 4.
7. **Write business + technical reports** with the converged or divergent findings.

## Conventions for input datasets

The pack ingests directories containing three CSVs:

| File (any of) | Schema |
|---|---|
| `features.csv` / `elliptic_txs_features.csv` / `txs_features.csv` | column 1 = node_id, column 2 = optional timestep, remaining columns = features (no header expected) |
| `edges.csv` / `elliptic_txs_edgelist.csv` / `txs_edgelist.csv` | two columns: source_id, target_id |
| `labels.csv` / `elliptic_txs_classes.csv` / `txs_classes.csv` | two columns: node_id, label. Label values: `1` / `"illicit"` → positive; `2` / `"licit"` / `0` → negative; anything else → unknown. |

A second column that's a small integer in the range [0, 1000) is treated as a timestep automatically. If you want to override, drop the timestep column from `features.csv`.

## Scope (v1)

- **Predictive only.** Node-classification with binary labels. Multi-class and link-prediction are out of scope for v1.
- **Convergence over methodology**, not over hyperparameters. The dpack does not do hyperparameter search; the model defaults are reasonable starting points, and methodological robustness matters more than squeezing the last F1 point.
- **CPU-only.** Models are sized so a 200k-node dataset trains in minutes on a laptop.

Future versions (v2+) may add descriptive analysis (community detection, centrality, null models — implemented as a separate set of skills and parallel agents), and may pick up methodology skills from Decision Hub at runtime rather than vendoring them here.

## License

MIT (same as the parent decision-lab framework). The Elliptic dataset itself is CC BY-NC-SA — you should not deploy a commercial product trained on it without separately licensing the data.
