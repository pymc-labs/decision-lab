import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "An example custom tool. Replace with your own logic.",
  args: {
    input: tool.schema.string().describe("Input to process"),
  },
  async run({ input }) {
    return `Processed: ${input}`
  },
})
