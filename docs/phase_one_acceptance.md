# Phase one acceptance

The requested product is a continuously evolving factor research system with a professional, accessible research frontend. A runnable loop alone does not satisfy this objective.

## Research evidence

- Import reproducible real stock panels with historical membership and explicit price, label, missing-data and corporate-action semantics.
- Establish fixed published-factor and simple-search baselines before tuning the adaptive system.
- Produce formulas with dated, out-of-sample evidence. Report uncertainty, coverage, turnover and execution-cost sensitivity. Unverified delisting settlement remains an explicit limitation.
- Compare random search, Wake, equal-budget recent replay and Wake–Sleep under the same candidate budget and evaluation dates. Improvement is an empirical requirement, not a property inferred from the architecture name.
- Retain failed candidates and negative results. Once historical holdout outcomes inform development, that period is no longer an untouched holdout for revised methods.

## Continuous operation

- Advance only when new observations and matured labels are available; repeated runs must not duplicate research events.
- Persist and restore search state, pending evaluations, policy updates and the factor library.
- Track degradation and retirement of previously useful factors. Historical replay must have a measurable effect and an independent comparison.

## Research frontend

- Expose real research runs, data provenance, formulas, lifecycle status and evaluation windows through the application API.
- Provide a searchable factor library and factor detail views with historical evidence, uncertainty and baseline comparisons.
- Show pending, failed and insufficient-evidence states accurately, with usable loading and error behavior.
- Verify the rendered frontend and its connection to actual persisted research results. A static report or the existing fixed-window Loop page is insufficient.

## Delivery

After the evidence and product requirements are met, consolidate duplicated experiment logic, remove task-created temporary artifacts, run affected checks and report actual results and remaining limitations. Preserve original experiments and unrelated user changes.

## Current evidence boundary

The three-ETF temporal experiment and 2026 follow-up have not established reliable factor discovery or a Wake–Sleep advantage. The fixed stock-panel momentum diagnostic is the next empirical check. No positive result or frontend completion is implied by this document.
