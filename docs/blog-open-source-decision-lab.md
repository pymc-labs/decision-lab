# Why We're Open-Sourcing Decision Lab: Scaling Judgment, Not Just Automation

A company deployed an AI agent to answer leadership questions about their marketing metrics. For three months, executives made strategic decisions based on its reports — budget reallocations, channel investments, headcount planning. The code was flawless. The analytics were entirely fabricated. Nobody noticed because the outputs looked exactly like what a competent analyst would produce: clean charts, confident recommendations, plausible numbers.

This is the core tension in agentic data science today. Coding agents write good code. They make bad analytical decisions. And the gap between those two things is where real damage happens.

That gap is why we built Decision Lab — and why we're releasing it as open source.

## The Garden of Forking Paths

Every analytical workflow is a series of judgment calls. How do you handle missing values? Which model structure fits the problem? What priors encode reasonable domain knowledge? What diagnostics confirm the model actually learned something real?

Experienced data scientists navigate this space using intuition built over years of practice. They know when a result "smells wrong." They know which shortcuts are safe and which ones hide landmines. Language models navigate the same space probabilistically — and they're remarkably good at producing plausible-sounding nonsense wrapped in confident language.

A recent paper by Bertran, Fogliato, and Wu (2026) demonstrated this concretely: autonomous agents given identical datasets produced wildly divergent conclusions, with different runs frequently reversing whether a hypothesis was supported. The code executed perfectly every time. The analytical decisions were effectively random.

These are not code quality problems. They are judgment problems. And you cannot solve judgment problems by writing better prompts.

## Our Vision: Agentic Data Science Done Right

At PyMC Labs, we believe the potential of agentic data science is enormous — but only if we build it on the right foundation. Our vision is clear:

> *Make Data Science accessible and efficient with an open source general agent to revolutionize decision intelligence across the enterprise.*

This is an ambitious statement, and we mean every word. But ambition without rigor is how you end up with fabricated analytics running unchecked for three months. So we grounded this vision in three pillars — the framework Luca Fiaschi laid out in his recent piece on [trustworthy AI agents](https://www.linkedin.com/pulse/agentic-data-science-three-pillars-trustworthy-ai-luca-fiaschi-phd--bsg0e/) — that make it achievable rather than reckless.

**Constraints as Skills.** The first pillar replaces prompt-based guidance with validated playbooks that encode real domain expertise. A "skill" is not a paragraph of instructions — it is a structured runtime document specifying mandatory diagnostics, preferred model structures, Bayesian priors, and the checks that must pass before any conclusion reaches a human. Think of it as the difference between a certified mechanic following a diagnostic protocol and an untrained person confidently recommending unnecessary repairs.

We tested this directly. We gave Claude Code a set of Bayesian modeling tasks with and without domain skills. On difficult problems like stochastic volatility, the unconstrained agent produced zero converged models. With domain skills installed, two out of three runs succeeded. Same model, same data — different judgment.

**Measurement.** The second pillar moves evaluation beyond what Luca calls "vibes" — does the output look reasonable? Instead, we propose a verification stack with multiple layers: execution (does the code run?), diagnostics (did the model converge?), predictive checks (does the model match observed reality?), sensitivity analysis (do conclusions hold under alternative assumptions?), and human checkpoints. Each layer catches a different class of failure. Skip any one of them, and you're back to hoping the output looks right.

**Epistemic Humility.** The third pillar treats Bayesian uncertainty quantification as an engineering requirement, not a philosophical preference. Rather than point estimates — "Channel A has 3.2x ROI" — agents should communicate credible intervals showing the full range of plausible values. And when the data cannot support a conclusion, the agent should say so.

In one of our tests, we gave both a vanilla agent and a Bayesian-equipped agent a marketing mix dataset with weak signal and high noise. The vanilla agent recommended reallocating 100% of budget to television. The Bayesian agent said: "Signal is too weak. I recommend gathering more data before making allocation decisions." That is the kind of judgment we need to scale.

## Decision Lab: The Three Pillars, Implemented

Decision Lab is where these principles become software. It is an open-source framework that red-teams your analysis — the agent tries to break its own conclusions before showing them to you.

We tested this on marketing mix modeling, our first enterprise-ready decision-pack. We gave a vanilla coding agent and a Decision Lab agent the same adversarial dataset where no valid inference was possible.

The vanilla agent fit a model and recommended budget reallocations. Confidently wrong.

Decision Lab explored 11 modeling approaches, found that none converged, and reported:

```
No valid model found
  11 modeling approaches attempted — 0 converged
  Root cause: insufficient signal in current data
  Recommendation: run a geo-holdout experiment to isolate channel effects
```

That is the difference: an agent that knows when to say "we don't know."

The architecture maps directly to the three pillars. **Constraints as Skills** become decision-packs — directories containing domain skills, agent prompts, and pinned environments so the agent codes against the right library versions. **Measurement** is built into the workflow: the agent runs mandatory diagnostics, stress-tests its conclusions, and actively tries to falsify its own results. **Epistemic Humility** is the default posture: if the agent cannot break its conclusions, you can trust them; if it can, it tells you exactly why and what to do next.

## Why Open Source?

We could have kept this behind a paywall. Here is why we did not.

**Judgment does not scale behind closed doors.** Domain expertise is distributed. The MMM team at a retail company knows things the PyMC Labs team does not, and vice versa. The forecasting team at a logistics firm has battle-tested knowledge about seasonality patterns that no single organization could replicate. Open-sourcing Decision Lab lets the community contribute decision-packs, validate them against real data, and share what works across domains.

**Trust requires transparency.** If the value proposition is "an agent that knows when it doesn't know," the framework itself cannot be a black box. Practitioners need to verify, audit, and extend the verification stack. They need to see exactly how the agent decides when to trust a result and when to flag uncertainty. Open source makes that possible.

**This is how PyMC was built.** PyMC Labs has always believed that the best scientific tools are community-driven. PyMC and pymc-marketing were built this way. Decision Lab is the natural next step — taking the same philosophy of rigorous, transparent, Bayesian decision-making and applying it to the agentic era.

## An Ecosystem, Not Just a Tool

Decision Lab is one piece of a larger ecosystem we are building. Decision Hub is an open registry of over 2,200 validated skills from 38 organizations, covering analytics domains from marketing mix modeling to time series forecasting. Together, Decision Lab and Decision Hub form the foundation of an ambitious initiative: giving every organization access to the kind of rigorous, domain-informed analytical agents that previously required a team of specialized data scientists.

This is just the beginning. We see this ecosystem expanding across domains, across industries, and across the full spectrum of decision intelligence — from exploratory analysis to production-grade automated reporting.

The measurable impact for businesses is direct: **reducing time-to-decision and time-to-insight**. When an analytical agent can explore multiple modeling approaches, validate its own conclusions, and produce a trustworthy report in hours instead of weeks, the ROI is not theoretical. It shows up in faster strategic decisions, more efficient use of data science resources, and fewer costly mistakes from unchecked analytical errors.

## Get Involved

Decision Lab is available now under the Apache 2.0 license.

- Install it and run the MMM decision-pack on the included example dataset
- Build your own decision-pack for your domain with the interactive creation wizard
- Contribute skills to Decision Hub and help validate them against real-world data
- Join the community and help shape the roadmap

We believe the future of AI in data science is about scaling judgment, not just automation. Decision Lab is our bet on how to get there — and we are building it in the open because the judgment we need to encode does not live in any single organization.

[GitHub: pymc-labs/decision-lab](https://github.com/pymc-labs/decision-lab)
