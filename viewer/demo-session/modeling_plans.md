# Modeling Plans

Based on data exploration, I propose 3 modeling strategies to run in parallel:

## Plan 1: Standard Saturating MMM (Geometric Adstock)
- **Data prep**: Approach 1 (minimal cleaning, all 156 weeks)
- **Adstock**: Geometric decay per channel
- **Saturation**: Logistic per channel
- **Priors**: Moderately informative (industry benchmarks)
- **Rationale**: Baseline model, well-understood behavior

## Plan 2: Flexible Adstock MMM (Weibull CDF)
- **Data prep**: Approach 1 (minimal cleaning, all 156 weeks)
- **Adstock**: Weibull CDF (more flexible peak timing)
- **Saturation**: Logistic per channel
- **Priors**: Moderately informative, wider on adstock shape
- **Rationale**: TV and Print may have delayed peak effects that geometric can't capture

## Plan 3: Conservative Data + Geometric Adstock
- **Data prep**: Approach 2 (conservative cleaning, 148 weeks)
- **Adstock**: Geometric decay per channel
- **Saturation**: Logistic per channel
- **Priors**: Informative (tighter bounds from prior studies)
- **Rationale**: Test sensitivity to data cleaning choices and prior strength
