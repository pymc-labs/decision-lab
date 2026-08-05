import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Run the edge-shuffle ablation: train the model twice — once on the real graph, once on a degree-preserving randomized version. If F1 is similar, the graph is contributing little signal beyond per-node features. This is the test that decides whether a 'graph model' is actually a graph model in practice. For GNNs on temporal/inductive splits, strict_edges is forced to true automatically (measuring the edge-shuffle gap in the leaky regime would conflate graph signal with train-time leakage) — the returned JSON's `strict_edges_forced` field reports whether this happened. Run across at least 3 seeds and report median plus min/max — a single-seed gap is noise.",

  args: {
    data_dir: tool.schema.string().describe("Path to the dataset directory"),
    model: tool.schema.string().describe("One of: xgboost, gcn, graphsage. (XGBoost will trivially produce zero gap; running it serves as a control.)"),
    split: tool.schema.string().describe("One of: transductive, temporal, inductive"),
    seed: tool.schema.number().describe("Random seed. Default 0.").optional(),
  },

  async execute({ data_dir, model, split, seed }) {
    const args = [
      "--data", data_dir,
      "--model", model,
      "--split", split,
    ]
    if (seed !== undefined) args.push("--seed", String(seed))

    const result = await Bun.$`python -m netforensics_lib.edge_shuffle_cli ${args}`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()
    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }
    return stdout
  },
})
