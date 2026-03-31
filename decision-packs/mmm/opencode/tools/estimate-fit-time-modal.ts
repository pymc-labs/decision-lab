import { tool } from "@opencode-ai/plugin"

export default tool({
  description: `Estimate MCMC fitting time before running a full fit.

Use this tool for large or complex models to understand how long fitting will take
BEFORE committing to a potentially long fit. Returns estimated time and recommendations.

WHEN TO USE:
- MMM with dims and 10+ geos/dimensions
- Models with 8+ channels
- When previous fits took >30 minutes
- When uncertain about model complexity

HOW IT WORKS:
- Runs ~100 samples on Modal (20 tune + 5 draws per chain)
- Takes 2-5 minutes including VM startup
- Extrapolates to estimate total time for your requested tune/draws

BASED ON RESULTS:
- < 10 min estimated: Proceed with full fit
- 10-30 min: Normal for complex models, proceed
- 30-60 min: Consider simplifying (pooled priors, grouping channels)
- > 60 min: Strongly consider simplifying before fitting

IMPORTANT: The model bundle must have build_model() already called, same as fit-model-modal.`,

  args: {
    model_bundle_path: tool.schema.string().describe("Path to model_to_fit.pkl containing the model bundle"),
  },

  async execute(args) {
    const cmd = `python -m mmm_lib.fit_model_modal --model-bundle ${args.model_bundle_path} --estimate-only`
    const result = await Bun.$`sh -c ${cmd}`.nothrow()
    const stdout = result.stdout.toString().trim()
    const stderr = result.stderr.toString()

    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }

    return stdout
  },
})
