import { tool } from "@opencode-ai/plugin"

export default tool({
  description: `Fit an MMM model using MCMC sampling with numpyro backend.
Takes a pickled unfitted model and data file, runs MCMC fitting,
saves fitted model using mmm.save(), and returns convergence diagnostics as JSON.

Supports both single time series (dims=None) and panel data (dims=("<DIM_COLUMN>",) where DIM_COLUMN is the actual column name from the dataframe).

This is Phase 2 of the 3-phase workflow:
1. Prepare: Create and configure MMM, run prior predictive, pickle the unfitted model
2. Fit: Use this tool to run MCMC sampling
3. Analyze: Load fitted model with MMM.load() and compute ROAS/contributions`,

  args: {
    model_path: tool.schema.string().describe("Path to pickled unfitted model (.pkl)"),
    data_path: tool.schema.string().describe("Path to data file (CSV or Parquet)"),
    output_path: tool.schema.string().optional().describe("Path for fitted model output (default: fitted_model.nc in cwd)"),
    draws: tool.schema.number().optional().describe("Number of MCMC draws (default: 1000)"),
    tune: tool.schema.number().optional().describe("Number of tuning samples (default: 1000)"),
    chains: tool.schema.number().optional().describe("Number of MCMC chains (default: 4)"),
    target_accept: tool.schema.number().optional().describe("Target acceptance rate (default: 0.9)"),
    seed: tool.schema.number().optional().describe("DO NOT USE - parallel instances should NOT share seeds"),
  },

  async execute(args) {
    const draws = args.draws ?? 1000
    const tune = args.tune ?? 1000
    const chains = args.chains ?? 4
    const targetAccept = args.target_accept ?? 0.9

    const cmdParts = [
      `python -m mmm_lib.fit_model_cli`,
      `--model ${args.model_path}`,
      `--data ${args.data_path}`,
      `--draws ${draws}`,
      `--tune ${tune}`,
      `--chains ${chains}`,
      `--target-accept ${targetAccept}`,
    ]
    if (args.output_path !== undefined) {
      cmdParts.push(`--output ${args.output_path}`)
    }
    if (args.seed !== undefined) {
      cmdParts.push(`--seed ${args.seed}`)
    }

    const result = await Bun.$`sh -c ${cmdParts.join(' ')}`.nothrow()
    const stdout = result.stdout.toString().trim()
    const stderr = result.stderr.toString()

    if (result.exitCode !== 0) {
      return { error: `Exit code ${result.exitCode}`, stderr, stdout }
    }

    // Parse JSON output from the CLI
    try {
      const diagnostics = JSON.parse(stdout)
      return diagnostics
    } catch {
      // If JSON parsing fails, return raw output
      return { raw_output: stdout }
    }
  },
})
