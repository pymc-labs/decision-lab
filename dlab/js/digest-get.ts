import { tool } from "@opencode-ai/plugin"
// Use require() for Node builtins — ESM imports break under Bun's strict interop
const { readFileSync } = require("fs")
const { join } = require("path")

// Deliberately dumb retrieval tool (issue #85): the host-side Python digest
// owns all the intelligence and writes _digest/index.json mapping every ID to
// {log_file, line_no, line_end?, event_type}. This tool just looks up one ID,
// reads that line (or line range, for a raw_text block), extracts the payload,
// and renders it DECODED (clean stdout/stderr, not escaped JSON) with slicing.

export default tool({
  description:
    "Retrieve a single log element by its digest ID (the [tN]/[xN]/[rN]/[p0] ids in _digest/digest.md). " +
    "IDs are fully qualified, e.g. 'main/t2', 'poet.r1.i2/x8', 'poet.r1.i2/r11'. Returns the decoded payload: " +
    "for a tool call (tN) its input plus clean stdout/stderr; for a raw_text stream (rN) the verbatim " +
    "stdout/stderr the run emitted — this is what you embed as a cell's stream output; for a text id (xN) " +
    "the verbatim reasoning; for p0 the full prompt. Use head/tail/range to slice long output (e.g. a PyMC " +
    "fit log) instead of paying for all of it.",

  args: {
    id: tool.schema.string().describe("Fully-qualified digest ID, e.g. 'poet.r1.i2/r11'"),
    head: tool.schema.number().optional().describe("Return only the first N lines of the payload"),
    tail: tool.schema.number().optional().describe("Return only the last N lines of the payload"),
    range: tool.schema.string().optional().describe("Return lines A-B of the payload, e.g. '10-40'"),
  },

  async execute({ id, head, tail, range }) {
    const cwd = process.cwd()
    let index: Record<string, { log_file: string; line_no: number; line_end?: number; event_type: string }>
    try {
      index = JSON.parse(readFileSync(join(cwd, "_digest", "index.json"), "utf-8"))
    } catch {
      return "ERROR: _digest/index.json not found — generate the digest first."
    }
    const entry = index[id]
    if (!entry) return `ERROR: unknown digest id '${id}'`

    let selected: string[]
    try {
      const content = readFileSync(join(cwd, entry.log_file), "utf-8").split("\n")
      const end = entry.line_end ?? entry.line_no
      selected = content.slice(entry.line_no - 1, end) // 1-based inclusive
    } catch {
      return `ERROR: cannot read ${entry.log_file}`
    }

    // raw_text: a block of plain stdout/stderr lines, no JSON. Strip the
    // [STDERR] markers so it reads as clean output ready to embed.
    if (entry.event_type === "raw_text") {
      const text = selected.map((l) => l.replace(/^\[STDERR\]\s?/, "")).join("\n")
      return sliceText(text, head, tail, range)
    }

    const rawLine = selected[0] ?? ""
    let obj: any
    try {
      obj = JSON.parse(rawLine)
    } catch {
      return sliceText(rawLine, head, tail, range) // non-JSON line: return as-is
    }
    return sliceText(renderPayload(obj, entry.event_type), head, tail, range)
  },
})

function renderPayload(obj: any, eventType: string): string {
  const part = obj.part ?? {}
  if (eventType === "text") return String(part.text ?? "")
  if (eventType === "dlab_start") return String(obj.prompt ?? part.prompt ?? "")
  if (eventType === "tool_use") {
    const state = part.state ?? {}
    const input = JSON.stringify(state.input ?? {}, null, 2)
    const output = stripLsp(state.output ?? state.error ?? "")
    return `# input\n${input}\n\n# output\n${output}`
  }
  return JSON.stringify(obj, null, 2)
}

// Drop the LSP/type-checker diagnostics opencode appends to write/edit output —
// false positives that otherwise pollute retrieval (composer feedback).
function stripLsp(text: string): string {
  return text
    .replace(/<diagnostics\b[^>]*>[\s\S]*?<\/diagnostics>/g, "")
    .replace(/\n*LSP errors detected[^\n]*/g, "")
    .replace(/\s+$/, "")
}

function sliceText(text: string, head?: number, tail?: number, range?: string): string {
  const lines = text.split("\n")
  if (range) {
    const [a, b] = range.split("-").map((n) => parseInt(n, 10))
    return lines.slice(a - 1, b).join("\n")
  }
  if (head) return lines.slice(0, head).join("\n")
  if (tail) return lines.slice(-tail).join("\n")
  return text
}
