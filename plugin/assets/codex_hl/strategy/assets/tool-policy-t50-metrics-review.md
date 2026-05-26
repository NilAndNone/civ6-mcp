# Asset: strategy.tool_policy.t50_metrics_review

## Purpose

This tool policy defines the first strategy metric comparison gate.

## Primary T50 Metrics

Strategy compares recorded T50 episodes using the roadmap's first metrics:

- city count;
- completed technology count and current research;
- completed civic count and current civic;
- science yield;
- culture yield.

## Review Policy

- Compare only already-recorded episode state snapshots.
- Prefer the `t50_final` state when present; otherwise use the highest recorded
  turn state.
- Treat a single `test 1` improvement as candidate evidence only.
- Do not claim general strategy improvement from one run.
- Do not generate asset diffs, merge assets, run replay, start Civ6, or roll
  back files from metric comparison.
- Metric deltas must preserve baseline and candidate episode ids and final state
  paths so reviewers can audit the source evidence.
