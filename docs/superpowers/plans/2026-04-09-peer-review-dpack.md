# Peer Review Decision Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Decision Lab decision pack that simulates academic peer review using parallel structural reviewer agents, claim decomposition, and a reference knowledge base.

**Architecture:** An orchestrator agent parses a paper, fans out decomposer and reference-analyst agents, then fans out 5 structural reviewer roles (claim-verifier, methodology-auditor, novelty-assessor, clarity-evaluator, significance-assessor) × N models. Orchestrator-mediated discussion rounds resolve disagreements. Output is a structured review report with conflict detection.

**Tech Stack:** Python 3.11 (PyMuPDF for PDF parsing, httpx for Semantic Scholar API), TypeScript (OpenCode tool plugin format), Docker, dlab decision pack conventions.

**Spec:** `docs/superpowers/specs/2026-04-09-peer-review-dpack-design.md`

---

## File Structure

```
decision-packs/peer-review/
├── config.yaml                              # dpack config
├── docker/
│   ├── Dockerfile                           # Python 3.11-slim + PyMuPDF + httpx
│   └── peer_review_lib/
│       ├── __init__.py                      # Package exports
│       ├── parse_paper.py                   # PDF/LaTeX → structured text
│       └── fetch_references.py              # Semantic Scholar API client
├── opencode/
│   ├── opencode.json                        # Default agent + permissions
│   ├── agents/
│   │   ├── orchestrator.md                  # Area chair — 10-step workflow
│   │   ├── decomposer.md                    # Claim extraction subagent
│   │   ├── reference-analyst.md             # Reference KB builder subagent
│   │   └── reviewer.md                      # Structural review subagent
│   ├── tools/
│   │   ├── parse-paper.ts                   # Calls parse_paper.py
│   │   └── fetch-references.ts              # Calls fetch_references.py
│   ├── skills/
│   │   ├── review-rubric/SKILL.md           # Dimensions, criteria, output format
│   │   ├── common-flaws/SKILL.md            # Paper weakness taxonomy
│   │   └── methodology/SKILL.md             # Evaluation frameworks by paper type
│   └── parallel_agents/
│       ├── decomposer.yaml                  # 2 instances, Opus + Gemini
│       ├── reference-analyst.yaml           # 2 instances, Opus + Gemini
│       └── reviewer.yaml                    # Up to 15 instances, role × model
```

---

## Task 1: Scaffold Decision Pack + Config Files

**Files:**
- Create: `decision-packs/peer-review/config.yaml`
- Create: `decision-packs/peer-review/opencode/opencode.json`
- Create: `decision-packs/peer-review/docker/Dockerfile`
- Create: `decision-packs/peer-review/docker/peer_review_lib/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p decision-packs/peer-review/docker/peer_review_lib
mkdir -p decision-packs/peer-review/opencode/agents
mkdir -p decision-packs/peer-review/opencode/tools
mkdir -p decision-packs/peer-review/opencode/skills/review-rubric
mkdir -p decision-packs/peer-review/opencode/skills/common-flaws
mkdir -p decision-packs/peer-review/opencode/skills/methodology
mkdir -p decision-packs/peer-review/opencode/parallel_agents
```

- [ ] **Step 2: Write config.yaml**

```yaml
name: peer-review
description: Simulated academic peer review using parallel structural reviewers
docker_image_name: dlab-peer-review
default_model: anthropic/claude-opus-4-5
requires_prompt: false
```

- [ ] **Step 3: Write opencode.json**

```json
{
  "default_agent": "orchestrator",
  "permission": {
    "external_directory": { "*": "allow" }
  }
}
```

- [ ] **Step 4: Write Dockerfile**

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

- [ ] **Step 5: Write peer_review_lib/__init__.py**

```python
"""
Peer Review Library

Modules:
- parse_paper: PDF/LaTeX → structured text with section boundaries
- fetch_references: Semantic Scholar API client for building reference KB
"""

__version__ = "0.1.0"

from .parse_paper import parse_paper, parse_and_print
from .fetch_references import fetch_reference, fetch_references_batch

__all__ = [
    "__version__",
    "parse_paper",
    "parse_and_print",
    "fetch_reference",
    "fetch_references_batch",
]
```

- [ ] **Step 6: Verify structure matches dpack requirements**

```bash
# Verify dlab validates the structure (it checks for docker/, opencode/, config.yaml)
cd /home/clsandoval/cs/decision-lab
~/miniconda3/envs/dlab-testing/bin/python -c "
from dlab.config import validate_config_structure
validate_config_structure('decision-packs/peer-review')
print('Structure valid')
"
```

Expected: `Structure valid`

- [ ] **Step 7: Commit**

```bash
git add decision-packs/peer-review/
git commit -m "feat(peer-review): scaffold decision pack with config, Dockerfile, and package init"
```

---

## Task 2: Paper Parsing Python Library

**Files:**
- Create: `decision-packs/peer-review/docker/peer_review_lib/parse_paper.py`

- [ ] **Step 1: Write parse_paper.py**

This module handles both PDF and LaTeX input. Two main functions:

```python
"""
Paper parsing: PDF and LaTeX → structured text with section boundaries.

Uses PyMuPDF (fitz) for PDF extraction and regex-based parsing for LaTeX.
"""

import json
import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


def _detect_format(path: str) -> str:
    """Detect whether input is PDF or LaTeX based on extension."""
    p = Path(path)
    if p.suffix.lower() == ".tex":
        return "latex"
    if p.suffix.lower() == ".pdf":
        return "pdf"
    # Try reading first bytes to detect PDF magic
    with open(path, "rb") as f:
        header = f.read(5)
    if header == b"%PDF-":
        return "pdf"
    return "latex"


def _parse_pdf(path: str) -> dict[str, Any]:
    """
    Parse a PDF file into structured text.

    Returns dict with keys: title, pages, source, citations, sections.
    """
    doc = fitz.open(path)
    pages: list[str] = []
    for page in doc:
        pages.append(page.get_text())

    full_text = "\n".join(pages)

    # Extract title: first non-empty line from page 1, heuristic
    first_page_lines = [
        line.strip() for line in pages[0].split("\n") if line.strip()
    ]
    title = first_page_lines[0] if first_page_lines else "Unknown Title"

    # Detect sections via common heading patterns
    sections = _extract_sections_from_text(full_text)

    # Extract citations: look for common patterns
    citations = _extract_citations(full_text)

    # Detect figures
    figure_count = 0
    for page in doc:
        figure_count += len(page.get_images(full=True))

    doc.close()

    return {
        "title": title,
        "pages": len(pages),
        "source": "PDF",
        "figures_detected": figure_count,
        "citations": citations,
        "sections": sections,
        "full_text": full_text,
    }


def _parse_latex(path: str) -> dict[str, Any]:
    """
    Parse a LaTeX file into structured text.

    Returns dict with keys: title, pages, source, citations, sections.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")

    # Extract title
    title_match = re.search(r"\\title\{([^}]+)\}", text)
    title = title_match.group(1).strip() if title_match else "Unknown Title"

    # Extract abstract
    abstract_match = re.search(
        r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, re.DOTALL
    )
    abstract = abstract_match.group(1).strip() if abstract_match else ""

    # Extract sections
    sections: list[dict[str, str]] = []
    if abstract:
        sections.append({"heading": "ABSTRACT", "text": abstract})

    # Match \section{...}, \subsection{...}, etc.
    section_pattern = re.compile(
        r"\\(section|subsection|subsubsection)\{([^}]+)\}"
    )
    matches = list(section_pattern.finditer(text))

    for i, match in enumerate(matches):
        level = match.group(1)
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # Clean LaTeX commands from body (basic cleanup)
        body = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", body)
        prefix = "" if level == "section" else "  " if level == "subsection" else "    "
        sections.append({"heading": f"{prefix}{heading}", "text": body})

    # Extract citations
    cite_pattern = re.compile(r"\\cite[pt]?\{([^}]+)\}")
    citation_keys: list[str] = []
    for match in cite_pattern.finditer(text):
        keys = match.group(1).split(",")
        citation_keys.extend(k.strip() for k in keys)
    citations = sorted(set(citation_keys))

    return {
        "title": title,
        "pages": None,
        "source": "LaTeX",
        "figures_detected": text.count("\\begin{figure}"),
        "citations": citations,
        "sections": sections,
        "full_text": text,
    }


def _extract_sections_from_text(text: str) -> list[dict[str, str]]:
    """
    Extract sections from raw text using heading patterns.

    Handles patterns like:
    - "1. Introduction"
    - "1 Introduction"
    - "Abstract"
    - "INTRODUCTION"
    - "2.1 Related Work"
    """
    # Common section heading patterns in academic papers
    heading_pattern = re.compile(
        r"^(?:"
        r"(?:Abstract|ABSTRACT)|"  # Abstract
        r"(?:\d+\.?\s+[A-Z][A-Za-z\s:&-]+)|"  # "1. Introduction" or "1 Introduction"
        r"(?:\d+\.\d+\.?\s+[A-Z][A-Za-z\s:&-]+)|"  # "2.1 Related Work"
        r"(?:[A-Z][A-Z\s:&-]{3,})"  # "INTRODUCTION", "RELATED WORK"
        r")\s*$",
        re.MULTILINE,
    )

    matches = list(heading_pattern.finditer(text))
    if not matches:
        return [{"heading": "FULL TEXT", "text": text}]

    sections: list[dict[str, str]] = []
    for i, match in enumerate(matches):
        heading = match.group(0).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections.append({"heading": heading, "text": body})

    return sections


def _extract_citations(text: str) -> list[str]:
    """
    Extract citation references from text.

    Handles patterns like:
    - [1], [2, 3], [Smith et al., 2023]
    - (Smith, 2023), (Smith & Jones, 2023)
    - Smith et al. (2023)
    """
    citations: list[str] = []

    # Bracketed numeric: [1], [2, 3, 4]
    bracket_nums = re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", text)
    for match in bracket_nums:
        nums = [n.strip() for n in match.split(",")]
        citations.extend(nums)

    # Author-year in brackets: [Smith et al., 2023]
    bracket_author = re.findall(
        r"\[([A-Z][a-z]+(?:\s+et\s+al\.?)?,?\s*\d{4}[a-z]?)\]", text
    )
    citations.extend(bracket_author)

    # Parenthetical: (Smith, 2023), (Smith & Jones, 2023)
    paren_author = re.findall(
        r"\(([A-Z][a-z]+(?:\s+(?:&|and)\s+[A-Z][a-z]+)?,?\s*\d{4}[a-z]?)\)",
        text,
    )
    citations.extend(paren_author)

    return sorted(set(citations))


def parse_paper(path: str) -> dict[str, Any]:
    """
    Parse a paper (PDF or LaTeX) into structured text.

    Parameters
    ----------
    path : str
        Path to the paper file (.pdf or .tex).

    Returns
    -------
    dict[str, Any]
        Keys: title, pages, source, figures_detected, citations, sections, full_text.
        sections is a list of dicts with 'heading' and 'text' keys.
    """
    fmt = _detect_format(path)
    if fmt == "pdf":
        return _parse_pdf(path)
    return _parse_latex(path)


def parse_and_print(path: str) -> None:
    """
    Parse a paper and print structured output to stdout.

    This is the entry point called by the parse-paper.ts tool.
    """
    result = parse_paper(path)

    # Print metadata block
    print("=== METADATA ===")
    print(f"Title: {result['title']}")
    if result["pages"] is not None:
        print(f"Pages: {result['pages']}")
    print(f"Source: {result['source']}")
    print(f"Figures detected: {result['figures_detected']}")
    print(f"Citations found: {len(result['citations'])}")
    if result["citations"]:
        print(f"Citation keys: {json.dumps(result['citations'])}")
    print()

    # Print sections
    for section in result["sections"]:
        heading = section["heading"]
        text = section["text"]
        print(f"=== {heading} ===")
        print(text)
        print()
```

- [ ] **Step 2: Verify parse_paper.py imports cleanly**

```bash
cd decision-packs/peer-review/docker
python3 -c "
import sys; sys.path.insert(0, '.')
from peer_review_lib.parse_paper import parse_paper, parse_and_print
print('parse_paper imports OK')
"
```

Expected: `parse_paper imports OK` (may fail if PyMuPDF not installed locally — that's fine, it runs inside Docker)

- [ ] **Step 3: Commit**

```bash
git add decision-packs/peer-review/docker/peer_review_lib/parse_paper.py
git commit -m "feat(peer-review): add paper parsing library (PDF + LaTeX)"
```

---

## Task 3: Reference Fetching Python Library

**Files:**
- Create: `decision-packs/peer-review/docker/peer_review_lib/fetch_references.py`

- [ ] **Step 1: Write fetch_references.py**

```python
"""
Semantic Scholar API client for fetching paper metadata and abstracts.

Uses the Semantic Scholar Academic Graph API (free, no auth for basic usage).
Rate limit: 100 requests per 5 minutes for unauthenticated access.
"""

import json
import time
from typing import Any

import httpx


BASE_URL = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,authors,year,venue,abstract,citationCount,externalIds"
# Conservative rate limiting: 1 request per 3 seconds
REQUEST_INTERVAL = 3.0


def fetch_reference(query: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """
    Search Semantic Scholar for a paper by title or citation key.

    Parameters
    ----------
    query : str
        Paper title or citation key to search for.
    client : httpx.Client | None
        Optional reusable HTTP client. Creates one if not provided.

    Returns
    -------
    dict[str, Any]
        Paper metadata with keys: title, authors, year, venue, abstract,
        citation_count, semantic_scholar_id, found.
        If not found, returns dict with found=False and the query.
    """
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=15.0)

    try:
        resp = client.get(
            f"{BASE_URL}/paper/search",
            params={"query": query, "limit": 1, "fields": FIELDS},
        )

        if resp.status_code == 429:
            # Rate limited — wait and retry once
            time.sleep(10)
            resp = client.get(
                f"{BASE_URL}/paper/search",
                params={"query": query, "limit": 1, "fields": FIELDS},
            )

        if resp.status_code != 200:
            return {"found": False, "query": query, "error": f"HTTP {resp.status_code}"}

        data = resp.json()
        papers = data.get("data", [])
        if not papers:
            return {"found": False, "query": query, "error": "No results"}

        paper = papers[0]
        authors = [
            a.get("name", "Unknown") for a in (paper.get("authors") or [])
        ]

        return {
            "found": True,
            "query": query,
            "title": paper.get("title", ""),
            "authors": authors,
            "year": paper.get("year"),
            "venue": paper.get("venue", ""),
            "abstract": paper.get("abstract", ""),
            "citation_count": paper.get("citationCount", 0),
            "semantic_scholar_id": paper.get("paperId", ""),
            "external_ids": paper.get("externalIds", {}),
        }
    finally:
        if own_client:
            client.close()


def fetch_references_batch(queries: list[str]) -> list[dict[str, Any]]:
    """
    Fetch multiple papers from Semantic Scholar with rate limiting.

    Parameters
    ----------
    queries : list[str]
        List of paper titles or citation keys.

    Returns
    -------
    list[dict[str, Any]]
        List of paper metadata dicts (same format as fetch_reference).
    """
    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=15.0) as client:
        for i, query in enumerate(queries):
            if i > 0:
                time.sleep(REQUEST_INTERVAL)
            result = fetch_reference(query, client=client)
            results.append(result)
            status = "found" if result["found"] else "not found"
            print(f"[{i + 1}/{len(queries)}] {query[:60]}... → {status}")
    return results


def fetch_and_print(query: str) -> None:
    """
    Fetch a single reference and print structured output.

    This is the entry point called by the fetch-references.ts tool.
    """
    result = fetch_reference(query)
    print(json.dumps(result, indent=2, ensure_ascii=False))
```

- [ ] **Step 2: Verify fetch_references.py imports cleanly**

```bash
cd decision-packs/peer-review/docker
python3 -c "
import sys; sys.path.insert(0, '.')
from peer_review_lib.fetch_references import fetch_reference, fetch_references_batch
print('fetch_references imports OK')
"
```

Expected: `fetch_references imports OK` (may fail if httpx not installed locally — fine, runs in Docker)

- [ ] **Step 3: Commit**

```bash
git add decision-packs/peer-review/docker/peer_review_lib/fetch_references.py
git commit -m "feat(peer-review): add Semantic Scholar reference fetching library"
```

---

## Task 4: TypeScript Tools

**Files:**
- Create: `decision-packs/peer-review/opencode/tools/parse-paper.ts`
- Create: `decision-packs/peer-review/opencode/tools/fetch-references.ts`

- [ ] **Step 1: Write parse-paper.ts**

```typescript
import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Parse a PDF or LaTeX paper into structured text with section boundaries, metadata, and citation keys. Use this FIRST on any paper before analysis.",

  args: {
    path: tool.schema.string().describe("Path to paper file (.pdf or .tex)"),
  },

  async execute({ path }) {
    const result = await Bun.$`python -c "
from peer_review_lib.parse_paper import parse_and_print
parse_and_print('${path}')
"`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()

    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }

    return stdout
  },
})
```

- [ ] **Step 2: Write fetch-references.ts**

```typescript
import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Fetch paper metadata and abstract from Semantic Scholar by title. Returns JSON with title, authors, year, venue, abstract, and citation count. Rate-limited to respect API limits.",

  args: {
    query: tool.schema.string().describe("Paper title or citation key to search for"),
  },

  async execute({ query }) {
    const result = await Bun.$`python -c "
from peer_review_lib.fetch_references import fetch_and_print
fetch_and_print('${query}')
"`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()

    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }

    return stdout
  },
})
```

- [ ] **Step 3: Commit**

```bash
git add decision-packs/peer-review/opencode/tools/
git commit -m "feat(peer-review): add parse-paper and fetch-references tools"
```

---

## Task 5: Skills — Review Rubric

**Files:**
- Create: `decision-packs/peer-review/opencode/skills/review-rubric/SKILL.md`

- [ ] **Step 1: Write review-rubric/SKILL.md**

```markdown
---
name: Review Rubric
description: Review dimensions, scoring criteria, structural role scoping, and output format for peer review agents. Defines the 6 review dimensions, maps them to structural roles, and specifies the claim-grounded assessment format.
---

# Peer Review Rubric

## Review Dimensions

### 1. Novelty

**What it measures:** Does this paper present new ideas, methods, perspectives, or combinations thereof?

**Strong novelty indicators:**
- New problem formulation that reframes an existing challenge
- Novel method with theoretical or empirical justification for why it works
- Surprising empirical finding that challenges conventional wisdom
- New dataset or benchmark that enables previously impossible comparisons

**Weak novelty indicators:**
- Incremental parameter changes to existing methods
- Applying an existing method to a slightly different domain without new insight
- Combining known techniques without understanding WHY the combination helps

**Common evaluation mistakes:**
- Penalizing a paper for not being novel in a dimension it doesn't claim to be novel in
- Confusing "I haven't seen this" with "this is novel" — check the related work
- Treating engineering contributions as inherently less novel than theoretical ones

### 2. Rigor

**What it measures:** Are the mathematical, statistical, and experimental claims correct?

**Strong rigor indicators:**
- Proofs are complete, with all assumptions stated
- Experiments control for confounds with appropriate baselines
- Statistical tests are appropriate for the data and claims
- Error bars, confidence intervals, or credible intervals are reported
- Ablation studies isolate the contribution of each component

**Weak rigor indicators:**
- Claims based on single runs without variance reporting
- Inappropriate statistical tests (e.g., t-test on non-normal data)
- Missing baselines or unfair baseline comparisons
- Proofs with unstated assumptions or hand-waved steps

**Common evaluation mistakes:**
- Demanding more rigor than the venue typically requires
- Ignoring correct but unconventional statistical approaches
- Conflating "different from what I would do" with "wrong"

### 3. Clarity

**What it measures:** Can a competent reader understand what was done and why?

**Strong clarity indicators:**
- Clear problem statement in first two pages
- Notation is consistent throughout
- Figures are self-contained (readable without main text)
- Algorithm boxes or pseudocode for complex procedures
- Related work is organized thematically, not just listed

**Weak clarity indicators:**
- Key definitions buried in appendix
- Inconsistent notation (same symbol means different things)
- Figures require the caption AND main text to interpret
- Wall-of-text paragraphs without structure

**Common evaluation mistakes:**
- Penalizing dense writing that is actually precise
- Conflating "unfamiliar to me" with "unclear"
- Over-weighting formatting issues vs content clarity

### 4. Significance

**What it measures:** If the claims are true, how much does this matter?

**Strong significance indicators:**
- Addresses a problem many researchers or practitioners care about
- Results change how people should think about or approach a problem
- Enables new research directions or applications
- Practical impact is clear and immediate

**Weak significance indicators:**
- Marginal improvement on a saturated benchmark
- Problem is artificial or only relevant to the authors
- Results are theoretically interesting but practically irrelevant (or vice versa)

**Common evaluation mistakes:**
- Equating significance with performance improvement on benchmarks
- Dismissing foundational work because it doesn't have immediate applications
- Penalizing papers for not solving a bigger problem than they claim to solve

### 5. Reproducibility

**What it measures:** Could an independent researcher replicate the results?

**Strong reproducibility indicators:**
- Code is released (or promised)
- All hyperparameters, random seeds, and hardware specs reported
- Dataset is publicly available or creation process is described
- Training procedures are described in sufficient detail
- Compute budget is reported

**Weak reproducibility indicators:**
- "Details in supplementary" but supplementary is incomplete
- Key implementation details described vaguely ("we tuned learning rate")
- Proprietary data with no synthetic alternative described
- Missing information about compute requirements

**Common evaluation mistakes:**
- Requiring code release for theoretical papers
- Treating "not yet released" as "will never be released"
- Over-penalizing papers that use proprietary data when the method is clearly described

### 6. Related Work

**What it measures:** Is prior work fairly cited and compared against?

**Strong related work indicators:**
- Key prior work is cited AND discussed (not just listed)
- Differences from most similar work are clearly articulated
- Fair comparison: prior work is described accurately, not strawmanned
- Missing citations are understandable (very recent, different subfield)

**Weak related work indicators:**
- Important prior work is missing entirely
- Prior work is cited but mischaracterized
- "Our method is different" without explaining HOW
- Only self-citations or citations from one research group

**Common evaluation mistakes:**
- Demanding citation of every tangentially related paper
- Penalizing for missing a paper published after submission
- Expecting deep discussion of papers from very different subfields

## Structural Role Scoping

Each structural role covers specific dimensions. Stay within your assigned scope.

| Role | Primary Dimensions | May Comment On |
|------|-------------------|----------------|
| claim-verifier | Rigor, Reproducibility | Any claim in any dimension |
| methodology-auditor | Rigor, Reproducibility | Significance (if method limits conclusions) |
| novelty-assessor | Novelty, Related Work | Significance (if novelty is the main contribution) |
| clarity-evaluator | Clarity | Any dimension (if clarity affects understanding) |
| significance-assessor | Significance | Novelty (relationship between novelty and significance) |

## Claim Grounding Requirement

**Every assessment MUST cite specific claim IDs from the claims index.**

DO:
- "Claim 14 (convergence bound in Lemma 3) is unsupported because Assumption 2 is violated when..."
- "Claims 7-9 (experimental results on benchmark X) are well-supported by the ablation in Table 3"

DO NOT:
- "The paper has some issues with rigor" (no specific claims cited)
- "The experiments seem weak" (which experiments? which claims?)
- "This is a nice paper" (ungrounded praise is as bad as ungrounded criticism)

## Output Format

Every reviewer instance MUST write `summary.md` with this structure:

```markdown
## Role
- Assigned role: [role name]
- Dimensions in scope: [list]

## Dimensional Assessments
### [Dimension Name]
- Assessment: [free-text evaluation]
- Supporting claims: [claim IDs with brief reasoning]
- References consulted: [files from reference_kb/ if any]

## Claim Evaluations
| Claim ID | Verdict | Reasoning |
|----------|---------|-----------|
| claim_001 | supported | [brief reasoning] |
| claim_014 | unsupported | [brief reasoning] |

## Strengths
- [Strength grounded in claim IDs]

## Weaknesses
- [Weakness grounded in claim IDs]

## Confidence
- [Dimension]: [confident/moderate/uncertain] — [why]
```

## Anti-Patterns

NEVER do these:

- **Vague praise**: "This is an interesting paper" — say WHAT is interesting and cite the claim
- **Score without evidence**: Every assessment must trace to claims
- **Conflating dimensions**: Novelty and significance are different things. A paper can be novel but insignificant, or significant but not novel.
- **Judging missing work**: Don't criticize a paper for not doing something it never claimed to do. Evaluate what IS claimed.
- **Expertise hallucination**: If a claim is outside your knowledge, say "I cannot confidently evaluate Claim N because it requires expertise in [domain]." Do NOT fabricate an assessment.
- **Anchoring on other reviewers**: In discussion rounds, form your own assessment first, THEN respond to others. Don't lead with "I agree with Reviewer X."
```

- [ ] **Step 2: Commit**

```bash
git add decision-packs/peer-review/opencode/skills/review-rubric/
git commit -m "feat(peer-review): add review rubric skill with dimensions, scoping, and output format"
```

---

## Task 6: Skills — Common Flaws

**Files:**
- Create: `decision-packs/peer-review/opencode/skills/common-flaws/SKILL.md`

- [ ] **Step 1: Write common-flaws/SKILL.md**

```markdown
---
name: Common Flaws
description: Taxonomy of recurring academic paper weaknesses organized by category. Includes detection methods and severity levels for claim verification and decomposition agents.
---

# Common Paper Flaws Taxonomy

Use this as a reference when extracting claims (decomposer) or evaluating them (claim-verifier). Each flaw has a detection method — use it as a checklist, not as a script.

## Claims Flaws

### Overclaiming
- **Definition**: Stated conclusions are stronger than what the evidence supports
- **Detection**: Compare the language in the abstract/conclusion with the actual results. Look for "we show" or "we prove" when the evidence is "we observe" or "our results suggest"
- **Example**: "Our method achieves state-of-the-art" when it beats 2 of 5 baselines
- **Severity**: Major

### Unstated Assumptions
- **Definition**: The argument relies on assumptions that are not made explicit
- **Detection**: For each claim, ask "under what conditions is this true?" If the paper doesn't answer, the assumption is unstated
- **Example**: A causal claim that assumes no unmeasured confounders without stating this
- **Severity**: Major (if assumption is likely violated), Minor (if assumption is standard)

### Circular Reasoning
- **Definition**: The conclusion is assumed in the premises
- **Detection**: Trace the logical chain from assumptions to conclusions. If any step uses the conclusion as input, it's circular
- **Example**: Defining a "good" model as one that scores high on the proposed metric, then showing the proposed model scores high
- **Severity**: Critical

### Correlation as Causation
- **Definition**: Causal language used for correlational evidence
- **Detection**: Look for "causes", "leads to", "results in" when the methodology is observational
- **Example**: "Using technique X leads to better performance" from a non-controlled comparison
- **Severity**: Major

## Experimental Flaws

### Missing Ablation
- **Definition**: A multi-component system is evaluated only as a whole
- **Detection**: Count the novel components. If >1 and no ablation table, this is missing
- **Example**: A model with 3 new modules evaluated only as a complete system
- **Severity**: Major

### Unfair Baselines
- **Definition**: Baselines are not given equivalent resources or tuning
- **Detection**: Check if baselines use the same data, compute budget, and hyperparameter tuning. Check if baseline implementations are original or re-implemented (re-implementations are often weaker)
- **Example**: Comparing a heavily tuned new model against default-hyperparameter baselines
- **Severity**: Major

### Cherry-Picked Metrics
- **Definition**: Reporting only metrics where the proposed method wins
- **Detection**: Check if standard metrics for the task are all reported. Look for unusual or custom metrics
- **Example**: Reporting F1 but not precision/recall when the method trades one for the other
- **Severity**: Major

### Test Set Leakage
- **Definition**: Information from the test set influenced model development
- **Detection**: Check the evaluation protocol. Is the test set truly held out? Were hyperparameters tuned on test data?
- **Example**: "We selected the best checkpoint based on test performance"
- **Severity**: Critical

### Inadequate Error Bars
- **Definition**: Variance of results is not reported
- **Detection**: Check if results include standard deviations, confidence intervals, or are averaged over multiple runs
- **Example**: Single-run results presented as definitive
- **Severity**: Minor (if trends are large), Major (if differences are small)

### Missing Significance Tests
- **Definition**: Statistical significance of differences is not tested
- **Detection**: When two methods are compared, is the difference statistically tested?
- **Example**: "Method A achieves 85.2 vs Method B at 84.9" with no significance test
- **Severity**: Minor (if gap is large), Major (if gap is small)

## Presentation Flaws

### Buried Key Results
- **Definition**: The most important findings are not prominently presented
- **Detection**: Can you find the main result within the first 2 pages? Is it in the abstract?
- **Example**: The primary contribution is in Table 7 of the appendix
- **Severity**: Minor

### Misleading Figures
- **Definition**: Figures visually exaggerate or obscure patterns
- **Detection**: Check axis scales (truncated?), check if error bars are included, check if the visual impression matches the numbers
- **Example**: Y-axis starting at 90% to make a 91% vs 92% difference look dramatic
- **Severity**: Major

### Inconsistent Notation
- **Definition**: The same symbol or term means different things in different places
- **Detection**: Track symbol definitions across sections. Flag any symbol used before definition or redefined
- **Example**: "x" meaning input features in Section 3 and output predictions in Section 4
- **Severity**: Minor

## Related Work Flaws

### Missing Key References
- **Definition**: Important prior work is not cited
- **Detection**: Cross-reference with the reference_kb/ analysis. Check Semantic Scholar for highly-cited papers on the same topic
- **Example**: Not citing the paper that introduced the technique being extended
- **Severity**: Major

### Strawman Descriptions
- **Definition**: Prior work is described inaccurately to make the comparison favorable
- **Detection**: Compare the paper's description of prior work with the actual abstracts in reference_kb/
- **Example**: "Prior method X cannot handle Y" when X's paper explicitly addresses Y
- **Severity**: Major

### Citing Without Comparing
- **Definition**: Related work is listed but never actually compared against
- **Detection**: Check if cited methods appear in the experimental comparison
- **Example**: "Related work includes [1, 2, 3, 4, 5]" with none appearing in experiments
- **Severity**: Minor (for tangentially related work), Major (for directly competing methods)
```

- [ ] **Step 2: Commit**

```bash
git add decision-packs/peer-review/opencode/skills/common-flaws/
git commit -m "feat(peer-review): add common flaws taxonomy skill"
```

---

## Task 7: Skills — Methodology

**Files:**
- Create: `decision-packs/peer-review/opencode/skills/methodology/SKILL.md`

- [ ] **Step 1: Write methodology/SKILL.md**

```markdown
---
name: Methodology Evaluation
description: Evaluation frameworks for different paper types (empirical ML, theoretical, systems, statistical modeling). Provides checklists for methodology auditors and decomposer agents.
---

# Methodology Evaluation Frameworks

Use the appropriate framework based on the paper type. Most papers are primarily one type but may have elements of others. Evaluate using the primary type's framework, noting where other frameworks are relevant.

## Empirical ML Papers

Papers that propose or evaluate methods using experiments on datasets.

### Dataset & Evaluation Checklist

- [ ] **Data splits described**: Train/val/test split ratios and method (random, temporal, stratified)
- [ ] **No test leakage**: Test set genuinely held out during all development
- [ ] **Dataset size adequate**: Sufficient examples for the complexity of the model
- [ ] **Dataset bias acknowledged**: Known biases or limitations of the dataset discussed
- [ ] **Evaluation metrics justified**: Why these metrics? Are they standard for this task?
- [ ] **Multiple metrics reported**: Not just the one where the method wins

### Experimental Design Checklist

- [ ] **Baselines are fair**: Same data, comparable compute, tuned hyperparameters
- [ ] **Baselines are relevant**: Include current SOTA and simple baselines
- [ ] **Ablation study**: Each novel component evaluated independently
- [ ] **Variance reported**: Multiple runs with different seeds, std reported
- [ ] **Statistical significance**: Differences tested when margins are small
- [ ] **Compute budget reported**: GPU hours, hardware specs, training time

### Reproducibility Checklist

- [ ] **Hyperparameters listed**: All hyperparameters with final values
- [ ] **Architecture details complete**: Someone could reimplement from the paper
- [ ] **Training procedure described**: Optimizer, learning rate schedule, early stopping criteria
- [ ] **Code availability**: Released or promised, with timeline
- [ ] **Random seeds reported**: For reproducible runs

## Theoretical Papers

Papers that prove properties, derive bounds, or establish theoretical frameworks.

### Proof Quality Checklist

- [ ] **All assumptions stated**: Every assumption the proof relies on is explicit
- [ ] **Assumptions are reasonable**: Assumptions hold in realistic settings
- [ ] **Proof is complete**: No hand-waved steps ("it can be shown that...")
- [ ] **Bound is tight**: Is there a matching lower bound or construction showing tightness?
- [ ] **Proof technique is appropriate**: Standard techniques applied correctly
- [ ] **Edge cases handled**: Boundary conditions, degenerate cases addressed

### Theory-Practice Gap Checklist

- [ ] **Practical relevance discussed**: Does the theory apply to real systems?
- [ ] **Gap acknowledged**: If assumptions are idealized, this is stated
- [ ] **Empirical validation**: Theory predictions verified experimentally where possible
- [ ] **Constants are reasonable**: O-notation hides constants — are they practical?

## Systems Papers

Papers that build and evaluate software/hardware systems.

### Benchmark Validity Checklist

- [ ] **Workload is representative**: Benchmarks reflect real usage patterns
- [ ] **Comparison is fair**: Systems compared under equivalent conditions
- [ ] **Scalability tested**: Performance at multiple scales, not just one
- [ ] **Bottleneck analysis**: Where does the system spend time? Why?

### Measurement Methodology Checklist

- [ ] **Warm-up runs**: System reaches steady state before measurement
- [ ] **Multiple trials**: Variance across runs reported
- [ ] **Resource accounting**: CPU, memory, network, disk all measured
- [ ] **End-to-end metrics**: Not just microbenchmarks that miss system effects
- [ ] **Latency distribution**: p50, p99, not just mean (means hide tail latency)

## Statistical Modeling Papers

Papers that propose or apply statistical/probabilistic models.

### Model Specification Checklist

- [ ] **Generative process described**: Full probabilistic model written out
- [ ] **Prior choices justified**: Why these priors? Sensitivity to prior choice discussed?
- [ ] **Likelihood appropriate**: Does the likelihood match the data generating process?
- [ ] **Identifiability**: Can the parameters be estimated from the data?

### Inference Quality Checklist

- [ ] **Convergence diagnostics**: R-hat, ESS, trace plots reported
- [ ] **Posterior predictive checks**: Model predictions compared to observed data
- [ ] **Sensitivity analysis**: Results robust to reasonable prior changes?
- [ ] **Multiple chains**: Not just one MCMC chain

### Causal Claims Checklist (if applicable)

- [ ] **Causal assumptions explicit**: DAG or structural equations provided
- [ ] **No unmeasured confounders justified**: Why is this reasonable?
- [ ] **Intervention vs observation**: Clear about what is manipulated vs observed
- [ ] **Identification strategy**: How are causal effects identified from observational data?
```

- [ ] **Step 2: Commit**

```bash
git add decision-packs/peer-review/opencode/skills/methodology/
git commit -m "feat(peer-review): add methodology evaluation frameworks skill"
```

---

## Task 8: Parallel Agent Configs

**Files:**
- Create: `decision-packs/peer-review/opencode/parallel_agents/decomposer.yaml`
- Create: `decision-packs/peer-review/opencode/parallel_agents/reference-analyst.yaml`
- Create: `decision-packs/peer-review/opencode/parallel_agents/reviewer.yaml`

- [ ] **Step 1: Write decomposer.yaml**

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
  ---

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

  ---

  Also write claims_index.json with the following structure:

  ```json
  {
    "claims": [
      {
        "id": "claim_001",
        "text": "The exact claim text from the paper",
        "type": "empirical",
        "section": "4.2 Experiments",
        "evidence_strength": "supported",
        "dependencies": ["claim_003"],
        "reasoning": "Brief note on why this classification"
      }
    ]
  }
  ```

summarizer_prompt: |
  You are a consolidator agent with READ-ONLY access.

  Read ONLY these exact summary files:
  {summary_paths}

  Also read the claims_index.json files from each instance directory.

  Create a consolidated claim index:
  1. Deduplicate claims found by both models (match by content, not ID)
  2. Flag claims found by only one model (mark provenance)
  3. Note any classification disagreements (type, evidence_strength)
  4. Produce a merged claims_index.json with deduplicated, renumbered claim IDs

  Write both summary.md (human-readable comparison) and claims_index.json (canonical merged index).

  Present facts only - do NOT resolve disagreements.

summarizer_model: "anthropic/claude-sonnet-4-5"
```

- [ ] **Step 2: Write reference-analyst.yaml**

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
  ---

  Write summary.md with your results:

  ## Reference Stats
  - Total citations in paper
  - Successfully fetched from Semantic Scholar
  - Not found

  ## Reference KB
  - Path to reference_kb/ directory
  - Number of paper files written

  ## Key Findings
  - Mischaracterizations found (list each with evidence)
  - Contradictions identified (list each with evidence)
  - Missing key references (list each with reasoning)
  - Citation pattern observations

  ---

  Also write the full reference_kb/ directory:

  reference_kb/
  ├── index.md              (citation list with found/not-found status)
  ├── papers/
  │   ├── ref_001.md        (one file per cited paper)
  │   └── ...
  └── analysis.md           (mischaracterizations, contradictions, missing refs)

  Each paper file in papers/ should contain:
  - Title, authors, venue, year, citation count
  - Abstract
  - How the reviewed paper cites it (quote the relevant text)
  - Characterization accuracy: accurate / inaccurate / partial (with reasoning)

summarizer_prompt: |
  You are a consolidator agent with READ-ONLY access.

  Read ONLY these exact summary files:
  {summary_paths}

  Also read the reference_kb/ directories from each instance.

  Compare the reference analyses:
  1. Did both analysts find the same mischaracterizations?
  2. Do they agree on missing references?
  3. Any contradictions one caught that the other missed?

  Merge into a consolidated reference_kb/ directory and analysis.md
  in your output directory. The orchestrator will copy this to the
  main workspace for downstream agents.

  Present facts only - do NOT resolve disagreements.

summarizer_model: "anthropic/claude-sonnet-4-5"
```

- [ ] **Step 3: Write reviewer.yaml**

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
  ---

  Write summary.md with your results:

  ## Role
  - Your assigned structural role
  - Dimensions in your scope

  ## Dimensional Assessments
  For each review dimension in your scope:
  - Free-text assessment
  - Key claims supporting your assessment (cite claim IDs)
  - References consulted from reference_kb/ (if any)

  ## Claim Evaluations
  For each claim you evaluated:
  - Claim ID
  - Verdict: supported / unsupported / unclear
  - Reasoning (cite evidence)
  - Reference from reference_kb/ if applicable

  ## Strengths
  - Grounded in specific claim IDs

  ## Weaknesses
  - Grounded in specific claim IDs

  ## Confidence
  - Per-dimension: confident / moderate / uncertain — with reasoning

summarizer_prompt: |
  You are a review consolidator with READ-ONLY access.

  Read ONLY these exact summary files:
  {summary_paths}

  Create a consolidated review comparison:
  1. Per-dimension comparison across all reviewers
  2. Claims where reviewers disagree (list claim IDs and verdicts)
  3. Same-role/different-model agreements and disagreements
  4. Cross-role tensions (e.g., claim-verifier vs methodology-auditor)
  5. Reference-grounded disagreements

  Present facts only - do NOT make a recommendation.

summarizer_model: "anthropic/claude-sonnet-4-5"
```

- [ ] **Step 4: Commit**

```bash
git add decision-packs/peer-review/opencode/parallel_agents/
git commit -m "feat(peer-review): add parallel agent configs for decomposer, reference-analyst, reviewer"
```

---

## Task 9: Subagent Definitions — Decomposer and Reference Analyst

**Files:**
- Create: `decision-packs/peer-review/opencode/agents/decomposer.md`
- Create: `decision-packs/peer-review/opencode/agents/reference-analyst.md`

- [ ] **Step 1: Write decomposer.md**

````markdown
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

# Claim Decomposition Agent

You are a claim extraction specialist. Your job is to read a parsed academic paper and extract every atomic claim, classify it, map it to the paper's structure, and assess its evidence strength.

## Your Task

1. Read the paper text provided in your prompt
2. Extract every atomic claim (see Claim Types below)
3. Classify each claim by type
4. Map each claim to the paper section it appears in
5. Identify dependencies between claims
6. Assess evidence strength for each claim
7. Write `claims_index.json` and `summary.md`

## What Is an Atomic Claim?

An atomic claim is a single, verifiable assertion. Decompose compound statements into individual claims.

**Compound (decompose this):**
> "Our method achieves state-of-the-art accuracy on CIFAR-10 and is 3x faster than the baseline."

**Atomic (into these):**
> Claim A: "Our method achieves state-of-the-art accuracy on CIFAR-10"
> Claim B: "Our method is 3x faster than the baseline"

## Claim Types

- **empirical**: Assertions about experimental results, measurements, or observations. "We achieve 95% accuracy." "Training takes 2 hours on a single GPU."
- **methodological**: Assertions about how something works or why it works. "The attention mechanism allows the model to focus on relevant features." "Our loss function is convex."
- **novelty**: Assertions about what is new. "To our knowledge, this is the first method to..." "Unlike prior work, we..."
- **scope**: Assertions about limitations or applicability. "This approach is limited to supervised settings." "Our results hold for datasets with >1000 samples."

## Evidence Strength

- **proven**: Formal proof provided (theorems, lemmas with complete proofs)
- **supported**: Empirical evidence or strong argument provided (experiments, ablations, citations to established results)
- **asserted**: Stated without direct evidence in this paper (may be common knowledge or may be unsupported)

## Dependency Tracking

If Claim B relies on Claim A being true, record this dependency. Common patterns:
- "Given our convergence result (Claim A), the method produces valid estimates (Claim B)"
- Experimental claims that depend on methodological claims being correct
- Novelty claims that depend on the related work characterization being accurate

## CRITICAL: NEVER FABRICATE

If a section is unclear or you cannot confidently extract a claim, mark it as unclear in your output. Do NOT invent claims that aren't in the paper.

## Working Directory Rules

- Read data from `data/` (relative path)
- Write ALL output to `.` (current directory)
- NEVER use `../` in any path
- NEVER write to absolute paths
````

- [ ] **Step 2: Write reference-analyst.md**

````markdown
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

# Reference Analyst Agent

You are a reference analysis specialist. Your job is to fetch metadata for every paper cited in the reviewed paper, build a reference knowledge base on disk, and identify mischaracterizations, contradictions, and missing references.

## Your Task

1. Read the citation list provided in your prompt
2. For each citation, use the `fetch-references` tool to get metadata from Semantic Scholar
3. Write a markdown file for each cited paper in `reference_kb/papers/`
4. Write `reference_kb/index.md` with the full citation list and fetch status
5. Analyze the references for issues
6. Write `reference_kb/analysis.md` with findings
7. Write `summary.md` with your results

## Fetching References

Use the `fetch-references` tool for each citation. The tool accepts a title or citation key and returns JSON with:
- title, authors, year, venue, abstract, citation_count, semantic_scholar_id

If a citation is a numeric reference (e.g., "[23]"), you need to find the corresponding title from the paper's bibliography section. If you cannot determine the title, mark it as "unable to resolve" in the index.

**Rate limiting is built into the tool.** You do not need to add delays between calls.

## Reference KB Structure

### reference_kb/index.md

```markdown
# Reference Index

| # | Citation Key | Title | Status |
|---|-------------|-------|--------|
| 1 | Smith2023 | Attention Is All You Need | found |
| 2 | [14] | Unable to resolve from bibliography | not_resolved |
| 3 | Chen2024 | Bayesian Deep Learning | found |
| 4 | Jones2022 | Unknown Title | not_found |
```

### reference_kb/papers/ref_001.md (one per found paper)

```markdown
# Smith et al. 2023 — Attention Is All You Need

- **Authors**: Smith, Jones, Lee
- **Venue**: NeurIPS 2023
- **Year**: 2023
- **Citation count**: 142
- **Semantic Scholar ID**: abc123

## Abstract
[Full abstract from Semantic Scholar]

## How the Reviewed Paper Cites This
[Quote the text from the reviewed paper that references this work, with section]

## Characterization Accuracy
[accurate / inaccurate / partial]
[Reasoning: compare what the reviewed paper says about this work vs what the abstract actually says]
```

### reference_kb/analysis.md

```markdown
# Reference Analysis

## Mischaracterizations
[Papers where the reviewed paper's description doesn't match the actual abstract]

## Contradictions
[Cases where cited papers' findings contradict the reviewed paper's claims]

## Potentially Missing References
[Important related papers found via Semantic Scholar that should have been cited]

## Citation Patterns
- Self-citation rate
- Recency distribution
- Venue distribution
- Any concerning patterns
```

## CRITICAL: Work Within Your Directory

- Write ALL output to `.` (current directory)
- NEVER use `../` in any path
- NEVER write to absolute paths

## CRITICAL: NEVER FABRICATE

If you cannot fetch a paper's details, say so. Do NOT make up abstracts or metadata. Mark as "not_found" and move on.
````

- [ ] **Step 3: Commit**

```bash
git add decision-packs/peer-review/opencode/agents/decomposer.md
git add decision-packs/peer-review/opencode/agents/reference-analyst.md
git commit -m "feat(peer-review): add decomposer and reference-analyst agent definitions"
```

---

## Task 10: Reviewer Agent Definition

**Files:**
- Create: `decision-packs/peer-review/opencode/agents/reviewer.md`

- [ ] **Step 1: Write reviewer.md**

````markdown
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

# Structural Reviewer Agent

You are a structural reviewer for academic papers. You evaluate a paper through a specific analytical lens defined by your assigned structural role. Your assessments must be grounded in the claims index — cite specific claim IDs for every point you make.

## Your Assignment

Your prompt specifies:
1. **Your structural role** (claim-verifier, methodology-auditor, novelty-assessor, clarity-evaluator, or significance-assessor)
2. **The paper text**
3. **The claims index** (with claim IDs)
4. **Access to reference_kb/** (grep or read as needed)

## Structural Roles

### claim-verifier
**Scope**: Rigor, Reproducibility
**Task**: For each claim in the claims index that falls within your scope, evaluate whether the evidence presented actually supports the claim. Check:
- Do experimental results support empirical claims?
- Are methodological claims backed by formal arguments or empirical evidence?
- Are scope claims (limitations) honest and complete?
Consult `reference_kb/` to verify claims about prior work.

### methodology-auditor
**Scope**: Rigor, Reproducibility
**Task**: Evaluate the paper's methodology using the appropriate framework from the methodology skill. Check:
- Is the experimental/theoretical methodology sound?
- Are there flaws in the evaluation protocol?
- Could the results be reproduced from the paper alone?
Use the methodology checklists as a starting point, but reason beyond them.

### novelty-assessor
**Scope**: Novelty, Related Work
**Task**: Evaluate what is genuinely new in this paper. Check:
- Are novelty claims actually novel? (consult reference_kb/ to verify)
- Is related work fairly represented? (compare paper's descriptions with reference_kb/)
- What is the actual delta over prior work?
Use `reference_kb/analysis.md` for mischaracterization and missing reference findings.

### clarity-evaluator
**Scope**: Clarity
**Task**: Evaluate whether the paper communicates its ideas effectively. Check:
- Can claims be understood without ambiguity?
- Is notation consistent?
- Are figures informative and self-contained?
- Is the paper organized logically?
Note: you may comment on other dimensions if clarity issues affect understanding of claims.

### significance-assessor
**Scope**: Significance
**Task**: Evaluate the potential impact of this work assuming the claims are true. Check:
- Does this address an important problem?
- Would the results change how people think or work?
- Is the contribution sufficient for the venue?
- What is the relationship between the novelty and its significance?

## How to Do Your Review

1. **Read your assigned role description above**
2. **Read the paper text** — understand what is being claimed
3. **Read the claims index** — this is your evidence map
4. **Grep reference_kb/ as needed** — verify claims about prior work
5. **Evaluate each relevant claim** within your scope
6. **Write dimensional assessments** for your assigned dimensions
7. **List strengths and weaknesses** — always citing claim IDs
8. **Note your confidence level** per dimension

## Discussion Rounds

If this is a discussion round (your prompt will say so), you will also receive:
- Your original review
- All other reviewers' reviews
- Targeted challenges from the orchestrator

In discussion rounds:
1. Read the challenges directed at you
2. Respond to each specific point
3. Update your assessments if the challenge changes your evaluation
4. Explicitly state what changed and why (or why you maintain your position)
5. Do NOT simply agree with other reviewers — reason independently

## CRITICAL: NEVER FABRICATE

- Do NOT claim expertise you don't have. If a claim requires domain knowledge you lack, say so.
- Do NOT invent references or results. If reference_kb/ doesn't have a paper, say the reference was not available.
- Do NOT provide assessments without evidence. Every point must cite a claim ID.

## Working Directory Rules

- Read data from `data/` (relative path)
- Read reference KB from `reference_kb/` (relative path, if it exists in your workspace)
- Write ALL output to `.` (current directory)
- NEVER use `../` in any path
- NEVER write to absolute paths
````

- [ ] **Step 2: Commit**

```bash
git add decision-packs/peer-review/opencode/agents/reviewer.md
git commit -m "feat(peer-review): add reviewer agent definition with structural roles"
```

---

## Task 11: Orchestrator Agent Definition

**Files:**
- Create: `decision-packs/peer-review/opencode/agents/orchestrator.md`

This is the largest file — it implements the full 10-step workflow.

- [ ] **Step 1: Write orchestrator.md**

````markdown
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

# Peer Review Orchestrator — Area Chair

You orchestrate a full academic peer review workflow. You parse the paper, decompose it into claims, build a reference knowledge base, fan out structural reviewers, mediate discussion, and produce a final review report.

## Your Workflow

Follow these steps in order.

### Step 1: Paper Parsing

**Use the `parse-paper` tool on each file in `data/`:**

```
parse-paper data/paper.pdf
```

This returns structured text with section boundaries, metadata, and citation keys.

**Write `paper_structure.md`** with:
- Paper title and abstract
- Section hierarchy (list all sections found)
- Source format (PDF or LaTeX)
- Any parsing issues (garbled text, missing sections)
- Initial domain identification (what fields does this paper touch?)
- Full citation list extracted

### Step 2: Claim Decomposition (Fan-out 1)

**Use the `parallel-agents` tool to spawn 2 decomposer agents.**

Pass the full parsed paper text to both. They will extract atomic claims independently.

```json
{
  "agent": "decomposer",
  "prompts": [
    "Parse and decompose the following paper into atomic claims.\n\n[PAPER TEXT FROM STEP 1]\n\nThe paper's section structure is:\n[SECTION LIST FROM STEP 1]",
    "Parse and decompose the following paper into atomic claims.\n\n[PAPER TEXT FROM STEP 1]\n\nThe paper's section structure is:\n[SECTION LIST FROM STEP 1]"
  ]
}
```

The consolidator will merge their claim sets automatically.

### Step 3: Reference Knowledge Base (Fan-out 2)

**Use the `parallel-agents` tool to spawn 2 reference-analyst agents.**

Pass the citation list from Step 1 and the paper text (so they can find how each reference is cited).

```json
{
  "agent": "reference-analyst",
  "prompts": [
    "Build a reference knowledge base for this paper.\n\nCitation list:\n[CITATIONS FROM STEP 1]\n\nPaper text (for finding how citations are used):\n[PAPER TEXT]",
    "Build a reference knowledge base for this paper.\n\nCitation list:\n[CITATIONS FROM STEP 1]\n\nPaper text (for finding how citations are used):\n[PAPER TEXT]"
  ]
}
```

The consolidator will merge the reference KBs.

### Step 4: Review Consolidated Outputs

**Copy the consolidated `reference_kb/` to the main workspace:**

```bash
cp -r parallel/run-*/reference_kb /workspace/reference_kb
```

Find the correct path from the parallel-agents output. The consolidated reference_kb/ should be in the run directory.

**Read and review:**
- The consolidated `claims_index.json` from the decomposer run
- The `reference_kb/analysis.md` from the reference-analyst run

**Check:**
- Are the two decomposers broadly consistent? If one found 40 claims and the other found 12, investigate.
- Are there claims only one model found? These may be subtle — highlight them for reviewers.
- Does the claim dependency graph make sense?
- Did reference-analysts flag any mischaracterizations or missing citations?

**Copy the consolidated claims_index.json to the main workspace:**

```bash
cp parallel/run-*/claims_index.json /workspace/claims_index.json
```

**Write `pre_review_assessment.md`** documenting your review of the consolidated outputs.

### Step 5: Construct Review Matrix (MANDATORY — DO NOT SKIP ROLES)

You MUST spawn ALL 5 structural roles. This is NOT a creative decision.

| Role | Focus | Dimensions |
|------|-------|------------|
| claim-verifier | Each claim against evidence | Rigor, Reproducibility |
| methodology-auditor | Statistical/experimental methods | Rigor, Reproducibility |
| novelty-assessor | Claims vs related work | Novelty, Related Work |
| clarity-evaluator | Writing, structure, figures | Clarity |
| significance-assessor | Impact, scope, implications | Significance |

**For EACH role, create one prompt per model in instance_models (currently: Opus, Gemini).**

5 roles × 2 models = 10 instances minimum.

**Construct the prompts and models arrays explicitly:**

Each prompt must include:
1. The structural role assignment (copy the role description from above)
2. The full paper text
3. The claims index (read from `/workspace/claims_index.json`)
4. A note that `reference_kb/` is available for reading/grepping
5. Optional domain-specific framing if the paper warrants it

```json
{
  "agent": "reviewer",
  "prompts": [
    "ROLE: claim-verifier\nSCOPE: Rigor, Reproducibility\n\n[FULL ROLE DESCRIPTION]\n\nPAPER:\n[TEXT]\n\nCLAIMS INDEX:\n[JSON]\n\nThe reference_kb/ directory is available in your workspace for verification.",
    "ROLE: claim-verifier\nSCOPE: Rigor, Reproducibility\n\n[FULL ROLE DESCRIPTION]\n\nPAPER:\n[TEXT]\n\nCLAIMS INDEX:\n[JSON]\n\nThe reference_kb/ directory is available in your workspace for verification.",
    "ROLE: methodology-auditor\nSCOPE: Rigor, Reproducibility\n\n[FULL ROLE DESCRIPTION]\n\nPAPER:\n[TEXT]\n\nCLAIMS INDEX:\n[JSON]\n\nThe reference_kb/ directory is available in your workspace for verification.",
    "ROLE: methodology-auditor\n...",
    "ROLE: novelty-assessor\n...",
    "ROLE: novelty-assessor\n...",
    "ROLE: clarity-evaluator\n...",
    "ROLE: clarity-evaluator\n...",
    "ROLE: significance-assessor\n...",
    "ROLE: significance-assessor\n..."
  ],
  "models": [
    "anthropic/claude-opus-4-5",
    "google/gemini-2.5-pro",
    "anthropic/claude-opus-4-5",
    "google/gemini-2.5-pro",
    "anthropic/claude-opus-4-5",
    "google/gemini-2.5-pro",
    "anthropic/claude-opus-4-5",
    "google/gemini-2.5-pro",
    "anthropic/claude-opus-4-5",
    "google/gemini-2.5-pro"
  ]
}
```

**Write `review_matrix.md`** documenting which role/model each instance got.

### Step 6: Structural Review (Fan-out 3)

The parallel-agents call from Step 5 runs all 10 instances. Wait for completion.

Read the consolidated review comparison. Also read individual instance `summary.md` files for detail.

### Step 7: Disagreement Analysis

**Identify disagreements across reviews:**

1. **Same-role/different-model**: Two claim-verifiers (Opus vs Gemini) disagree on a claim → likely model artifact
2. **Cross-role tensions**: Claim-verifier says unsupported, methodology-auditor says method is sound → needs discussion
3. **High-spread dimensions**: Reviews diverge significantly on a dimension
4. **Split claim verdicts**: A claim is "supported" by some reviewers and "unsupported" by others

**Rank disagreements by severity.** Focus discussion on the most consequential ones.

**Write `disagreement_analysis.md`** documenting all disagreements found.

### Step 8: Discussion Rounds (Fan-out 4)

**Construct targeted discussion prompts.**

For each reviewer, include:
- Their original review
- All other reviews (so they have full context)
- 1-3 specific challenges based on the disagreements found in Step 7

Example challenge:
> "Claim verifier (Opus) found Claim 14 unsupported — the convergence bound in Lemma 3 doesn't hold under Assumption 2. Methodology auditor (Gemini) assessed the overall method as sound without flagging this. Respond to the specific Lemma 3 concern. Update your assessments for any dimension where you've changed your mind, and explicitly state what changed and why."

Spawn the reviewer agent again with discussion prompts:

```json
{
  "agent": "reviewer",
  "prompts": [
    "DISCUSSION ROUND\n\nROLE: claim-verifier\n\nYour original review:\n[THEIR REVIEW]\n\nAll reviews:\n[ALL REVIEWS]\n\nChallenges for you:\n[TARGETED CHALLENGES]\n\nRespond to each challenge. Update your assessments if warranted. Explicitly state what changed and why.",
    ...
  ],
  "models": ["anthropic/claude-opus-4-5", "google/gemini-2.5-pro", ...]
}
```

**After discussion, compare pre/post assessments.** Note what changed and what didn't.

**MAXIMUM 2 ROUNDS** (initial review + 1 discussion). Persistent disagreement is signal, not noise. Do NOT keep iterating.

### Step 9: Conflict Detection

**Run the conflict detection checklist:**

**Check 1: Dimensional Agreement**
For each dimension, assess the spread across all reviewer assessments:

| Spread | Assessment |
|--------|------------|
| Reviewers broadly agree | Consensus — confident assessment |
| Minor differences in emphasis | Moderate agreement — note caveats |
| Fundamental disagreement persists after discussion | Strong disagreement — flag as unresolved |

**Check 2: Accept/Reject Direction**

| Pattern | Assessment |
|---------|------------|
| All roles lean accept or reject | Consensus |
| Clear majority (4-1, 5-1 across roles) | Lean with majority, note dissent |
| Even split | Genuinely borderline — report as such |

**Check 3: Critical Flaw Agreement**

| Pattern | Assessment |
|---------|------------|
| Multiple roles confirm a critical flaw | High confidence — critical issue |
| Only one role flags, others don't address | Uncertain — flag for author response |
| One role flags, another explicitly disagrees | Genuine disagreement — report both sides |

### Step 10: Final Report

**Write `report.md`** (human-readable):

```markdown
# Peer Review Report

## Recommendation
[Accept / Borderline Accept / Borderline Reject / Reject]
Confidence: [High / Moderate / Low]

## Executive Summary
[2-3 paragraph summary of the review findings]

## Per-Dimension Assessments

### Novelty
[Synthesized from novelty-assessor reviews]

### Rigor
[Synthesized from claim-verifier and methodology-auditor reviews]

### Clarity
[Synthesized from clarity-evaluator reviews]

### Significance
[Synthesized from significance-assessor reviews]

### Reproducibility
[Synthesized from claim-verifier and methodology-auditor reviews]

### Related Work
[Synthesized from novelty-assessor reviews + reference KB analysis]

## Consensus Areas
[What all reviewers agreed on]

## Disagreement Areas
[What remained unresolved after discussion, with attribution]

## Claim-Level Evidence
| Claim ID | Text | Verifier | Methodology | Novelty |
|----------|------|----------|-------------|---------|
[Table of key claims and their verdicts across roles]

## Reference Analysis Highlights
[Key findings from reference KB: mischaracterizations, missing refs]

## Discussion Impact
[What changed during discussion and what didn't]

## Strengths
[Aggregated, grounded in claims]

## Weaknesses
[Aggregated, grounded in claims]

## Questions for Authors
[Aggregated from all reviewers]
```

**Write `report.json`** (machine-readable for future validation harness):

Write a Python script to generate structured JSON:

```python
#!/usr/bin/env python3
"""Generate report.json from review artifacts."""
import json

report = {
    "recommendation": "<accept/borderline_accept/borderline_reject/reject>",
    "confidence": "<high/moderate/low>",
    "dimensions": {},
    "claims": {},
    "reference_analysis": {},
    "discussion_changes": [],
    "conflict_detection": {}
}

# Populate from review artifacts...
# Read individual review summaries, claims_index.json, reference_kb/analysis.md

with open("report.json", "w") as f:
    json.dump(report, f, indent=2)
```

Populate the JSON structure from the review artifacts — individual summary.md files, claims_index.json, reference_kb/analysis.md, and your conflict detection results.
````

- [ ] **Step 2: Verify all agent files have valid frontmatter**

```bash
cd decision-packs/peer-review
for f in opencode/agents/*.md; do
  echo "=== $f ==="
  head -20 "$f"
  echo
done
```

Expected: each file starts with `---` frontmatter containing description, mode, tools, and skills.

- [ ] **Step 3: Commit**

```bash
git add decision-packs/peer-review/opencode/agents/orchestrator.md
git commit -m "feat(peer-review): add orchestrator agent with full 10-step workflow"
```

---

## Task 12: Final Validation

- [ ] **Step 1: Verify complete file structure**

```bash
cd /home/clsandoval/cs/decision-lab
find decision-packs/peer-review -type f | sort
```

Expected output:
```
decision-packs/peer-review/config.yaml
decision-packs/peer-review/docker/Dockerfile
decision-packs/peer-review/docker/peer_review_lib/__init__.py
decision-packs/peer-review/docker/peer_review_lib/fetch_references.py
decision-packs/peer-review/docker/peer_review_lib/parse_paper.py
decision-packs/peer-review/opencode/agents/decomposer.md
decision-packs/peer-review/opencode/agents/orchestrator.md
decision-packs/peer-review/opencode/agents/reference-analyst.md
decision-packs/peer-review/opencode/agents/reviewer.md
decision-packs/peer-review/opencode/opencode.json
decision-packs/peer-review/opencode/parallel_agents/decomposer.yaml
decision-packs/peer-review/opencode/parallel_agents/reference-analyst.yaml
decision-packs/peer-review/opencode/parallel_agents/reviewer.yaml
decision-packs/peer-review/opencode/skills/common-flaws/SKILL.md
decision-packs/peer-review/opencode/skills/methodology/SKILL.md
decision-packs/peer-review/opencode/skills/review-rubric/SKILL.md
decision-packs/peer-review/opencode/tools/fetch-references.ts
decision-packs/peer-review/opencode/tools/parse-paper.ts
```

- [ ] **Step 2: Validate dpack structure via dlab**

```bash
~/miniconda3/envs/dlab-testing/bin/python -c "
from dlab.config import validate_config_structure, load_dpack_config
validate_config_structure('decision-packs/peer-review')
config = load_dpack_config('decision-packs/peer-review')
print(f'Name: {config[\"name\"]}')
print(f'Model: {config[\"default_model\"]}')
print(f'Docker: {config[\"docker_image_name\"]}')
print(f'Requires prompt: {config.get(\"requires_prompt\", True)}')
print('Validation passed')
"
```

Expected: Validation passed with correct config values.

- [ ] **Step 3: Verify all parallel agent configs reference existing agent files**

```bash
cd decision-packs/peer-review
for yaml_file in opencode/parallel_agents/*.yaml; do
  agent_name=$(grep "^name:" "$yaml_file" | awk '{print $2}')
  agent_file="opencode/agents/${agent_name}.md"
  if [ -f "$agent_file" ]; then
    echo "OK: $yaml_file → $agent_file"
  else
    echo "MISSING: $yaml_file references $agent_file which does not exist"
  fi
done
```

Expected: all OK.

- [ ] **Step 4: Verify agent frontmatter tool references match available tools**

```bash
cd decision-packs/peer-review
echo "Available tools:"
ls opencode/tools/
echo
for agent in opencode/agents/*.md; do
  echo "=== $(basename $agent) ==="
  # Extract tools from frontmatter
  sed -n '/^tools:/,/^[a-z]/p' "$agent" | head -10
  echo
done
```

Expected: all tool references (parse-paper, fetch-references) correspond to files in opencode/tools/.

- [ ] **Step 5: Commit any fixes, then final commit**

```bash
git add -A decision-packs/peer-review/
git status
git commit -m "feat(peer-review): complete peer review decision pack v1"
```
