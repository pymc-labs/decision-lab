---
name: Methodology Evaluation
description: Evaluation frameworks for different paper types (empirical ML, theoretical, systems, statistical modeling). Provides checklists for methodology auditors and decomposer agents.
---

# Methodology Evaluation

This skill provides structured evaluation frameworks for assessing the methodological rigor of research papers across four major paper types. Each framework contains checklists designed for use by methodology auditors and decomposer agents.

---

## 1. Empirical ML Papers

### Dataset & Evaluation Checklist

- [ ] **Data splits described**: Train/validation/test splits are clearly defined with sizes reported
- [ ] **No test leakage**: Test set is held out and never used for model selection or hyperparameter tuning
- [ ] **Dataset size adequate**: Sample size is sufficient to support the claims being made
- [ ] **Bias acknowledged**: Known dataset biases, collection artifacts, or distributional limitations are discussed
- [ ] **Evaluation metrics justified**: Choice of metrics is explained and appropriate for the task
- [ ] **Multiple metrics reported**: More than one evaluation metric is used to give a complete performance picture

### Experimental Design Checklist

- [ ] **Fair baselines**: Baselines are given equal access to resources (compute, data, tuning) as the proposed method
- [ ] **Relevant baselines**: Comparisons include strong, recent, and appropriate prior work for the domain
- [ ] **Ablation study**: Components of the proposed method are individually tested to show their contribution
- [ ] **Variance reported**: Results include standard deviation, confidence intervals, or error bars across runs
- [ ] **Statistical significance**: Significance tests (e.g., t-test, Wilcoxon) are used where appropriate
- [ ] **Compute budget reported**: Training time, GPU hours, and hardware specs are disclosed

### Reproducibility Checklist

- [ ] **Hyperparameters listed**: All tuned and fixed hyperparameters are reported in sufficient detail
- [ ] **Architecture details complete**: Model architecture (layers, sizes, activations, etc.) is fully specified
- [ ] **Training procedure described**: Optimizer, learning rate schedule, batch size, and stopping criteria are given
- [ ] **Code availability**: Code is released or will be released upon acceptance
- [ ] **Random seeds reported**: Seeds used for data shuffling, weight initialization, and sampling are documented

---

## 2. Theoretical Papers

### Proof Quality Checklist

- [ ] **All assumptions stated**: Every assumption required for the result is explicitly listed before the proof
- [ ] **Assumptions reasonable**: Stated assumptions are justifiable in realistic or well-motivated settings
- [ ] **Proof complete (no hand-waving)**: Each step in the proof is fully justified with no unexplained leaps
- [ ] **Bound is tight**: The result includes a matching lower bound or discussion of tightness
- [ ] **Proof technique appropriate**: The chosen proof method is well-suited to the problem structure
- [ ] **Edge cases handled**: Degenerate or boundary cases are addressed within or following the main proof

### Theory-Practice Gap Checklist

- [ ] **Practical relevance discussed**: The authors articulate why the theoretical result matters in practice
- [ ] **Gap acknowledged**: Differences between the theoretical setting and real-world conditions are noted
- [ ] **Empirical validation where possible**: Experiments or examples are provided to support the theoretical claims
- [ ] **Constants are reasonable**: Hidden constants in asymptotic results are estimated or discussed for practical applicability

---

## 3. Systems Papers

### Benchmark Validity Checklist

- [ ] **Workload representative**: Benchmarks reflect realistic or standard workloads for the target use case
- [ ] **Comparison fair**: All systems are evaluated under equivalent configurations and resource constraints
- [ ] **Scalability tested**: Performance is evaluated across a range of input sizes, data volumes, or concurrency levels
- [ ] **Bottleneck analysis**: The paper identifies where the system spends time and what limits peak performance

### Measurement Methodology Checklist

- [ ] **Warm-up runs**: System is warmed up before measurements to eliminate cold-start artifacts
- [ ] **Multiple trials**: Each measurement is repeated and results are aggregated (mean, median, or similar)
- [ ] **Resource accounting**: CPU, memory, disk I/O, and network usage are tracked and reported where relevant
- [ ] **End-to-end metrics**: Measurements include full pipeline overhead, not only the optimized component
- [ ] **Latency distribution (p50/p99 not just mean)**: Tail latencies (e.g., p99) are reported alongside median to capture variability

---

## 4. Statistical Modeling Papers

### Model Specification Checklist

- [ ] **Generative process described**: The full data-generating model is stated (e.g., via plate diagram or formal notation)
- [ ] **Prior choices justified**: Prior distributions are explained with rationale (informative, weakly informative, or non-informative)
- [ ] **Likelihood appropriate**: The chosen likelihood function matches the data type and measurement process
- [ ] **Identifiability**: The model parameters are identifiable from the data, or non-identifiability is acknowledged and handled

### Inference Quality Checklist

- [ ] **Convergence diagnostics (R-hat, ESS)**: R-hat values near 1.0 and sufficient effective sample sizes are reported for MCMC
- [ ] **Posterior predictive checks**: Simulated data from the posterior is compared to observed data to assess model fit
- [ ] **Sensitivity analysis**: Results are tested under alternative priors or model specifications to assess robustness
- [ ] **Multiple chains**: MCMC inference uses at least 4 independent chains to detect convergence failures

### Causal Claims Checklist (if applicable)

- [ ] **Causal assumptions explicit (DAG)**: A directed acyclic graph or equivalent formalism is provided to encode causal structure
- [ ] **No unmeasured confounders justified**: The authors argue why unmeasured confounding is unlikely or controlled for
- [ ] **Intervention vs observation clear**: The paper distinguishes between observational associations and interventional effects
- [ ] **Identification strategy**: A valid identification strategy (e.g., instrumental variables, regression discontinuity, front-door criterion) is described and justified
