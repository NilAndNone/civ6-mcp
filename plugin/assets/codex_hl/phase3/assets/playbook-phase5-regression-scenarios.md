# Phase 5 Regression Scenarios Playbook

Phase 5 turns real failures into a growing regression scenario pool.

Rules:

- Ingest only confirmed Phase 2 failures.
- Preserve source episode, source failure, evidence refs, save refs, expected behavior, and failed behavior.
- Write the shared pool under `validation/regression_scenarios/` unless the caller explicitly chooses another pool root.
- Mark new scenarios as passive and not runnable until a replay harness exists.
- Do not launch Civ6, load saves, replay turns, or generate asset diffs during scenario registration.
- Use the scenario pool as the minimum validation substrate for L4/L5 governance.
