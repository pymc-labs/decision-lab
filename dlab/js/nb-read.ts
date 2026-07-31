import { tool } from "@opencode-ai/plugin"
import { readFileSync, existsSync } from "fs"

// Cell-level notebook composition (issue #86). Compact, base64-STRIPPED read:
// agents must never read raw ipynb — the base64 is the same context poison we
// keep out of writing. One line per cell: index, type, execution_count, an
// output summary (figure paths + stream line counts), and a source preview.

function srcText(source: any): string {
  return (typeof source === "string" ? source : (source ?? []).join(""))
}

export default tool({
  description:
    "Read a notebook as a COMPACT summary — one line per cell, base64 image data stripped. " +
    "Shows each cell's index, type, execution_count, a summary of its outputs (figure paths and " +
    "stream line counts, never the bytes), and a truncated source preview. Use this instead of " +
    "opening the .ipynb, whose embedded base64 would flood your context.",

  args: {
    notebook: tool.schema.string().describe("Path to the .ipynb file"),
    head: tool.schema.number().optional()
      .describe("Preview only the first N source chars per cell (default 80)"),
  },

  async execute({ notebook, head }) {
    if (!existsSync(notebook)) return `ERROR: ${notebook} not found`
    let nb: any
    try {
      nb = JSON.parse(readFileSync(notebook, "utf-8"))
    } catch {
      return `ERROR: ${notebook} is not valid JSON`
    }
    const n = head ?? 80
    const cells = nb.cells ?? []
    const lines: string[] = []
    for (let i = 0; i < cells.length; i++) {
      const c = cells[i]
      const src = srcText(c.source).replace(/\s+/g, " ").trim()
      const preview = src.length > n ? src.slice(0, n - 1) + "…" : src
      if (c.cell_type === "code") {
        const outs: string[] = []
        for (const o of c.outputs ?? []) {
          if (o.output_type === "display_data" || o.output_type === "execute_result")
            outs.push(`image: ${o.metadata?.dlab_source ?? "inline"}`)
          else if (o.output_type === "stream")
            outs.push(`stream ${srcText(o.text).split("\n").length} ln`)
          else if (o.output_type === "error")
            outs.push("error")
        }
        const tags = c.metadata?.tags?.length ? ` tags=[${c.metadata.tags.join(",")}]` : ""
        const outSum = outs.length ? `, ${outs.join(", ")}` : ", no output"
        lines.push(`cell ${i} [code, exec ${c.execution_count ?? "·"}${tags}${outSum}]: ${preview}`)
      } else {
        lines.push(`cell ${i} [${c.cell_type}]: ${preview}`)
      }
    }
    return lines.length ? lines.join("\n") : `(${notebook} has no cells)`
  },
})
