---
name: Review Rubric
description: Review dimensions, scoring criteria, structural role scoping, and output format for peer review agents. Defines the 6 review dimensions, maps them to structural roles, and specifies the claim-grounded assessment format.
---

# Review Rubric

This document is the primary reference for all reviewer agents. It defines what each reviewer evaluates, how assessments must be grounded in specific claims, what output format to produce, and which failure modes to avoid.

---

## 1. Review Dimensions

Each dimension has a 1–5 integer score where 1 = very weak, 3 = acceptable, 5 = exceptional. Scores must always be accompanied by at least one cited claim ID.

---

### 1.1 Novelty

**What it measures**: Whether the paper introduces genuinely new ideas, methods, datasets, frameworks, or perspectives that were not present or obvious in prior work.

**Strong indicators**
- Introduces a technique, model, or formulation not found in surveyed literature
- Addresses a gap the related work section explicitly identifies and no prior work fills
- Combines existing ideas in a non-obvious way with demonstrated synergistic effect
- Opens a new line of inquiry or defines a new problem formulation
- Produces a result that would surprise an expert reader familiar with the area

**Weak indicators**
- Incremental parameter tuning or minor architectural change with no conceptual contribution
- Re-applies a known method to a new dataset without adaptation or insight
- Claims of novelty are refuted or weakened by uncited prior work
- Contribution is entirely engineering effort with no scientific originality
- The paper itself hedges novelty claims heavily ("similar to X but…")

**Common evaluation mistakes**
1. Conflating novelty with correctness — a technically sound paper can have low novelty if it merely confirms known results.
2. Penalizing empirical or engineering papers by applying theory-novelty standards that do not match the venue.
3. Crediting novelty for claims the paper does not substantiate or demonstrate experimentally.

---

### 1.2 Rigor

**What it measures**: Mathematical, statistical, and experimental correctness. Whether claims are derived, proven, or tested appropriately and conclusions are supported by the evidence presented.

**Strong indicators**
- Proofs are complete, lemmas are stated with full hypotheses, and assumptions are explicit
- Statistical tests are appropriate for the data distribution; p-values or confidence intervals reported
- Ablations isolate individual variables and baselines are fair, contemporaneous, and reproducible
- Negative results and failure modes are reported alongside positive results
- Mathematical notation is consistent throughout and key quantities are defined before use

**Weak indicators**
- Conclusions stated as certain when error bars overlap or statistical tests are absent
- Key lemma missing a proof or proof sketch with hand-wavy steps
- Baselines are outdated, cherry-picked, or evaluated under different conditions than the proposed method
- Hyperparameter search performed only for the proposed method, not for baselines
- Equations have undefined variables or dimensional inconsistencies

**Common evaluation mistakes**
1. Accepting an informal argument as a proof — "it is clear that" and "trivially follows" are not proofs.
2. Overlooking that a p-value below 0.05 is not sufficient if multiple comparisons are made without correction.
3. Penalizing the paper for a claimed result that is correct but uses non-standard notation the reviewer finds unfamiliar.

---

### 1.3 Clarity

**What it measures**: Writing quality, logical organization, figure and table quality, and whether a competent reader in the field can follow the paper's argument without external assistance.

**Strong indicators**
- Problem statement and contributions are stated explicitly and early
- Section structure matches the logical flow of the argument (motivation → method → experiments → analysis)
- Figures are self-contained with descriptive captions; axes are labeled with units
- Technical terms are defined at first use and used consistently
- Related work situates the paper's position clearly relative to the cited work

**Weak indicators**
- Introduction does not distinguish the problem from adjacent problems
- Methods section requires the reader to consult supplementary material to understand the core algorithm
- Figures reuse acronyms that differ from main text, or axes lack labels
- Tense, voice, or terminology shifts unexpectedly between sections
- Key claims appear in abstract and conclusion but lack a corresponding methods or results section

**Common evaluation mistakes**
1. Penalizing non-native English phrasing while ignoring genuine structural clarity problems that affect understanding.
2. Rating clarity purely on prose polish rather than on whether the technical argument is followable.
3. Conflating clarity with correctness — a clearly written incorrect argument should score high on clarity and low on rigor.

---

### 1.4 Significance

**What it measures**: Impact on the field if the paper is published. Whether the contribution moves forward the state of the art, enables new research directions, or matters to a meaningful audience.

**Strong indicators**
- Addresses a problem recognized as important or open in the community (e.g., cited as future work in multiple papers)
- Results would change how practitioners choose methods or set benchmarks
- Potential to be built upon: introduces formalism, dataset, or method reusable in other contexts
- Scope is clearly defined and the contribution fully addresses that scope
- The paper would be cited by work in adjacent subfields, not only the immediate niche

**Weak indicators**
- Addresses a synthetic or artificially narrow problem constructed to make the method look good
- Gains over baselines are marginal and within measurement noise
- Results hold only under narrow assumptions unlikely to generalize
- Problem domain has a small, self-contained audience with limited cross-area impact
- Contribution described only by comparison to direct predecessors with no broader framing

**Common evaluation mistakes**
1. Conflating significance with novelty — a paper can confirm or unify existing results in a way that is highly significant but not novel.
2. Discounting significance because the reviewer's own subfield is not the target audience.
3. Inflating significance because the method achieves a state-of-the-art number without considering whether the benchmark itself is meaningful.

---

### 1.5 Reproducibility

**What it measures**: Whether an independent researcher could replicate the paper's core results using only the paper and any publicly released code or data, without contacting the authors.

**Strong indicators**
- All hyperparameters, random seeds, and hardware configurations are reported in the paper or supplementary
- Training/evaluation splits, preprocessing steps, and data cleaning decisions are documented
- Code or model weights are released with a permissive license and include a runnable example
- Results vary across seeds and variance is reported; the best single-run result is not the only figure reported
- The paper specifies which results from prior work are reproduced vs. taken from the original papers

**Weak indicators**
- Critical hyperparameters are omitted or described only vaguely ("we tuned X")
- Dataset filtering or preprocessing steps are absent or inconsistent between text and code
- Evaluation protocol differs subtly from described baselines in ways that favor the proposed method
- Code is not released, or released code does not match the paper's described method
- Compute requirements are not stated, making it impossible to judge practical reproducibility

**Common evaluation mistakes**
1. Accepting "code will be released upon acceptance" as satisfying reproducibility requirements.
2. Treating reproducibility as binary — partial information disclosure (e.g., key hyperparameters listed but no code) should receive partial credit.
3. Assuming a paper is reproducible because the method is simple; simplicity does not substitute for explicit documentation.

---

### 1.6 Related Work

**What it measures**: Whether the paper fairly characterizes, compares against, and cites the relevant prior art, including work that may weaken or contextualize its own contribution.

**Strong indicators**
- All direct predecessors are cited and quantitatively compared where applicable
- Work that partially achieves the same goal is acknowledged and the difference explained
- The related work section identifies what problem the cited works leave unsolved
- Papers from adjacent subfields that are relevant are included, not only work from the authors' own community
- Limitations of cited methods are stated accurately and not overstated to inflate the perceived gap

**Weak indicators**
- Key competing methods are absent from the literature review and from experimental baselines
- Related work is a citation list without synthesis or comparative analysis
- Characterizations of prior work are inaccurate (e.g., claiming a method does not handle X when it does)
- Self-citation rate is high relative to the coverage of the field
- Work published after the submission deadline is cited selectively to favor the authors' claims

**Common evaluation mistakes**
1. Penalizing the paper for not citing work the reviewer happens to know if that work postdates the submission.
2. Demanding citation of every tangentially related paper rather than judging whether the coverage is sufficient for the contribution being made.
3. Conflating an incomplete related work section with dishonest related work — omission is usually a clarity/rigor issue, not misconduct.

---

## 2. Structural Role Scoping

Each reviewer agent is assigned a structural role. Roles define which dimensions an agent is primarily responsible for and which dimensions it may comment on when evidence in those dimensions is directly encountered.

| Role | Primary Dimensions | May Comment On |
|---|---|---|
| claim-verifier | Rigor, Reproducibility | Any claim in any dimension |
| methodology-auditor | Rigor, Reproducibility | Significance (if method limits conclusions) |
| novelty-assessor | Novelty, Related Work | Significance (if novelty is main contribution) |
| clarity-evaluator | Clarity | Any dimension (if clarity affects understanding) |
| significance-assessor | Significance | Novelty (relationship between novelty and significance) |

**Interpretation rules**

- An agent should only produce a dimensional score for its **Primary Dimensions**.
- Commentary on "May Comment On" dimensions should be filed as an observation, not a score.
- If a reviewer encounters a clear error in an out-of-scope dimension (e.g., a clarity-evaluator finds a mathematical contradiction), it should flag it as an observation and defer scoring to the appropriate role.
- Agents must not score dimensions outside their primary or comment scope.

---

## 3. Claim Grounding Requirement

Every assessment — whether a dimensional score, a strength, or a weakness — **must cite at least one specific claim ID** from the parsed paper. Ungrounded assertions are not acceptable review content.

Claim IDs are assigned by the `parse-paper` tool and take the form `C<section>.<index>` (e.g., `C3.2`, `C5.1`).

### DO

```
Rigor: 2/5
The main theorem (C4.1) is stated without proof; the paper says "proof follows from
standard arguments" but does not provide even a proof sketch. The experimental
comparison in (C6.3) uses different evaluation metrics for the proposed method
vs. baselines, which undermines the quantitative claims.
```

```
Weakness: Reproducibility gap
Hyperparameter table (C7.1) lists learning rate and batch size but omits the
weight decay schedule, which the ablation (C7.4) identifies as the single most
impactful hyperparameter. Without it, the result in Table 3 (C6.5) cannot be
reproduced.
```

### DO NOT

```
Rigor: 2/5
The experiments are not convincing and the proofs have gaps.
```

```
Weakness: The paper is hard to reproduce.
```

These DO NOT examples are invalid because they contain no claim IDs. Any assessment filed without a claim ID will be treated as incomplete and excluded from consolidation.

---

## 4. Output Format

Every reviewer agent must produce a `summary.md` file in its assigned output directory. The file must follow this exact structure.

```markdown
# Review: <Role Name>

## Role
<role-identifier>  <!-- e.g., novelty-assessor -->

## Dimensional Assessments

<!-- One entry per PRIMARY dimension for this role. -->

### <Dimension Name>: <Score>/5

<Prose justification. Minimum 2 sentences. Must cite at least one claim ID.>

---

<!-- Repeat for each primary dimension -->

## Claim Evaluations

| Claim ID | Verdict | Notes |
|----------|---------|-------|
| C<n>.<m> | Supported / Unsupported / Partial / Unverifiable | <one-line explanation> |

<!-- Include ALL claims examined, not only those that fail. -->

## Strengths

- <Specific strength with claim ID> (C<n>.<m>)
- <Specific strength with claim ID> (C<n>.<m>)
<!-- Minimum 2 entries -->

## Weaknesses

- <Specific weakness with claim ID> (C<n>.<m>)
- <Specific weakness with claim ID> (C<n>.<m>)
<!-- Minimum 2 entries; if genuinely no weaknesses, explain why with a claim citation -->

## Observations (Out-of-Scope)

<!-- Optional section. Use only for observations in "May Comment On" dimensions or
     cross-dimension flags. Do NOT assign scores here. -->

- [<Dimension>] <Observation> (C<n>.<m>)

## Confidence

**Level**: High / Medium / Low

**Rationale**: <1–3 sentences explaining confidence level. High = reviewer has clear
expertise and claims are unambiguous. Low = outside reviewer's primary expertise or
claims are difficult to verify without running code.>
```

**Mandatory fields**: Role, all primary dimensional assessments with scores, Claim Evaluations table (at least one row), Strengths (at least two entries), Weaknesses (at least two entries), Confidence.

**Optional fields**: Observations (Out-of-Scope).

---

## 5. Anti-Patterns

Reviewers must never exhibit the following behaviors. Violations cause invalid reviews that the consolidator will flag and exclude.

### 5.1 Vague Praise
**Never** write generic positive statements without evidence.

Bad: "The paper is well-written and the experiments are comprehensive."
Good: "Section 3 (C3.1–C3.4) presents the method with consistent notation and sufficient detail to follow the algorithm."

---

### 5.2 Score Without Evidence
**Never** assign a dimensional score without at least one cited claim ID and an explanatory sentence.

Bad: `Novelty: 4/5`
Good: `Novelty: 4/5 — The proposed sparse attention kernel (C2.3) has not appeared in any cited or surveyed work, and the paper provides a formal efficiency bound (C4.1) distinguishing it from prior linear-attention variants.`

---

### 5.3 Conflating Dimensions
**Never** penalize one dimension for a failure in another.

Bad: Lowering Novelty because the writing is unclear.
Good: Score Clarity low for the writing; score Novelty based solely on whether the idea is new.

---

### 5.4 Judging Missing Work
**Never** penalize the paper for not doing additional work beyond its stated scope, unless the omission directly undermines a specific claim the paper makes.

Bad: "The authors should also evaluate on dataset X."
Good: "The paper claims generalization to out-of-distribution data (C5.2), but all experiments use in-distribution test splits (C6.1–C6.4), which does not support that claim."

---

### 5.5 Expertise Hallucination
**Never** claim to have verified something you cannot actually verify from the paper text. If a claim requires running experiments, checking a proof in full formal detail, or consulting literature not in your context, mark the verdict as `Unverifiable` in the Claim Evaluations table and explain why.

Bad: Marking a proof as `Supported` when only the statement was read.
Good: Marking `Unverifiable` with note "Proof sketch references Lemma A.3 in supplementary; supplementary not provided."

---

### 5.6 Anchoring on Other Reviewers
**Never** read or reference another reviewer agent's `summary.md` before completing your own. Reviews must be independent. The consolidator role is responsible for synthesizing across reviewers. Individual reviewers must produce their assessments solely from the parsed paper claims.
