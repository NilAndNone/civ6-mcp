"""Boundary and vocabulary contract for Codex HL Civ6."""

CONTRACT_TERMS = {
    "episode": "A recorded run segment that can be reviewed and resumed.",
    "turn_snapshot": "A per-turn state capture grounded in Civ6 connector output.",
    "decision_atom": "A key decision with context, candidates, choice, rationale, outcome, and evidence links.",
    "asset": "A versioned prompt, playbook, tool policy, or low-trust memory reference.",
    "scenario": "A reproducible validation setup, not proof of general improvement by itself.",
}

CONTRACT_CHECKLIST = [
    "Use the roadmap vocabulary consistently.",
    "Treat memory as low-trust reference only.",
    "Keep Observation observation separate from Review+ failure attribution.",
    "Do not promote strategy assets from a single test run.",
]
