import { tool } from "@opencode-ai/plugin"
import { readFileSync, writeFileSync, existsSync } from "fs"

// Notebook editing (issue #68) — insert narration BETWEEN existing cells.

function loadNb(path: string): any {
  return JSON.parse(readFileSync(path, "utf-8"))
}
function saveNb(path: string, nb: any): void {
  writeFileSync(path, JSON.stringify(nb, null, 1) + "\n")
}
// Auto-mined run text is almost always currency ("$1,240 spend"), so a bare '$'
// would trigger MathJax. Escape it by default; math:true opts a cell into LaTeX.
function escapeDollar(text: string, math?: boolean): string {
  return math ? text : text.replace(/\$/g, "\\$")
}

export default tool({
  description:
    "Insert a markdown cell at a 0-based index (shifting later cells down), to weave " +
    "narration between the skeleton's code cells. Index equal to the cell count " +
    "appends. Pass math:true for a cell that intentionally uses LaTeX.",

  args: {
    notebook: tool.schema.string().describe("Path to the .ipynb file"),
    index: tool.schema.number().describe("0-based position to insert at"),
    text: tool.schema.string().describe("Markdown source"),
    math: tool.schema.boolean().optional()
      .describe("Keep '$' literal for LaTeX (default: escape it)"),
  },

  async execute({ notebook, index, text, math }) {
    if (!existsSync(notebook)) return `ERROR: ${notebook} not found`
    const nb = loadNb(notebook)
    const cells = nb.cells ?? (nb.cells = [])
    if (index < 0 || index > cells.length)
      return `ERROR: index ${index} out of range (0..${cells.length})`
    cells.splice(index, 0, {
      cell_type: "markdown", metadata: {},
      source: escapeDollar(text, math).split(/(?<=\n)/),
    })
    saveNb(notebook, nb)
    return `Inserted markdown cell at ${index} in ${notebook}; now ${cells.length} cell(s)`
  },
})
