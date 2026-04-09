---
name: Common Flaws
description: Taxonomy of recurring academic paper weaknesses organized by category. Includes detection methods and severity levels for claim verification and decomposition agents.
---

# Common Flaws Taxonomy

This document is the reference taxonomy for flaw detection across all reviewer agents. It defines recurring weakness patterns in academic papers, organized into four categories: Claims, Experimental, Presentation, and Related Work. Each flaw entry includes a definition, detection method, concrete example, and severity level.

Severity levels:
- **Critical** — invalidates or severely undermines the paper's central contribution
- **Major** — weakens primary claims or evaluation in a substantive way; warrants rejection or major revision
- **Minor** — reduces clarity or rigor without undermining the core contribution; warrants revision

---

## 1. Claims Flaws

Flaws in how the paper states, scopes, or logically supports its primary claims.

---

### 1.1 Overclaiming

**Definition**: The paper's conclusions are stated more strongly than the evidence supports. Hedged or qualified results in the experiments section are restated as certain or universal in the abstract or conclusion.

**Detection**: Compare the language of the abstract and conclusion against the actual results tables and figures. Look for verbs like "proves," "demonstrates," "establishes," or "shows that X always/universally" when the experiments are narrow in scope, evaluated on a single dataset, or show mixed results.

**Example**: An abstract states "our method eliminates hallucination in language models" but the results section reports a 12% reduction on one benchmark with no evaluation across other settings or model families.

**Severity**: Major

---

### 1.2 Unstated Assumptions

**Definition**: The argument relies on conditions or preconditions that are not made explicit. The claim holds only under constraints the paper never acknowledges, meaning readers cannot assess the actual scope of validity.

**Detection**: For each central claim, ask "under what conditions is this true?" If the paper does not state those conditions but the conclusion depends on them, the assumption is unstated. Pay attention to claims about generalization, efficiency, or correctness that implicitly require specific data distributions, compute budgets, or problem formulations.

**Example**: A method is claimed to be "computationally efficient" without specifying that this holds only for sequences under 512 tokens, whereas the baseline comparisons include tasks with much shorter sequences.

**Severity**: Major (when the assumption materially changes the claim's scope); Minor (when the assumption is standard in the field and a reader would infer it)

---

### 1.3 Circular Reasoning

**Definition**: The conclusion is assumed within the premises. The argument is structured such that the claim to be proven is presupposed in the setup, making the reasoning self-referential rather than demonstrative.

**Detection**: Trace the logical chain from premises to conclusion. If at any step the argument can only proceed by assuming what it sets out to prove, circular reasoning is present. Common forms include: defining evaluation metrics in terms of the method's outputs, using the proposed method's outputs as ground truth, or treating the method's theoretical framing as validated evidence for the theoretical framing.

**Example**: A paper claims a new clustering metric better captures "true" cluster structure, then validates this by showing the metric assigns high scores to clusters produced by the proposed algorithm — without an independent definition of "true" structure.

**Severity**: Critical

---

### 1.4 Correlation as Causation

**Definition**: The paper uses causal language ("causes," "leads to," "results in," "drives") to describe relationships that are established only through correlational or observational methodology. No randomized or controlled experimental design is in place to warrant causal inference.

**Detection**: Identify all causal language in the abstract, introduction, and conclusion. Check the methodology section to determine whether the study design supports causal inference (e.g., randomized controlled trial, natural experiment with a valid instrument, ablation with controlled variables). If the methodology is observational or purely correlational, causal language is unsupported.

**Example**: A paper studying user engagement with recommendation systems concludes "diverse recommendations cause increased session length," when the study observes a correlation in production logs with no controlled assignment of diversity levels.

**Severity**: Major

---

## 2. Experimental Flaws

Flaws in the design, execution, or reporting of experiments and evaluations.

---

### 2.1 Missing Ablation

**Definition**: The proposed system contains multiple novel components but is only evaluated as a whole, making it impossible to attribute performance gains to specific contributions.

**Detection**: Count the number of novel components introduced (architecture changes, training objectives, data augmentation strategies, inference-time modifications, etc.). Check whether the paper includes an ablation table or study that removes or replaces each component independently. If multiple novel components are present and no ablation is reported, this flaw applies.

**Example**: A model introduces a new attention mechanism, a custom loss function, and a two-stage training procedure. The paper reports only whole-system results against baselines without any ablation that isolates each component's contribution.

**Severity**: Major

---

### 2.2 Unfair Baselines

**Definition**: Baselines are evaluated under conditions that disadvantage them relative to the proposed method, such as different compute budgets, less hyperparameter tuning, smaller training sets, or outdated implementations.

**Detection**: Check whether each baseline is given equivalent resources (data volume, compute, tuning budget, training time). Look for disclosures about hyperparameter search: if the proposed method underwent extensive tuning and baselines used default settings or a single configuration, the comparison is unfair. Also check whether baseline implementations are from original authors, reproduced, or re-implemented, and whether reproduced results match original reported numbers.

**Example**: The proposed method is trained for 100 epochs with a tuned learning rate schedule, while baselines are run for 50 epochs with the learning rate from the baseline paper's original setting — which was designed for a different dataset.

**Severity**: Major

---

### 2.3 Cherry-Picked Metrics

**Definition**: The paper reports only the subset of standard evaluation metrics on which the proposed method outperforms baselines, omitting metrics where performance is comparable or worse.

**Detection**: Identify the standard benchmark suite and metric set for the task and venue. Check which metrics are reported. If well-established metrics are absent without explanation, or if supplementary results show underperformance that is not discussed in the main paper, cherry-picking is likely.

**Example**: For a machine translation paper, BLEU is prominently reported but chrF and TER are absent, even though all three are standard for the benchmark. Supplementary tables show the method underperforms on chrF.

**Severity**: Major

---

### 2.4 Test Set Leakage

**Definition**: The test set, test set statistics, or test set labels have influenced any stage of model development, including architecture design, hyperparameter selection, feature engineering, or training data curation — invalidating the evaluation.

**Detection**: Check the evaluation protocol for any mention of test set inspection before final evaluation. Look for patterns such as: model selection using test performance, preprocessing or filtering decisions applied uniformly to train and test, data sourced from the same distribution in a way that makes contamination possible, or reported results that substantially exceed what other methods achieve on the same benchmark.

**Example**: The paper selects the final model checkpoint by picking the epoch with best test set performance, then reports that performance as the result, rather than selecting the checkpoint by validation performance.

**Severity**: Critical

---

### 2.5 Inadequate Error Bars

**Definition**: The paper reports performance as point estimates without accompanying variance information (standard deviation, standard error, or confidence intervals) across repeated runs with different random seeds.

**Detection**: Check all results tables and figures for variance reporting. For stochastic methods (neural networks, randomized algorithms, methods with random initialization), results should include variance across at least three runs. Single-run results presented without variance are inadequate.

**Example**: A paper comparing neural network training methods reports mean accuracy to two decimal places but notes in a footnote that all results are from a single run.

**Severity**: Minor (when differences are large and clearly significant); Major (when differences between methods are small and could plausibly be within variance)

---

### 2.6 Missing Significance Tests

**Definition**: Differences in performance between the proposed method and baselines are not tested for statistical significance. The paper treats numerical differences as meaningful without assessing whether they exceed what would be expected by chance.

**Detection**: Check for mention of statistical significance tests (t-test, Wilcoxon, bootstrap, permutation test, etc.) in the experimental section. If performance differences are within 1–2 percentage points on any metric and no significance test is reported, this flaw applies. Also check whether multiple comparisons are corrected for (Bonferroni, Benjamini-Hochberg, etc.) when many metrics or conditions are tested.

**Example**: A paper claims a 0.8 BLEU point improvement over the best baseline across three language pairs, but no significance test is conducted. Given typical variance in MT evaluations, this difference may not be reliable.

**Severity**: Minor (when differences are large); Major (when differences are small and the paper's central claim rests on them)

---

## 3. Presentation Flaws

Flaws in how information, findings, and structure are communicated to readers.

---

### 3.1 Buried Key Results

**Definition**: The paper's most important findings are placed in supplementary material, appendices, or late in the paper body, while less critical results occupy prominent positions. Readers reading only the main text receive a distorted picture of what the paper shows.

**Detection**: Identify the paper's central claim. Locate where the primary evidence for that claim appears in the document structure. If the key supporting result is not in the main body, or if it appears only after extensive lower-priority material, the result is buried.

**Example**: The main paper reports average performance across all tasks, but the per-task breakdown — which reveals that the method underperforms on three out of seven tasks — appears only in the appendix with no reference in the main text.

**Severity**: Minor

---

### 3.2 Misleading Figures

**Definition**: Figures are constructed in ways that visually exaggerate or obscure patterns in the data, leading readers to draw incorrect impressions from the visual representation.

**Detection**: Check y-axes for truncation (not starting at zero when the scale would suggest it), verify that error bars or confidence intervals are included where variance is relevant, check that comparison figures use the same scale for all methods, and look for cherry-picked time ranges or data slices. Confirm that figure captions accurately describe what is shown.

**Example**: A bar chart comparing method performance has a y-axis starting at 85%, making a 1% difference appear as a 5x difference visually. The caption does not note the truncated axis.

**Severity**: Major

---

### 3.3 Inconsistent Notation

**Definition**: The same symbol, variable name, or term is used with different meanings across sections of the paper, or different symbols are used for the same quantity, creating ambiguity about what is being claimed or described.

**Detection**: Track variable and symbol definitions introduced in the methods section and verify they are used consistently throughout the experiments, analysis, and appendix. Pay particular attention to variables that appear in both theoretical and empirical sections.

**Example**: The letter `n` denotes the number of samples in the methods section but is reused to denote the number of layers in the experiments section without redefinition or disambiguation.

**Severity**: Minor

---

## 4. Related Work Flaws

Flaws in how the paper engages with prior and concurrent work.

---

### 4.1 Missing Key References

**Definition**: Important prior work directly relevant to the paper's contribution is not cited. The omission may be accidental or may serve to inflate the perceived novelty or significance of the contribution.

**Detection**: For the paper's core topic, task, and methodology, identify whether the most widely cited and most recent relevant work is present in the reference list. Look for missing work from the same benchmark, dataset, or problem formulation. Check whether work that directly anticipates or partially achieves the paper's claimed contributions is absent.

**Example**: A paper proposing a new approach to few-shot learning fails to cite three papers from the prior two years that address the same benchmark with similar methods and achieve comparable results.

**Severity**: Major

---

### 4.2 Strawman Descriptions

**Definition**: The paper characterizes prior work inaccurately — typically understating its capabilities, scope, or performance — to make the gap between prior work and the proposed contribution appear larger than it is.

**Detection**: For each cited prior work that the paper claims to improve upon or supersede, verify that the characterization matches what the prior work actually claims and demonstrates. Look for phrases like "X cannot handle Y" or "X fails to address Z" and check whether the cited paper actually demonstrates handling Y or addressing Z.

**Example**: A paper states "existing methods require full supervision and cannot operate in the semi-supervised setting," but one of the cited papers explicitly presents a semi-supervised extension in its Section 4.

**Severity**: Major

---

### 4.3 Citing Without Comparing

**Definition**: The paper lists related work in a related work section but does not compare against it experimentally, qualitatively, or analytically, leaving the reader unable to understand how the proposed approach differs in outcomes from listed prior work.

**Detection**: For each method listed in the related work section, check whether it appears in the experimental comparison tables. If a method is acknowledged as related but absent from experiments, check whether the paper provides a principled reason (e.g., the method requires data unavailable to the authors, code is not released, or the method targets a different evaluation setting). Absence of both experimental comparison and justification indicates this flaw.

**Example**: The related work section discusses four papers as directly related methods. Only one of those four appears in the comparison table. The other three are mentioned in one sentence each with no discussion of why they are not included in experiments.

**Severity**: Minor (when the omitted methods are acknowledged and a reason is given); Major (when directly competing methods are listed but silently excluded from quantitative comparison)
