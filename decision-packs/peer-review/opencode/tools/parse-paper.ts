import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Parse a PDF or LaTeX paper into structured text with section boundaries, metadata, and citation keys. Use this FIRST on any paper before analysis.",

  args: {
    path: tool.schema.string().describe("Path to paper file (.pdf or .tex)"),
  },

  async execute({ path }) {
    const result = await Bun.$`python -c "
from peer_review_lib.parse_paper import parse_and_print
parse_and_print('${path}')
"`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()

    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }

    return stdout
  },
})
