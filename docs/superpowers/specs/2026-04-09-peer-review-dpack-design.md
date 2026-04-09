# Peer Review Decision Pack — Design Spec

## Overview

A decision pack for Decision Lab that simulates academic peer review using parallel structural reviewer agents. The system decomposes a paper into atomic claims, builds a reference knowledge base from cited literature, then fans out structural reviewer roles (claim-verifier, methodology-auditor, novelty-assessor, clarity-evaluator, significance-assessor) across multiple LLM models. An orchestrator-mediated discussion phase surfaces and resolves disagreements. The final output is a structured review report with per-dimension assessments, claim-level evidence, and an accept/reject recommendation with conflict detection.

**Goal**: Not a replacement for human review, but a rigorous pre-submission check ("how would reviewers likely respond to this draft?") and a research tool for studying peer review dynamics.

**Scope (v1)**: Core review pipeline. SSR scoring, venue-specific configs, and the OpenReview validation harness are deferred to v2. Output format is designed for future validation harness consumption.

## Decision Pack Structure

```
decision-packs/peer-review/
├── config.yaml
├── docker/
│   ├── Dockerfile
│   └── peer_review_lib/
│       ├── __init__.py
│       ├── parse_paper.py
│       └── fetch_references.py
├── opencode/
│   ├── opencode.json
│   ├── agents/
│   │   ├── orchestrator.md
│   │   ├── decomposer.md
│   │   ├── reference-analyst.md
│   │   └── reviewer.md
│   ├── tools/
│   │   ├── parse-paper.ts
│   │   └── fetch-references.ts
│   ├── skills/
│   │   ├── review-rubric/SKILL.md
│   │   ├── common-flaws/SKILL.md
│   │   └── methodology/SKILL.md
│   └── parallel_agents/
│       ├── decomposer.yaml
│       ├── reference-analyst.yaml
│       └── reviewer.yaml
```

## Configuration Files

### config.yaml

```yaml
name: peer-review
description: Simulated academic peer review using parallel structural reviewers
docker_image_name: dlab-peer-review
default_model: anthropic/claude-opus-4-5
requires_prompt: false
```

`requires_prompt: false` — the paper is the input. Usage:
```
dlab --dpack decision-packs/peer-review --data paper.pdf
```

### opencode.json

```json
{
  "default_agent": "orchestrator",
  "permission": {
    "external_directory": { "*": "allow" }
  }
}
```

## Orchestrator Workflow

The orchestrator is the area chair. It drives the full pipeline.

### Step 1: Paper Parsing

Orchestrator uses `parse-paper` tool on input file(s) in `data/`. Gets structured text with section boundaries. Writes `paper_structure.md`:

- Paper title, abstract
- Section hierarchy
- Source format (PDF or LaTeX)
- Parsing issues (garbled equations, missing figures)
- Initial domain identification
- Citation list extracted

### Step 2: Claim Decomposition (Fan-out 1)

Orchestrator calls `parallel-agents` with the decomposer agent. 2 instances, different models (Opus + Gemini), same prompt. Each decomposer:

- Extracts every atomic claim from the paper
- Classifies each: empirical, methodological, novelty, scope
- Maps each claim to the paper section it appears in
- Identifies dependencies between claims (claim B relies on claim A)
- Assesses evidence strength: asserted / supported / proven

Consolidator merges into canonical `claims_index.json` — deduplicated, with provenance (which models found each claim, disagreements flagged).

### Step 3: Reference Knowledge Base (Fan-out 2)

Orchestrator calls `parallel-agents` with the reference-analyst agent. 2 instances, different models. Each reference-analyst:

- Takes the citation list from Step 1
- Uses `fetch-references` tool to get abstracts + metadata from Semantic Scholar API for ALL cited papers
- Writes a `reference_kb/` directory to disk:

```
reference_kb/
├── index.md              # Full citation list with found/not-found status
├── papers/
│   ├── smith2023.md      # One file per cited paper
│   ├── chen2024.md
│   └── ...
└── analysis.md           # Contradictions, mischaracterizations, missing refs
```

Each paper file contains:
- Title, authors, venue, year, citation count
- Abstract
- Key claims (extracted from abstract)
- How the reviewed paper cites it (quoted from the paper, with section reference)
- Characterization accuracy assessment (accurate / inaccurate / partial, with reasoning)

`analysis.md` covers:
- Mischaracterizations found
- Contradictions between cited works and the paper's claims
- Potentially missing references (via Semantic Scholar related papers)
- Citation patterns (heavy self-citation, recency bias, missing seminal work)

The `reference_kb/` directory lives on disk so any downstream agent can `read` or `grep` into it.

### Step 4: Review Consolidated Outputs

Orchestrator copies the consolidated `reference_kb/` from the reference-analyst run directory to the main workspace (`/workspace/reference_kb/`) so all downstream agents can access it via read/grep.

Orchestrator reads:
- Consolidated claim index from Step 2
- Reference KB analysis from Step 3

Checks:
- Are the two decomposers broadly consistent?
- Are there claims one model found that the other missed?
- Does the claim dependency graph make sense?
- Did the reference-analysts flag any mischaracterizations or missing citations?

Writes `pre_review_assessment.md` with the finalized claim index and reference analysis notes.

### Step 5: Construct Review Matrix (MANDATORY)

The orchestrator MUST spawn ALL 5 structural roles. This is not a creative decision — the role set is fixed:

| Role | Focus | Dimensions Covered |
|------|-------|--------------------|
| claim-verifier | Each claim against evidence presented | Rigor, Reproducibility |
| methodology-auditor | Statistical/experimental methods | Rigor, Reproducibility |
| novelty-assessor | Claims vs related work | Novelty, Related Work |
| clarity-evaluator | Writing, structure, figures | Clarity |
| significance-assessor | Impact, scope, implications | Significance |

For EACH role, the orchestrator creates one prompt per model in `instance_models`. The prompt includes:
- Full paper text
- Claims index
- Reference to `reference_kb/` directory (agents grep as needed)
- The specific structural role assignment and scope
- Optional domain-specific framing when warranted

5 roles × N models = 5N instances. With 2 models: 10 instances. With 3 models: 15 instances.

The orchestrator constructs `prompts` and `models` arrays explicitly — role-model pairing is intentional:
```
prompts: [claim-verifier-prompt, claim-verifier-prompt, methodology-auditor-prompt, ...]
models:  [opus,                  gemini,                opus,                       ...]
```

Writes `review_matrix.md` documenting the assignments.

### Step 6: Structural Review (Fan-out 3)

`parallel-agents` call with reviewer agent. Each instance writes `summary.md`:

- Structural role assignment
- Per-claim evaluations within scope (claim ID, verdict: supported/unsupported/unclear, reasoning)
- Per-dimension free-text assessments for dimensions in scope
- Strengths (grounded in specific claims)
- Weaknesses (grounded in specific claims)
- References consulted from `reference_kb/`
- Confidence notes (where certain vs uncertain)

Consolidator produces comparison across all reviewers:
- Per-dimension comparison
- Claims where reviewers disagree
- Same-role/different-model agreements and disagreements
- Cross-role tensions

### Step 7: Disagreement Analysis

Orchestrator reads consolidated review + individual reviews. Identifies:

- Same-role/different-model disagreements (model artifact — two claim-verifiers on different models reached different conclusions about the same claim)
- Cross-role tensions (claim-verifier says unsupported, methodology-auditor says method is sound)
- Dimensions with high spread across reviewers
- Specific claims with split verdicts

Ranks disagreements by severity and constructs targeted discussion prompts.

### Step 8: Discussion Rounds (Fan-out 4+)

Orchestrator constructs targeted challenges for each reviewer:

> "Claim verifier (Opus) found Claim 14 unsupported — the convergence bound in Lemma 3 doesn't hold under Assumption 2. Methodology auditor (Gemini) assessed the overall method as sound without flagging this. Respond to the specific Lemma 3 concern. Also review the full critique below. Update your assessments for any dimension where you've changed your mind, and explicitly state what changed and why."

Each reviewer gets:
- Their original review
- All other reviews
- Targeted challenges based on biggest disagreements
- Instruction to explicitly state what changed and why

After discussion fan-out, orchestrator compares pre/post assessments.

**Max 2 rounds** (initial review + 1 discussion). Persistent disagreement is signal, not noise — do not keep iterating.

### Step 9: Conflict Detection

Adapted from MMM pack's conflict detection pattern:

**Check 1: Score Spread** (based on orchestrator's synthesis of text assessments)
| Spread | Assessment |
|--------|------------|
| Reviewers broadly agree | Consensus — confident assessment |
| Minor differences in emphasis | Moderate agreement — note in caveats |
| Fundamental disagreement | Strong disagreement — flag as unresolved |

**Check 2: Accept/Reject Directional Agreement**
| Pattern | Assessment |
|---------|------------|
| All lean accept or all lean reject | Consensus |
| Clear majority (4-1, 5-1 across roles) | Lean with majority, note dissent |
| Even split | Genuinely borderline — report as such |

**Check 3: Critical Flaw Agreement**
| Pattern | Assessment |
|---------|------------|
| Multiple roles confirm flaw | High confidence — critical issue |
| Only one role flags, others don't address | Uncertain — flag for author response |
| One role flags, another explicitly disagrees | Genuine disagreement — report both sides |

### Step 10: Final Report

Writes `report.md` (human-readable) and `report.json` (machine-readable for future validation harness):

- **Recommendation**: Accept / Borderline Accept / Borderline Reject / Reject (with confidence level)
- **Per-dimension assessments**: Synthesized from structural reviewers
- **Consensus areas**: What all reviewers agreed on
- **Disagreement areas**: What remained unresolved and why (with attribution: persona-driven vs model-driven)
- **Claim-level evidence**: Which claims were supported/challenged by which reviewers
- **Reference analysis**: Mischaracterizations, missing citations, contradictions from reference KB
- **Discussion impact**: What changed during discussion and what didn't
- **Strengths summary**: Grounded in claims
- **Weaknesses summary**: Grounded in claims
- **Questions for authors**: Aggregated from all reviewers

## Agent Definitions

### orchestrator.md

```yaml
---
description: Orchestrates peer review workflow (area chair)
mode: primary
tools:
  read: true
  edit: true
  bash: true
  parallel-agents: true
  parse-paper: true
  fetch-references: true
skills:
  - review-rubric
  - common-flaws
  - methodology
---
```

Full system prompt implements the 10-step workflow above. Key responsibilities:
- Constructs role × model matrix (mandatory, all 5 roles)
- Mediates discussion with targeted challenges
- Runs conflict detection checklist
- Writes final report

### decomposer.md

```yaml
---
description: Extracts atomic claims and maps them to paper sections
mode: subagent
tools:
  read: true
  edit: true
  bash: true
  parse-paper: true
skills:
  - common-flaws
  - methodology
---
```

Receives parsed paper text. Extracts every atomic claim, classifies by type (empirical/methodological/novelty/scope), maps to sections, identifies dependencies, assesses evidence strength. Writes `claims_index.json` + `summary.md`.

### reference-analyst.md

```yaml
---
description: Builds reference knowledge base from cited papers
mode: subagent
tools:
  read: true
  edit: true
  bash: true
  fetch-references: true
skills:
  - review-rubric
---
```

Receives citation list from parsed paper. Fetches all cited papers via Semantic Scholar API. Builds `reference_kb/` directory with per-paper markdown files and overall analysis. Identifies mischaracterizations, contradictions, missing references.

### reviewer.md

```yaml
---
description: Structural review agent for paper evaluation
mode: subagent
tools:
  read: true
  edit: true
  bash: true
skills:
  - review-rubric
  - common-flaws
  - methodology
---
```

Receives paper text + claims index + structural role assignment. Has access to `reference_kb/` via read/grep. Evaluates claims within role's scope. Writes per-claim assessments, dimensional free-text evaluations, strengths/weaknesses grounded in claims. Same agent definition for both initial review and discussion rounds — the prompt changes.

Note: all 3 skills are loaded for every reviewer instance. The structural role is assigned via the orchestrator's prompt, which scopes the reviewer to their dimensions. The skills provide reference material — agents use what's relevant to their role and ignore the rest.

## Parallel Agent Configs

### decomposer.yaml

```yaml
name: decomposer
description: "Extract atomic claims from paper with different models"
timeout_minutes: 30
failure_behavior: continue
default_model: "anthropic/claude-opus-4-5"
max_instances: 3
instance_models:
  - "anthropic/claude-opus-4-5"
  - "google/gemini-2.5-pro"

subagent_suffix_prompt: |
  Write summary.md with your results:

  ## Claim Count
  - Total claims extracted
  - By type: empirical, methodological, novelty, scope

  ## Claims Index
  For each claim:
  - ID, text, type, section, evidence strength
  - Dependencies on other claims

  ## Parsing Issues
  - Any sections that were unclear or hard to decompose

  Also write claims_index.json with structured claim data.

summarizer_prompt: |
  You are a consolidator agent with READ-ONLY access.

  Read ONLY these exact summary files:
  {summary_paths}

  Create a consolidated claim index:
  1. Deduplicate claims found by both models
  2. Flag claims found by only one model
  3. Note any classification disagreements
  4. Produce a merged claims_index.json

  Present facts only - do NOT resolve disagreements.

summarizer_model: "anthropic/claude-sonnet-4-5"
```

### reference-analyst.yaml

```yaml
name: reference-analyst
description: "Build reference knowledge base from cited papers"
timeout_minutes: 30
failure_behavior: continue
default_model: "anthropic/claude-opus-4-5"
max_instances: 3
instance_models:
  - "anthropic/claude-opus-4-5"
  - "google/gemini-2.5-pro"

subagent_suffix_prompt: |
  Write summary.md with your results:

  ## Reference Stats
  - Total citations in paper
  - Successfully fetched from Semantic Scholar
  - Not found

  ## Reference KB
  - Path to reference_kb/ directory
  - Number of paper files written

  ## Key Findings
  - Mischaracterizations found
  - Contradictions identified
  - Missing key references
  - Citation pattern observations

  Also write the full reference_kb/ directory structure.

summarizer_prompt: |
  You are a consolidator agent with READ-ONLY access.

  Read ONLY these exact summary files:
  {summary_paths}

  Compare the reference analyses:
  1. Did both analysts find the same mischaracterizations?
  2. Do they agree on missing references?
  3. Any contradictions one caught that the other missed?

  Merge findings into a consolidated reference_kb/ and analysis.md
  in your output directory.
  Present facts only - do NOT resolve disagreements.

  IMPORTANT: Write the merged reference_kb/ directory so the
  orchestrator can copy it to the main workspace for downstream agents.

summarizer_model: "anthropic/claude-sonnet-4-5"
```

### reviewer.yaml

```yaml
name: reviewer
description: "Run structural review roles in parallel across models"
timeout_minutes: 60
failure_behavior: continue
default_model: "anthropic/claude-opus-4-5"
max_instances: 15
instance_models:
  - "anthropic/claude-opus-4-5"
  - "google/gemini-2.5-pro"

subagent_suffix_prompt: |
  Write summary.md with your results:

  ## Role
  - Your assigned structural role
  - Dimensions in your scope

  ## Dimensional Assessments
  For each review dimension in your scope:
  - Free-text assessment
  - Key claims supporting your assessment
  - References consulted from reference_kb/

  ## Claim Evaluations
  For each claim you evaluated:
  - Claim ID, verdict (supported/unsupported/unclear)
  - Reasoning
  - Evidence from reference_kb/ if applicable

  ## Strengths
  - Grounded in specific claim IDs

  ## Weaknesses
  - Grounded in specific claim IDs

  ## Confidence
  - Where you are confident vs uncertain

summarizer_prompt: |
  You are a review consolidator with READ-ONLY access.

  Read ONLY these exact summary files:
  {summary_paths}

  Create a consolidated review comparison:
  1. Per-dimension comparison across all reviewers
  2. Claims where reviewers disagree (with claim IDs)
  3. Same-role/different-model agreements and disagreements
  4. Cross-role tensions
  5. Reference-grounded disagreements

  Present facts only - do NOT make a recommendation.

summarizer_model: "anthropic/claude-sonnet-4-5"
```

## Tools

### parse-paper.ts

TypeScript tool that calls `peer_review_lib.parse_paper`. Accepts a file path (PDF or .tex). Returns structured text with section markers, metadata (title, page count, figures detected), and extracted citation keys.

Implementation:
- **PDF path**: PyMuPDF (`fitz`) for text extraction. Section detection via font size/weight heuristics, falling back to regex patterns for numbered headings.
- **LaTeX path**: Direct parsing of `\section{}`, `\subsection{}`, `\begin{abstract}`, `\cite{}`.
- **Output format**:
  ```
  === METADATA ===
  Title: ...
  Pages: ...
  Source: PDF | LaTeX
  Citations: [key1, key2, ...]

  === ABSTRACT ===
  ...

  === 1. INTRODUCTION ===
  ...
  ```

### fetch-references.ts

TypeScript tool that calls `peer_review_lib.fetch_references`. Accepts a citation key or title string. Hits Semantic Scholar API, returns paper metadata + abstract.

Implementation:
- Uses Semantic Scholar Academic Graph API (free, no auth for basic usage)
- Search by title, return: title, authors, year, venue, abstract, citation count, Semantic Scholar ID
- Rate limiting built in (100 requests per 5 minutes for unauthenticated)
- Returns structured text for the agent to write into `reference_kb/papers/`

## Skills

### review-rubric/SKILL.md

Loaded by: orchestrator, novelty-assessor, clarity-evaluator, significance-assessor, reference-analyst

Contents:
- **The 6 review dimensions** with detailed definitions: Novelty, Rigor, Clarity, Significance, Reproducibility, Related Work. What each means, what good/bad looks like, common mistakes in evaluating each.
- **Claim grounding requirement**: every assessment must cite specific claim IDs from the claims index. No ungrounded opinions.
- **Structural role scoping**: which roles cover which dimensions (prevents drift outside scope).
- **Output format**: the exact summary.md structure each reviewer must produce.
- **Anti-patterns**: vague praise ("this paper is interesting"), scoring without evidence, conflating significance with novelty, judging a paper for not doing something it never claimed to do.

### common-flaws/SKILL.md

Loaded by: orchestrator, decomposer, claim-verifier (via reviewer.md)

A taxonomy of recurring paper weaknesses:

- **Claims flaws**: overclaiming, unstated assumptions, circular reasoning, conflating correlation with causation
- **Experimental flaws**: no ablation, unfair baselines, cherry-picked metrics, test set leakage, inadequate error bars, missing significance tests
- **Presentation flaws**: buried key results, misleading figures, inconsistent notation
- **Related work flaws**: missing obvious comparisons, strawman descriptions, citing without comparing

Each flaw: definition, detection method, example, severity (minor/major/critical).

### methodology/SKILL.md

Loaded by: orchestrator, decomposer, methodology-auditor (via reviewer.md)

Evaluation frameworks by paper type:

- **Empirical ML papers**: dataset split validity, hyperparameter selection, compute budget fairness, reproducibility checklist
- **Theoretical papers**: proof structure, assumption reasonableness, theory-practice gap, bound tightness
- **Systems papers**: benchmark validity, scalability claims, measurement methodology
- **Statistical modeling papers**: model specification, identifiability, convergence diagnostics, posterior predictive checks, sensitivity analysis

Each framework is a checklist the methodology auditor works through — baseline coverage, not exhaustive.

## Docker Environment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /workspace

RUN pip install --no-cache-dir \
    PyMuPDF==1.25.3 \
    pdfplumber==0.11.4 \
    httpx==0.28.1

COPY peer_review_lib /opt/peer_review_lib

ENV PYTHONPATH="/opt"

RUN python -c "import peer_review_lib; print('peer_review_lib import OK')"
RUN python -c "import fitz; print('PyMuPDF import OK')"

CMD ["/bin/bash"]
```

Lightweight image: Python + PDF parsing (PyMuPDF, pdfplumber) + HTTP client (httpx for Semantic Scholar API). No ML frameworks.

## Output Format

### report.md (human-readable)

Structured review report:
- Recommendation (Accept / Borderline Accept / Borderline Reject / Reject) with confidence
- Per-dimension synthesized assessments
- Consensus areas
- Disagreement areas (with attribution)
- Claim-level evidence table
- Reference analysis highlights
- Discussion impact summary
- Aggregated strengths, weaknesses, questions for authors

### report.json (machine-readable, for future validation harness)

```json
{
  "recommendation": "borderline_accept",
  "confidence": "moderate",
  "dimensions": {
    "novelty": {
      "assessments": [
        {"role": "novelty-assessor", "model": "opus", "text": "...", "round": "initial"},
        {"role": "novelty-assessor", "model": "gemini", "text": "...", "round": "initial"},
        {"role": "novelty-assessor", "model": "opus", "text": "...", "round": "discussion"}
      ]
    }
  },
  "claims": {
    "claim_001": {
      "text": "Our method achieves state-of-the-art on benchmark X",
      "type": "empirical",
      "section": "4.2",
      "evaluations": [
        {"role": "claim-verifier", "model": "opus", "verdict": "supported", "reasoning": "..."},
        {"role": "claim-verifier", "model": "gemini", "verdict": "unsupported", "reasoning": "..."}
      ]
    }
  },
  "reference_analysis": {
    "total_citations": 47,
    "fetched": 42,
    "mischaracterizations": [...],
    "missing_references": [...],
    "contradictions": [...]
  },
  "discussion_changes": [...],
  "conflict_detection": {
    "score_spread": {...},
    "directional_agreement": "...",
    "critical_flaws": [...]
  }
}
```

## Deferred to v2

| Feature | Why deferred |
|---------|-------------|
| SSR scoring | Core pipeline must work first. SSR is a calibration layer that slots in at Steps 6-8 without changing agent architecture. |
| Venue-specific configs | Tied to SSR anchor statement calibration per venue. |
| OpenReview validation harness | Separate project that consumes `report.json`. Output format designed for it now. |
| LaTeX equation rendering | v1 extracts equations as raw LaTeX strings. Rendering is a nice-to-have. |

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Discussion architecture | Orchestrator-mediated, serial fan-outs | More faithful to real discussion dynamics |
| Decomposition | Hybrid — claims extracted, mapped to sections, reviewers ground in claims | Forces evidence-based review, prevents vibes-based scoring |
| Reviewer architecture | Structural roles via single reviewer.md, role assigned in prompt | Context isolation through role scoping; all instances run in one fan-out |
| Role × model multiplication | Mandatory 5 roles × N models, prescribed in orchestrator prompt | Ensures coverage, disentangles model vs role effects |
| Role set enforcement | Hardcoded in orchestrator system prompt, not a creative decision | Prevents orchestrator from skipping roles |
| Reference KB | On-disk markdown directory, all cited papers fetched | Any agent can grep; no scoping — agents decide relevance |
| SSR | Deferred to v2 | Orthogonal to agent architecture, can be layered on later |
| Scoring (v1) | Orchestrator synthesizes from reviewer text directly | Simple, works without external API dependency |
| Paper input | PDF primary, LaTeX optional | PDF is universal; LaTeX is bonus for better structure |
| Discussion rounds | Max 2 (initial + 1 discussion) | Persistent disagreement is signal |
| Conflict detection | Adapted from MMM pattern | Proven approach: spread checks, directional agreement, critical flaw consensus |
