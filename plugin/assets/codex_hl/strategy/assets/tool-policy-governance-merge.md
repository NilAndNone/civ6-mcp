# Governance Auto Merge Tool Policy

L4/L5 governance defaults to audit-only evaluation.

Auto merge can run only when all gates pass:

- At least two scenarios are present.
- Every scenario result is pass.
- At least one T50 main metric improves.
- No T50 main metric regresses.
- There are no regression records.
- The target asset hash still matches the candidate package.
- The candidate has source failures and a rollback plan.
- The caller explicitly passes the merge flag.

When merge is allowed:

- Write a merge decision audit.
- Write a rollback snapshot before changing files.
- Update asset content, catalog hash/version, and ledger together.
- Keep rollback available from the audit directory.

Rollback must restore asset content and catalog hash from the audit snapshot and append a rollback ledger row.
