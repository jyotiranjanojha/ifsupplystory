---
name: "IFSP Scenario Comparison"
description: "Compare two weekly planning scenarios and explain key deltas in demand, supply, constraints, and root causes with grounded evidence."
argument-hint: "Provide week, base scenario, compare scenario, product/site scope, and key metrics."
agent: "IFSP Planning Copilot"
---
Compare two Intel Foundry Supply Planning scenarios using grounded planning data and return an analyst-ready summary.

Use the user input to identify:
- Planning week
- Base scenario ID
- Compare scenario ID
- Scope (product, site, region, customer, or node)
- Priority metrics (for example: demand met percent, unmet demand, capacity utilization, lateness)

Data location default:
- Read BY ESP setup/input datasets from `by_input/`.
- Read BY ESP plan result/output datasets from `by_output/`.
- If any required evidence is missing, use Snowflake or request additional data.

## Required Method
1. Confirm identifiers and scope. If missing, ask for the minimum missing identifiers first.
2. Retrieve comparable setup/input data from `by_input/` and outcome/output data from `by_output/` for both scenarios.
3. Validate data comparability (same week grain, entity keys, and metric definitions).
4. Compute and rank the largest deltas.
5. Explain likely drivers using master data, BOM, parameter, lineage, and output evidence.
6. Separate confirmed findings from hypotheses when evidence is partial.

## Output Format
1. Comparison Scope
2. Data and Evidence Used
3. Top Delta Metrics (ranked)
4. Likely Drivers and Root Causes
5. Confirmed Findings vs Hypotheses
6. Confidence and Data Gaps
7. Recommended Next Checks

## Style
- Keep language concise and functional.
- Prefer explicit planning terms (demand, supply, capacity, BOM, parameter, lineage).
- Keep conclusions traceable to evidence.
