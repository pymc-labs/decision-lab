import { tool } from "@opencode-ai/plugin"
import { readFileSync, writeFileSync, existsSync } from "fs"

// Cell-level notebook composition (issue #86). Finalize: inject the mandatory
// provenance header (idempotent) and write canonical ipynb JSON. Without the
// header these notebooks — which LOOK executed (embedded outputs, execution
// counts) — are indistinguishable from genuinely executed ones; the header is
// exactly the silent-fiction guard this project exists to avoid.

const HEADER_MARK = "Auto-composed from session artifacts"

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
  writeFileSync(path, JSON.stringify(nb, null, 1) + "\n")
}

function srcText(source: any): string {
  return (typeof source === "string" ? source : (source ?? []).join(""))
}

export default tool({
  description:
    "Finalize a notebook: inject the provenance header cell at the top (idempotent — safe to call " +
    "again) and write canonical ipynb JSON with the required nbformat fields. Call once when the " +
    "notebook is complete.",

  args: {
    notebook: tool.schema.string().describe("Path to the .ipynb file"),
  },

  async execute({ notebook }) {
    const nb = loadNb(notebook)
    if (!nb.cells) nb.cells = []
    // The first cell is always the markdown "preamble": the provenance line
    // pinned to the very top, above any nb-note disclosures already collected
    // there. Keep provenance + notes in ONE cell rather than stacking cells.
    const header =
      `> **${HEADER_MARK}.** Outputs are embedded from the original run — this notebook was ` +
      `composed, not executed. Open it to explore and re-run the analysis yourself.`
    const first = nb.cells[0]
    if (first && first.cell_type === "markdown") {
      const s = srcText(first.source)
      if (!s.includes(HEADER_MARK)) first.source = header + "\n\n" + s
    } else {
      nb.cells.unshift({ cell_type: "markdown", metadata: {}, source: header })
    }
    nb.nbformat = 4
    if (nb.nbformat_minor == null) nb.nbformat_minor = 5
    if (!nb.metadata) {
      nb.metadata = {
        kernelspec: { name: "python3", display_name: "Python 3" },
        language_info: { name: "python" },
      }
    }
    saveNb(notebook, nb)
    return `Finalized ${notebook} (${nb.cells.length} cells, provenance header present)`
  },
})
