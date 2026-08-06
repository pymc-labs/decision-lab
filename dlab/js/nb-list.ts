import { tool } from "@opencode-ai/plugin"
import { readFileSync, readdirSync, statSync, existsSync } from "fs"
import { join } from "path"

// Notebook editing (issue #68) — survey the notebooks so the composer can plan.

function ipynbUnder(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...ipynbUnder(p))
    else if (name.endsWith(".ipynb")) out.push(p)
  }
  return out.sort()
}

export default tool({
  description:
    "List every notebook under a directory (recursively) with a one-line summary: " +
    "cell counts by type, figures, and — for skeletons — the phase and whether it is " +
    "the adopted path or an attempt. Use to plan the composition before editing.",

  args: {
    dir: tool.schema.string().describe("Directory to scan for .ipynb files"),
  },

  async execute({ dir }) {
    if (!existsSync(dir)) return `ERROR: ${dir} not found`
    const files = ipynbUnder(dir)
    if (!files.length) return `(no .ipynb under ${dir})`
    const lines: string[] = []
    for (const f of files) {
      let nb: any
      try { nb = JSON.parse(readFileSync(f, "utf-8")) } catch { lines.push(`${f}: invalid JSON`); continue }
      const cells = nb.cells ?? []
      const code = cells.filter((c: any) => c.cell_type === "code").length
      const md = cells.filter((c: any) => c.cell_type === "markdown").length
      const figs = cells.reduce((n: number, c: any) =>
        n + (c.outputs ?? []).filter((o: any) => o.output_type === "display_data").length, 0)
      const d = nb.metadata?.dlab
      const tag = d ? (d.phase ? `${d.phase}/${d.adopted ? "adopted" : "attempt"}` : "orchestrator") : ""
      lines.push(`${f}: ${code} code, ${md} md, ${figs} fig${tag ? ` [${tag}]` : ""}`)
    }
    return lines.join("\n")
  },
})
