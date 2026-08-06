import { tool } from "@opencode-ai/plugin"
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs"
import { dirname } from "path"

// Cell-level notebook composition (issue #86) — the model passes text only.

function emptyNb(): any {
  return {
    cells: [],
    metadata: {
      kernelspec: { name: "python3", display_name: "Python 3" },
      language_info: { name: "python" },
    },
    nbformat: 4,
    nbformat_minor: 5,
  }
}

function loadNb(path: string): any {
  if (!existsSync(path)) return emptyNb()
  try {
    return JSON.parse(readFileSync(path, "utf-8"))
  } catch {
    return emptyNb()
  }
}

function saveNb(path: string, nb: any): void {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, JSON.stringify(nb, null, 1) + "\n")
}

// Auto-mined run text is almost always currency ("$1,240 spend"), so a bare '$'
// would trigger MathJax. Escape it by default; math:true opts a cell into LaTeX.
function escapeDollar(text: string, math?: boolean): string {
  return math ? text : text.replace(/\$/g, "\\$")
}

export default tool({
  description:
    "Append a markdown cell to a notebook (created if missing). By default '$' is escaped to '\\$' " +
    "so auto-mined currency text does not trigger MathJax; pass math:true for a cell that " +
    "intentionally uses LaTeX.",

  args: {
    notebook: tool.schema.string().describe("Path to the .ipynb file"),
    text: tool.schema.string().describe("Markdown source"),
    math: tool.schema.boolean().optional()
      .describe("Keep '$' literal for MathJax (default false: '$' is escaped)"),
  },

  async execute({ notebook, text, math }) {
    const nb = loadNb(notebook)
    nb.cells.push({ cell_type: "markdown", metadata: {}, source: escapeDollar(text, math) })
    saveNb(notebook, nb)
    return `Added markdown cell ${nb.cells.length - 1} to ${notebook}`
  },
})
