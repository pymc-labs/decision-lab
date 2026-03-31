import { tool } from "@opencode-ai/plugin"

export default tool({
  description: `Run a computation on Modal cloud.

Calls the run_compute() function deployed in docker/modal_app/example.py.
Pass a JSON string with the data to send to the Modal function.

The Modal app must be deployed first (happens automatically via the
pre-run hook deploy_modal.sh).`,

  args: {
    data: tool.schema.string().describe("JSON string with input data for the Modal function"),
  },

  async execute(args) {
    const pyCode = `
import json, modal
f = modal.Function.from_name("modal-example-compute", "run_compute")
data = json.loads('${args.data.replace(/'/g, "\'")}')
result = f.remote(data)
print(json.dumps(result))
`.trim()
    const result = await Bun.$`python -c "${pyCode}" 2>&1`.nothrow()
    const output = result.text().trim()
    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${output}`
    }
    return output
  },
})
