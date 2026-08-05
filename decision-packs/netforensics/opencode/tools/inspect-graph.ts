import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Inspect a graph dataset directory. Reports node/edge counts, feature stats, class balance, temporal range, and degree distribution. Call this FIRST on any new dataset before designing the analysis. Expects a directory containing features.csv, edges.csv, labels.csv (Elliptic's native filenames are auto-detected).",

  args: {
    data_dir: tool.schema.string().describe("Path to the directory containing the dataset CSVs"),
  },

  async execute({ data_dir }) {
    const result = await Bun.$`python -m netforensics_lib.inspect_graph ${data_dir}`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()
    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }
    return stdout
  },
})
