import { tool } from "@opencode-ai/plugin"
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs"
import { dirname } from "path"

// Notebook editing (issue #68) — regroup cells across notebooks. The cell object
// is moved verbatim, so a code cell's source + outputs are preserved exactly.

function loadNb(path: string): any {
  return JSON.parse(readFileSync(path, "utf-8"))
}
function saveNb(path: string, nb: any): void {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, JSON.stringify(nb, null, 1) + "\n")
}

export default tool({
  description:
    "Move a cell from one notebook to another (or within one) by index — to regroup " +
    "the skeleton's cells into phase notebooks / attempts. The cell is moved exactly " +
    "as-is; a code cell's code and outputs are never altered. If to_index is omitted " +
    "the cell is appended.",

  args: {
    from_notebook: tool.schema.string().describe("Source .ipynb path"),
    from_index: tool.schema.number().describe("0-based index in the source"),
    to_notebook: tool.schema.string().describe("Destination .ipynb path (created if missing)"),
    to_index: tool.schema.number().optional().describe("0-based insert position (default: append)"),
  },

  async execute({ from_notebook, from_index, to_notebook, to_index }) {
    if (!existsSync(from_notebook)) return `ERROR: ${from_notebook} not found`
    const same = from_notebook === to_notebook
    const src = loadNb(from_notebook)
    const srcCells = src.cells ?? []
    if (from_index < 0 || from_index >= srcCells.length)
      return `ERROR: from_index ${from_index} out of range (0..${srcCells.length - 1})`

    const dst = same ? src : (existsSync(to_notebook) ? loadNb(to_notebook) : emptyNb())
    const cell = srcCells.splice(from_index, 1)[0]
    const dstCells = dst.cells ?? (dst.cells = [])
    // Within one notebook, removing shifts later indices down by one.
    let at = to_index ?? dstCells.length
    if (same && to_index !== undefined && to_index > from_index) at -= 1
    at = Math.max(0, Math.min(at, dstCells.length))
    dstCells.splice(at, 0, cell)

    saveNb(from_notebook, src)
    if (!same) saveNb(to_notebook, dst)
    return `Moved cell ${from_index} (${cell.cell_type}) from ${from_notebook} ` +
      `to ${to_notebook}[${at}]`
  },
})

function emptyNb(): any {
  return {
    cells: [],
    metadata: {
      kernelspec: { name: "python3", display_name: "Python 3" },
      language_info: { name: "python" },
    },
    nbformat: 4, nbformat_minor: 5,
  }
}
