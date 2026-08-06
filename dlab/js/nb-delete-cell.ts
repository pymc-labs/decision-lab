import { tool } from "@opencode-ai/plugin"
import { readFileSync, writeFileSync, existsSync } from "fs"

// Notebook editing (issue #68) — structural only; never alters a cell's content.

function loadNb(path: string): any {
  return JSON.parse(readFileSync(path, "utf-8"))
}
function saveNb(path: string, nb: any): void {
  writeFileSync(path, JSON.stringify(nb, null, 1) + "\n")
}

export default tool({
  description:
    "Delete a cell from a notebook by its 0-based index (later cells shift up). " +
    "Use to drop noise or deduplicate repeated cells. Does not alter any other cell.",

  args: {
    notebook: tool.schema.string().describe("Path to the .ipynb file"),
    index: tool.schema.number().describe("0-based index of the cell to delete"),
  },

  async execute({ notebook, index }) {
    if (!existsSync(notebook)) return `ERROR: ${notebook} not found`
    const nb = loadNb(notebook)
    const cells = nb.cells ?? []
    if (index < 0 || index >= cells.length)
      return `ERROR: index ${index} out of range (0..${cells.length - 1})`
    const removed = cells.splice(index, 1)[0]
    saveNb(notebook, nb)
    return `Deleted cell ${index} (${removed.cell_type}) from ${notebook}; ` +
      `${cells.length} cell(s) remain`
  },
})
