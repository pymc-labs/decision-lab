import { tool } from "@opencode-ai/plugin"
import { readFileSync, writeFileSync, existsSync } from "fs"

// Cell-level notebook composition (issue #86). The model never writes ipynb
// JSON or base64 — it passes text, code, and figure PATHS; the tool renders the
// canonical JSON. ipynb is just JSON; base64 is a few lines of Bun. Zero deps.

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

function nextExecCount(nb: any): number {
  let m = 0
  for (const c of nb.cells ?? [])
    if (c.cell_type === "code" && typeof c.execution_count === "number")
      m = Math.max(m, c.execution_count)
  return m + 1
}

function imageOutput(path: string): any {
  const ext = path.toLowerCase().split(".").pop() ?? ""
  const mime =
    ext === "jpg" || ext === "jpeg" ? "image/jpeg" :
    ext === "gif" ? "image/gif" :
    ext === "svg" ? "image/svg+xml" : "image/png"
  const data: any = {}
  // SVG is text; raster formats are base64. The source path is kept in
  // metadata so nb-read can name the figure without decoding the bytes.
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
    "Append a code cell to a notebook (created if missing). Pass the Python source as `code`. " +
    "Pass `outputs` as a list of {image: <path>} or {stream: <text>} — the tool reads the figure " +
    "file and base64-encodes it into a proper display_data output; you pass PATHS, never base64. " +
    "execution_count is assigned automatically. Use tags like ['long-running'] for expensive cells.",

  args: {
    notebook: tool.schema.string().describe("Path to the .ipynb file"),
    code: tool.schema.string().describe("The cell's Python source"),
    outputs: tool.schema.array(tool.schema.object({
      image: tool.schema.string().optional().describe("Path to a figure file to embed"),
      stream: tool.schema.string().optional().describe("Captured stdout/stderr text"),
    })).optional().describe("Cell outputs, in order"),
    tags: tool.schema.array(tool.schema.string()).optional()
      .describe("Cell metadata tags, e.g. ['long-running']"),
  },

  async execute({ notebook, code, outputs, tags }) {
    const nb = loadNb(notebook)
    const built = buildOutputs(outputs ?? [])
    const cell: any = {
      cell_type: "code",
      execution_count: nextExecCount(nb),
      metadata: tags && tags.length ? { tags } : {},
      outputs: built,
      source: code,
    }
    nb.cells.push(cell)
    saveNb(notebook, nb)
    return `Added code cell ${nb.cells.length - 1} (exec ${cell.execution_count}, ${built.length} output(s)) to ${notebook}`
  },
})
