import { tool } from "@opencode-ai/plugin"
import { writeFileSync, existsSync, mkdirSync } from "fs"
import { dirname } from "path"

// Notebook editing (issue #68) — create a fresh notebook (e.g. 00_overview.ipynb).

export default tool({
  description:
    "Create a new, empty notebook at a path (e.g. ./notebooks/00_overview.ipynb), " +
    "optionally with a title as its first markdown cell. Use for a notebook you " +
    "author from scratch (like the overview) before adding cells. Refuses to " +
    "overwrite an existing file.",

  args: {
    notebook: tool.schema.string().describe("Path for the new .ipynb file"),
    title: tool.schema.string().optional()
      .describe("Optional title → a first markdown cell '# <title>'"),
  },

  async execute({ notebook, title }) {
    if (existsSync(notebook)) return `ERROR: ${notebook} already exists`
    const cells: any[] = []
    if (title)
      cells.push({ cell_type: "markdown", metadata: {}, source: [`# ${title}\n`] })
    const nb = {
      cells,
      metadata: {
        kernelspec: { name: "python3", display_name: "Python 3" },
        language_info: { name: "python" },
      },
      nbformat: 4, nbformat_minor: 5,
    }
    mkdirSync(dirname(notebook), { recursive: true })
    writeFileSync(notebook, JSON.stringify(nb, null, 1) + "\n")
    return `Created ${notebook}${title ? ` with title "${title}"` : ""}`
  },
})
