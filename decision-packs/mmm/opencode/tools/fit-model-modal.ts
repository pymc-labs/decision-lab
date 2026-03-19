import { tool } from "@opencode-ai/plugin"

export default tool({
  description: `Fit an MMM model on Modal cloud using numpyro backend.

Takes a model_to_fit.pkl file containing the model bundle and sends it to Modal
for MCMC sampling. Posterior predictive sampling is done locally. The fitted
model is saved to fitted_model.nc.

REQUIRED: The model_to_fit.pkl must be a cloudpickled dictionary containing:
- mmm: The MMM model (with build_model(X, y) already called!)
- X: Feature DataFrame
- y: Target Series (ALWAYS pass y, never None)
- draws: Number of MCMC draws (default: 1000)
- tune: Number of tuning samples (default: 1000)
- chains: Number of MCMC chains (default: 4)
- target_accept: Target acceptance rate (default: 0.9)

Example Python code to create model_to_fit.pkl:
\`\`\`python
import cloudpickle

# After configuring mmm and preparing X, y:
mmm.build_model(X=X, y=y)

model_bundle = {
    "mmm": mmm,
    "X": X,
    "y": y,  # ALWAYS pass y, never None
    "draws": 1000,
    "tune": 1000,
    "chains": 4,
    "target_accept": 0.9,
}

with open("model_to_fit.pkl", "wb") as f:
    cloudpickle.dump(model_bundle, f)
\`\`\``,

  args: {
    model_bundle_path: tool.schema.string().describe("Path to model_to_fit.pkl containing the model bundle"),
    output_path: tool.schema.string().optional().describe("Path for fitted model output (default: fitted_model.nc)"),
  },

  async execute(args) {
    const cmdParts = [
      `python -m mmm_lib.fit_model_modal`,
      `--model-bundle ${args.model_bundle_path}`,
    ]
    if (args.output_path !== undefined) {
      cmdParts.push(`--output ${args.output_path}`)
    }

    const result = await Bun.$`sh -c ${cmdParts.join(' ')}`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()

    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }

    return stdout.trim()
  },
})
