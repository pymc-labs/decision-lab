import { tool } from "@opencode-ai/plugin"
import { readFileSync, mkdirSync, writeFileSync, existsSync, appendFileSync, readdirSync, copyFileSync, cpSync, statSync } from "fs"
// Use require() for CJS package — ESM imports break under Bun's strict interop
const yaml = require("yaml")
import { join, basename } from "path"

// Helper: Copy directory contents excluding certain paths
function copyWorkDir(src: string, dest: string, exclude: string[]) {
  mkdirSync(dest, { recursive: true })
  for (const item of readdirSync(src)) {
    if (exclude.includes(item)) continue
    const srcPath = join(src, item)
    const destPath = join(dest, item)
    const stat = statSync(srcPath)
    if (stat.isDirectory()) {
      cpSync(srcPath, destPath, { recursive: true })
    } else {
      copyFileSync(srcPath, destPath)
    }
  }
}

// Helper: Parse YAML frontmatter from agent markdown
function parseAgentFrontmatter(agentPath: string): Record<string, any> {
  const content = readFileSync(agentPath, "utf-8")
  const match = content.match(/^---\n([\s\S]*?)\n---/)
  if (!match) return {}
  return yaml.parse(match[1])
}

// Helper: Build permission config from agent frontmatter tools
// Some permissions support nested objects (read, edit, glob, grep, list, bash, task, external_directory, lsp)
// Others only accept simple strings (todoread, todowrite, question, webfetch, websearch, codesearch, doom_loop)
function buildPermissionsFromFrontmatter(agentPath: string): Record<string, any> {
  const frontmatter = parseAgentFrontmatter(agentPath)
  const tools = frontmatter.tools || {}

  return {
    // Permissions that support nested objects - use { "*": "action" } format
    "read": { "*": "allow" },
    "glob": { "*": "allow" },
    "grep": { "*": "allow" },
    "list": { "*": "allow" },
    "lsp": { "*": "allow" },
    "external_directory": { "*": "allow" },

    // Write/execute tools - based on frontmatter
    "edit": { "*": tools["edit"] === true ? "allow" : "deny" },
    "bash": { "*": tools["bash"] === true ? "allow" : "deny" },

    // Subagent spawning - deny
    "task": { "*": "deny" },

    // Simple string permissions
    "todoread": "allow",
    "todowrite": tools["edit"] === true ? "allow" : "deny",
    "question": "deny",
    "webfetch": "allow",
    "websearch": "allow",
    "codesearch": "allow",
    "doom_loop": "allow",
  }
}

// Helper: Setup minimal consolidator environment (read-only, no custom tools)
function setupConsolidator(runDir: string, srcOpencode: string, summarizerPrompt: string) {
  const destOpencode = join(runDir, ".opencode")

  // Create directories
  mkdirSync(join(destOpencode, "agents"), { recursive: true })

  // Create minimal consolidator agent from summarizer_prompt
  const consolidatorAgent = `---
description: Consolidator agent for comparing parallel agent results
mode: primary
tools:
  read: true
  edit: false
  bash: false
  parallel-agents: false
---

${summarizerPrompt}
`
  writeFileSync(join(destOpencode, "agents", "consolidator.md"), consolidatorAgent)

  // Copy and modify opencode.json
  const opconfig = JSON.parse(readFileSync(join(srcOpencode, "opencode.json"), "utf-8"))
  opconfig.default_agent = "consolidator"

  // Hardcoded read-only permissions for consolidator
  opconfig.permission = {
    // Read/discovery tools - always allowed
    "read": { "*": "allow" },
    "glob": { "*": "allow" },
    "grep": { "*": "allow" },
    "list": { "*": "allow" },
    "lsp": { "*": "allow" },
    "external_directory": { "*": "allow" },

    // Write/execute tools - always denied
    "edit": { "*": "deny" },
    "bash": { "*": "deny" },
    "task": { "*": "deny" },

    // Simple permissions
    "todoread": "allow",
    "todowrite": "deny",
    "question": "deny",
    "webfetch": "allow",
    "websearch": "allow",
    "codesearch": "allow",
    "doom_loop": "allow",
  }

  writeFileSync(join(destOpencode, "opencode.json"), JSON.stringify(opconfig, null, 2))

  // NOTE: Do NOT copy tools/ directory - consolidator has no custom tools
}

// Helper: Copy only allowed tools based on agent frontmatter
function copyAllowedTools(srcOpencode: string, destOpencode: string, agentName: string) {
  const agentPath = join(srcOpencode, "agents", `${agentName}.md`)
  const frontmatter = parseAgentFrontmatter(agentPath)
  const tools = frontmatter.tools || {}

  // Create dest directories
  mkdirSync(join(destOpencode, "agents"), { recursive: true })
  mkdirSync(join(destOpencode, "tools"), { recursive: true })

  // Copy opencode.json and package.json
  copyFileSync(join(srcOpencode, "opencode.json"), join(destOpencode, "opencode.json"))
  if (existsSync(join(srcOpencode, "package.json"))) {
    copyFileSync(join(srcOpencode, "package.json"), join(destOpencode, "package.json"))
  }

  // NOTE: Do NOT copy parallel_agents/ to subagents - only orchestrator needs it

  // Copy the target agent definition, converting subagent to primary mode
  // (OpenCode doesn't allow subagents to be the default_agent)
  let agentContent = readFileSync(agentPath, "utf-8")
  agentContent = agentContent.replace(/^(---.*)mode:\s*subagent(.*---)$/ms, "$1mode: primary$2")
  writeFileSync(join(destOpencode, "agents", `${agentName}.md`), agentContent)

  // Copy only tools that are explicitly allowed (true in frontmatter)
  const srcTools = join(srcOpencode, "tools")
  if (existsSync(srcTools)) {
    for (const file of readdirSync(srcTools)) {
      const toolName = file.replace(/\.(ts|js)$/, "")
      // NEVER copy parallel-agents to subagents
      if (toolName === "parallel-agents") continue
      // Only copy if explicitly allowed
      if (tools[toolName] === true) {
        copyFileSync(join(srcTools, file), join(destOpencode, "tools", file))
      }
    }
  }

  // Copy skills declared in frontmatter
  const skills = frontmatter.skills || []
  if (skills.length > 0) {
    const srcSkills = join(srcOpencode, "skills")
    if (existsSync(srcSkills)) {
      for (const skillName of skills) {
        const srcSkill = join(srcSkills, skillName)
        if (existsSync(srcSkill)) {
          const destSkill = join(destOpencode, "skills", skillName)
          cpSync(srcSkill, destSkill, { recursive: true })
        }
      }
    }
  }
}

export default tool({
  description: "Spawn parallel subagents for a configured agent type",

  args: {
    agent: tool.schema.string().describe("Agent name (must have config in parallel_agents/)"),
    prompts: tool.schema.array(tool.schema.string()).describe("Array of prompts, one per instance"),
    models: tool.schema.array(tool.schema.string()).optional()
      .describe("Optional: model per instance (defaults to config default_model)"),
  },

  async execute(args, ctx) {
    const cwd = process.cwd()
    const timestamp = Date.now()
    const runDir = join(cwd, "parallel", `run-${timestamp}`)
    const logsDir = join(cwd, "_opencode_logs", `${args.agent}-parallel-run-${timestamp}`)

    // Load parallel agent config
    const configPath = join(cwd, ".opencode", "parallel_agents", `${args.agent}.yaml`)
    if (!existsSync(configPath)) {
      throw new Error(`No parallel config found: ${configPath}`)
    }
    const config = yaml.parse(readFileSync(configPath, "utf-8"))

    // Validate instance count
    const numInstances = args.prompts.length
    if (numInstances < 1) {
      throw new Error("At least 1 prompt required")
    }
    if (config.max_instances && numInstances > config.max_instances) {
      throw new Error(`Max ${config.max_instances} instances allowed, got ${numInstances}`)
    }

    mkdirSync(runDir, { recursive: true })
    mkdirSync(logsDir, { recursive: true })

    // Spawn instances
    const processes: Array<{
      proc: ReturnType<typeof Bun.spawn>
      dir: string
      logFile: string
      model: string
      prompt: string
    }> = []

    for (let i = 0; i < numInstances; i++) {
      const instanceDir = join(runDir, `instance-${i + 1}`)
      mkdirSync(instanceDir, { recursive: true })

      // HACK: Initialize git repo to stop OpenCode config traversal to parent directories.
      // This is an EVIL HACK. OpenCode traverses up looking for .opencode/ configs and merges
      // them, causing subagents to see parent agents and get confused about their role.
      // Creating a .git dir makes OpenCode think this is a project root, stopping traversal.
      // TODO: Replace with proper solution when OpenCode supports disabling parent traversal.
      Bun.spawnSync(["git", "init"], { cwd: instanceDir, stdout: "ignore", stderr: "ignore" })

      // Copy entire work directory to instance (excluding special dirs)
      // This gives subagents access to all work done by the orchestrator so far
      copyWorkDir(cwd, instanceDir, [".opencode", "_opencode_logs", "parallel", ".state.json", ".git"])

      // Copy .opencode with ONLY allowed tools
      copyAllowedTools(join(cwd, ".opencode"), join(instanceDir, ".opencode"), args.agent)

      // Set default agent AND build granular permissions from frontmatter
      const opconfigPath = join(instanceDir, ".opencode", "opencode.json")
      const opconfig = JSON.parse(readFileSync(opconfigPath, "utf-8"))
      opconfig.default_agent = args.agent

      // Build permissions based on agent's tools frontmatter
      const agentPath = join(cwd, ".opencode", "agents", `${args.agent}.md`)
      opconfig.permission = buildPermissionsFromFrontmatter(agentPath)

      writeFileSync(opconfigPath, JSON.stringify(opconfig, null, 2))

      // Build prompt with subagent context and suffix
      // Model priority: 1) explicit models array, 2) instance_models from config, 3) default_model
      const instanceModels = config.instance_models || []
      const model = args.models?.[i] || instanceModels[i] || config.default_model

      // Automatic subagent context (always added to prevent hangs and enforce workspace boundaries)
      const subagentContext = `IMPORTANT CONTEXT: You are running as a parallel subagent in non-interactive mode.

YOUR WORKING DIRECTORY: ${instanceDir}

CRITICAL OUTPUT RULES:
- Write ALL output files to the ROOT of your working directory
- Do NOT create subdirectories - write directly to: ${instanceDir}/
- Required outputs:
  - summary.md -> ${instanceDir}/summary.md
  - cleaned_data.parquet -> ${instanceDir}/cleaned_data.parquet (if applicable)
- You may READ files from absolute paths if mentioned in your prompt
- You must NEVER WRITE or EDIT files outside your working directory
- NEVER ask for permission or confirmation - all operations are pre-approved or pre-denied
- If an operation fails, report the error and continue with alternatives

`
      const fullPrompt = subagentContext + args.prompts[i] + "\n\n" + (config.subagent_suffix_prompt || "")

      const logFile = join(logsDir, `instance-${i + 1}.log`)

      // Write dlab_start event as first line (model, agent, prompt)
      writeFileSync(logFile, JSON.stringify({type: "dlab_start", timestamp: Date.now(), model, agent: args.agent, prompt: fullPrompt}) + "\n")

      const proc = Bun.spawn(["opencode", "run", "--format", "json", "--log-level", "DEBUG", "--model", model, fullPrompt], {
        cwd: instanceDir,
        stdout: "pipe",
        stderr: "pipe",
        env: process.env,  // Inherit PYTHONPATH and other env vars
      })

      // Stream to logs (async)
      ;(async () => {
        const reader = proc.stdout.getReader()
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          appendFileSync(logFile, new TextDecoder().decode(value))
        }
      })()
      ;(async () => {
        const reader = proc.stderr.getReader()
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          appendFileSync(logFile, "[STDERR] " + new TextDecoder().decode(value))
        }
      })()

      processes.push({ proc, dir: instanceDir, logFile, model, prompt: args.prompts[i] })
    }

    // Wait for all
    const results: Array<{
      dir: string
      summaryPath: string
      exitCode: number | null
    }> = []

    for (const p of processes) {
      await p.proc.exited
      results.push({
        dir: p.dir,
        summaryPath: join(p.dir, "summary.md"),
        exitCode: p.proc.exitCode,
      })
    }

    // Run consolidator if >= 3 instances completed
    // For n=2, the orchestrator can read both summaries directly
    let consolidatedSummary = ""
    if (numInstances >= 3 && config.summarizer_prompt) {
      // Use ABSOLUTE paths so consolidator doesn't need to search
      const summaryPaths = results
        .filter(r => existsSync(r.summaryPath))
        .map(r => r.summaryPath)  // Already absolute paths

      const consolidatedSummaryPath = join(runDir, "consolidated_summary.md")

      // Build consolidator prompt with absolute paths and explicit output location
      const consolidatorContext = `IMPORTANT CONTEXT: You are running as a consolidator subagent in non-interactive mode.

READ ONLY THESE EXACT FILES (do NOT search or glob):
${summaryPaths.map((p: string) => `- ${p}`).join("\n")}

WRITE YOUR OUTPUT TO: ${consolidatedSummaryPath}

RULES:
- NEVER ask for permission or confirmation - all operations are pre-approved or pre-denied
- NEVER use glob or search for files - read the exact paths listed above
- If an operation fails, report the error and continue with alternatives

`
      const consolidatorPrompt = consolidatorContext + config.summarizer_prompt
        .replace("{summary_paths}", summaryPaths.map((p: string) => `- ${p}`).join("\n"))

      const consolidatorModel = config.summarizer_model || config.default_model

      // HACK: Initialize git repo to stop OpenCode config traversal (same as instances)
      // Without this, OpenCode traverses up and merges parent's .opencode/, running as orchestrator
      Bun.spawnSync(["git", "init"], { cwd: runDir, stdout: "ignore", stderr: "ignore" })

      // Setup minimal consolidator environment (read-only, no custom tools)
      setupConsolidator(runDir, join(cwd, ".opencode"), config.summarizer_prompt)

      const consLogFile = join(logsDir, "consolidator.log")

      // Write dlab_start event as first line
      writeFileSync(consLogFile, JSON.stringify({type: "dlab_start", timestamp: Date.now(), model: consolidatorModel, agent: "consolidator", prompt: consolidatorPrompt}) + "\n")

      const consProc = Bun.spawn(["opencode", "run", "--format", "json", "--log-level", "DEBUG", "--model", consolidatorModel, consolidatorPrompt], {
        cwd: runDir,
        stdout: "pipe",
        stderr: "pipe",
        env: process.env,  // Inherit PYTHONPATH and other env vars
      })

      // Stream stdout to log file (don't use as summary - it's JSON logs)
      const reader = consProc.stdout.getReader()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        appendFileSync(consLogFile, new TextDecoder().decode(value))
      }
      await consProc.exited

      // Read the consolidated summary from file (not stdout)
      if (existsSync(consolidatedSummaryPath)) {
        consolidatedSummary = readFileSync(consolidatedSummaryPath, "utf-8")
      } else {
        consolidatedSummary = "[Consolidator did not produce a summary file]"
      }
    }

    // Build final output
    let finalOutput = "## Parallel Agent Results\n\n"
    finalOutput += `Ran ${numInstances} instances of agent: ${args.agent}\n\n`

    for (const r of results) {
      finalOutput += `### ${basename(r.dir)}\n`
      finalOutput += `- Exit code: ${r.exitCode}\n`
      if (existsSync(r.summaryPath)) {
        finalOutput += `- Summary: ${r.summaryPath}\n`
      }
      finalOutput += "\n"
    }

    if (consolidatedSummary) {
      finalOutput += "## Consolidated Summary\n\n"
      finalOutput += consolidatedSummary + "\n\n"
      finalOutput += "---\n\n"
      finalOutput += "If you need more details, individual summaries are at:\n"
      for (const r of results) {
        if (existsSync(r.summaryPath)) {
          finalOutput += `- ${r.summaryPath}\n`
        }
      }
    } else {
      // No consolidator (n <= 2) - tell orchestrator where to find summaries
      finalOutput += "## Summary Locations\n\n"
      finalOutput += "Read these summary files to compare results:\n"
      for (const r of results) {
        if (existsSync(r.summaryPath)) {
          finalOutput += `- ${r.summaryPath}\n`
        }
      }
    }

    return finalOutput
  },
})
