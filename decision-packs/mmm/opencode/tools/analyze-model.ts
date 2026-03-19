import { tool } from "@opencode-ai/plugin"
import { writeFileSync, readFileSync, mkdirSync } from "fs"
import { join } from "path"

export default tool({
  description: `Run comprehensive post-fit analysis on a fitted MMM model.

Generates diagnostics, posterior predictive checks, channel contributions,
saturation curves, sensitivity analysis, and ROAS analysis. All results are
saved to an output directory.

Outputs:
- analysis_output.txt (full stdout log with all numerical results)
- analysis_summary.json (machine-readable key metrics: R-squared, MAPE, divergences, R-hat)
- 14+ PNG plots (diagnostics, contributions, saturation, sensitivity, ROAS)
- contributions.csv, roas.csv

Returns the full analysis output (stdout) directly so the agent can read it
without needing to open any files. The same output is also saved to disk.

Call this AFTER Phase 2 (fitting) completes and fitted_model.nc exists.
Budget optimization is skipped by default (orchestrator runs it separately).`,

  args: {
    model_path: tool.schema.string().describe("Path to fitted model (.nc file from mmm.save())"),
    output_dir: tool.schema.string().optional().describe("Directory for analysis outputs (default: analysis_output/ next to model)"),
    skip_budget: tool.schema.boolean().optional().describe("Skip budget optimization (default: true)"),
    roas_applicable: tool.schema.boolean().optional().describe("Set to false when channels are not in monetary units (skips ROAS, shows budget optimization as directional guidance only)"),
  },

  async execute(args) {
    const outputDir = args.output_dir ?? "analysis_output"
    mkdirSync(outputDir, { recursive: true })

    const cmdParts = [
      `python -m mmm_lib.analyze_model_cli`,
      args.model_path,
      `-o ${outputDir}`,
    ]
    if (args.skip_budget !== false) {
      cmdParts.push("--skip-budget")
    }
    if (args.roas_applicable === false) {
      cmdParts.push("--no-roas")
    }

    const result = await Bun.$`sh -c ${cmdParts.join(' ')}`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()

    // Save stdout to disk
    if (stdout) {
      writeFileSync(join(outputDir, "analysis_output.txt"), stdout)
    }

    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }

    // Append the analysis_summary.json contents to stdout if available
    try {
      const summary = readFileSync(join(outputDir, "analysis_summary.json"), "utf-8")
      return `${stdout}\n\n=== analysis_summary.json ===\n${summary}`
    } catch {
      return stdout
    }
  },
})
