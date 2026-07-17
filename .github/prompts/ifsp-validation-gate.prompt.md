---
name: "IFSP Validation Gate"
description: "Run pre-solve validation checks for master data, BOM integrity, and planning parameters, then report readiness and risks with evidence."
argument-hint: "Provide week, scenario, scope, and validation focus areas."
agent: "IFSP Planning Copilot"
---
Run a validation-only quality gate for Intel Foundry Supply Planning data before solve or before explainability analysis.

Use the user input to identify:
- Planning week
- Scenario ID
- Scope (product, site, region, customer, or node)
- Validation focus areas (master data, BOM, parameters, output sanity)

Data location default:
- Read BY ESP plan inputs from `by_input/`.
- Read BY ESP plan outputs from `by_output/`.
- If required evidence is missing, then query Snowflake or request additional files.

## Required Method
1. Confirm identifiers and scope. If missing, ask for the minimum missing identifiers first.
2. Retrieve required input datasets from `by_input/` and output datasets from `by_output/` for the stated week and scenario.
3. Validate master data completeness and key consistency.
4. Validate BOM integrity (missing links, broken hierarchy, invalid quantities, effectivity issues).
5. Validate planning parameters (lead time, lot size, capacity settings, sourcing rules, policy flags).
6. Validate output sanity checks against expected ranges and business rules.
7. Classify each issue by severity and business impact.
8. Provide clear pass/fail readiness with remediation priorities.

## Output Format
1. Validation Scope
2. Datasets and Evidence Used
3. Checks Executed
4. Issues Found (Critical, High, Medium, Low)
5. Readiness Verdict (Pass, Conditional Pass, Fail)
6. Root Causes and Likely Planning Impact
7. Recommended Fixes (ordered by impact)
8. Confidence and Data Gaps

## Style
- Keep language concise and operational.
- Use explicit planning terms and trace each issue to evidence.
- Separate confirmed defects from potential risks.
