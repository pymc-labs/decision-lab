import { tool } from "@opencode-ai/plugin"
import { readFileSync, writeFileSync, existsSync } from "fs"

// Cell-level notebook composition (issue #86) — replace a cell's source/outputs
// by index (for fixes). Index-based like every kernel-free notebook MCP; the
// composer mostly appends, so shifting indices on insert is not a concern here.

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

function escapeDollar(text: string, math?: boolean): string {
  return math ? text : text.replace(/\$/g, "\\$")
}

function imageOutput(path: string): any {
  const ext = path.toLowerCase().split(".").pop() ?? ""
  const mime =
    ext === "jpg" || ext === "jpeg" ? "image/jpeg" :
    ext === "gif" ? "image/gif" :
    ext === "svg" ? "image/svg+xml" : "image/png"
  const data: any = {}
  data[mime] = mime === "image/svg+xml"
    ? readFileSync(path, "utf-8")
    : readFileSync(path).toString("base64")
  return { output_type: "display_data", data, metadata: { dlab_source: path } }
}

function streamOutput(text: string): any {
  return { output_type: "stream", name: "stdout", text }
}

function buildOutputs(outputs: any[]): any[] {
  const built: any[] = []
  for (const o of outputs ?? []) {
    if (o && o.image) built.push(imageOutput(o.image))
    else if (o && o.stream !== undefined) built.push(streamOutput(o.stream))
  }
  return built
}

export default tool({
  description:
    "Replace the source and/or outputs of an existing cell by 0-based index (for fixes). " +
    "Pass `text` for a markdown cell, `code` for a code cell, and/or `outputs` (same shape as " +
    "nb-add-code-cell) to rebuild the cell's outputs.",

  args: {
    notebook: tool.schema.string().describe("Path to the .ipynb file"),
    index: tool.schema.number().describe("0-based cell index to edit"),
    text: tool.schema.string().optional().describe("New markdown source (markdown cells)"),
    code: tool.schema.string().optional().describe("New Python source (code cells)"),
    math: tool.schema.boolean().optional().describe("Keep '$' literal (markdown cells)"),
    outputs: tool.schema.array(tool.schema.object({
      image: tool.schema.string().optional(),
      stream: tool.schema.string().optional(),
    })).optional().describe("Replacement outputs (code cells)"),
  },

  async execute({ notebook, index, text, code, math, outputs }) {
    const nb = loadNb(notebook)
    const cell = (nb.cells ?? [])[index]
    if (!cell) return `ERROR: no cell at index ${index} (notebook has ${nb.cells?.length ?? 0} cells)`
    if (cell.cell_type === "markdown" && text !== undefined) cell.source = escapeDollar(text, math)
    if (cell.cell_type === "code" && code !== undefined) cell.source = code
    if (outputs !== undefined && cell.cell_type === "code") cell.outputs = buildOutputs(outputs)
    saveNb(notebook, nb)
    return `Edited cell ${index} [${cell.cell_type}] in ${notebook}`
  },
})
