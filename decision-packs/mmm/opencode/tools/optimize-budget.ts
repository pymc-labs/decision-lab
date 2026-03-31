import { tool } from "@opencode-ai/plugin"
import { writeFileSync, mkdirSync } from "fs"
import { join } from "path"

export default tool({
  description: `Run budget optimization on a fitted MMM at a specific risk appetite.

risk_pct controls how far from historical mean spend the optimizer can move
each channel: bounds are [(1-risk_pct)*mean, (1+risk_pct)*mean], clamped at 0.
Use 5000.0 for effectively unconstrained optimization.

Outputs allocation per channel, share multipliers, uplift estimates with
uncertainty, bounds binding analysis, and comparison plots.

Returns the full optimization output directly so the agent can read it
without needing to open any files. The same output is also saved to disk.`,

  args: {
    model_path: tool.schema.string().describe("Path to fitted model (.nc file from mmm.save())"),
    risk_pct: tool.schema.number().describe("Bounds as fraction of historical mean spend: each channel can move ±risk_pct from its mean. Bounds = [(1-risk_pct)*mean, (1+risk_pct)*mean], clamped at 0. Use 5000.0 for unconstrained."),
    output_dir: tool.schema.string().optional().describe("Directory for outputs (default: budget_output/ next to model)"),
    roas_applicable: tool.schema.boolean().optional().describe("Set to false when channels are not in monetary units (shows directional guidance only)"),
  },

  async execute(args) {
    const outputDir = args.output_dir ?? "budget_output"
    mkdirSync(outputDir, { recursive: true })

    const cmdParts = [
      `python -m mmm_lib.optimize_budget_cli`,
      args.model_path,
      `--risk-pct ${args.risk_pct}`,
      `-o ${outputDir}`,
    ]
    if (args.roas_applicable === false) {
      cmdParts.push("--no-roas")
    }

    const result = await Bun.$`sh -c ${cmdParts.join(' ')}`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()

    // Save stdout to disk
    if (stdout) {
      writeFileSync(join(outputDir, "budget_output.txt"), stdout)
    }

    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }

    return stdout
  },
})
