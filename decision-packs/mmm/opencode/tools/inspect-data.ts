import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Inspect a CSV or Parquet data file. Shows shape, columns, dtypes, missing values, duplicates, and sample rows. Use this FIRST on any data file before writing analysis scripts.",

  args: {
    path: tool.schema.string().describe("Path to data file (CSV or Parquet)"),
  },

  async execute({ path }) {
    const result = await Bun.$`python -c "
from mmm_lib import load_csv_or_parquet_from_file_and_inspect
load_csv_or_parquet_from_file_and_inspect('${path}')
"`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()

    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }

    return stdout
  },
})
