import { tool } from "@opencode-ai/plugin"
import { readFileSync, existsSync, unlinkSync } from "fs"

// Notebook editing (issue #68) — cleanup only. Deletes a whole notebook FILE, but
// REFUSES if it holds any code cell, so real content can never be destroyed; use
// it to remove an empty stub or a duplicate you created.

export default tool({
  description:
    "Delete an entire notebook FILE — for final cleanup only (an empty stub or a " +
    "duplicate you created). REFUSES to delete a notebook that contains any code " +
    "cell, so a notebook with real content is never destroyed.",

  args: {
    notebook: tool.schema.string().describe("Path to the .ipynb file to delete"),
  },

  async execute({ notebook }) {
    if (!existsSync(notebook)) return `ERROR: ${notebook} not found`
    let nb: any
    try { nb = JSON.parse(readFileSync(notebook, "utf-8")) }
    catch { return `ERROR: ${notebook} is not valid JSON` }
    const codeCells = (nb.cells ?? []).filter((c: any) => c.cell_type === "code").length
    if (codeCells > 0)
      return `ERROR: ${notebook} has ${codeCells} code cell(s) — refusing to delete ` +
        "a notebook with real content"
    unlinkSync(notebook)
    return `Deleted ${notebook} (no code cells — an empty/stub notebook)`
  },
})
