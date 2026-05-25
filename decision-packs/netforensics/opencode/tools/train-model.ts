import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Train one model on one (split, model, feature regime) configuration and report metrics. Returns JSON with f1_positive, precision_at_50, precision_at_500, pr_auc, auroc, runtime_s, plus the configuration echoed back. The agent calls this many times in different configurations to map out where signal lives. For GNNs on temporal/inductive splits, pass strict_edges=true to avoid training-time leakage from the test region.",

  args: {
    data_dir: tool.schema.string().describe("Path to the dataset directory"),
    model: tool.schema.string().describe("One of: xgboost, gcn, graphsage"),
    split: tool.schema.string().describe("One of: transductive, temporal, inductive"),
    feature_mode: tool.schema.string().describe("One of: all, raw_local, topology_only. 'raw_local' takes only the first n_raw_features columns (dataset-specific). 'topology_only' ignores provided features and uses computed degree/PageRank/clustering. Default: all").optional(),
    n_raw_features: tool.schema.number().describe("Required if feature_mode=raw_local. Dataset-specific count of the per-node-only feature columns (e.g., 94 for Elliptic Bitcoin).").optional(),
    seed: tool.schema.number().describe("Random seed. Default 0.").optional(),
    strict_edges: tool.schema.boolean().describe("For GNN models with temporal/inductive split, restrict training-time edges to those with both endpoints in the train set. Default false. Set to true to avoid leakage.").optional(),
  },

  async execute({ data_dir, model, split, feature_mode, n_raw_features, seed, strict_edges }) {
    const args = [
      "--data", data_dir,
      "--model", model,
      "--split", split,
    ]
    if (feature_mode) args.push("--feature-mode", feature_mode)
    if (n_raw_features !== undefined) args.push("--n-raw-features", String(n_raw_features))
    if (seed !== undefined) args.push("--seed", String(seed))
    if (strict_edges) args.push("--strict-edges")

    const result = await Bun.$`python -m netforensics_lib.train_cli ${args}`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()
    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }
    return stdout
  },
})
