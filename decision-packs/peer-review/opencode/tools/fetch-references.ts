import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Fetch paper metadata and abstract from Semantic Scholar by title. Returns JSON with title, authors, year, venue, abstract, and citation count. Rate-limited to respect API limits.",

  args: {
    query: tool.schema.string().describe("Paper title or citation key to search for"),
  },

  async execute({ query }) {
    const result = await Bun.$`python -c "
from peer_review_lib.fetch_references import fetch_and_print
fetch_and_print('${query}')
"`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()

    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }

    return stdout
  },
})
