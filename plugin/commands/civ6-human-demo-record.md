# /civ6-human-demo-record

Record human-play Civ6 demonstrations into a separate SQLite reference
database. This command captures facts and read-only snapshots. It does not run
strategy policy, choose actions, advance turns, write `episodes/`, generate
candidate playbooks, or modify strategy assets.

## Commands

- `start`: create/resume a demo and capture the first before snapshot.
- `advance`: capture after state, compute delta, and create a pending inferred
  action for later Codex summary.
- `record-inference`: write a Codex-generated summary, evidence list, and
  confidence into SQLite.
- `correct`: write a human correction.
- `note`: write a manual demo note.
- `finish`: complete the demo and generate HTML.
- `report-only`: regenerate HTML from SQLite.
- `watch`: read-only turn polling that records after the human advances.

`self-play` action execution has been removed from the human-demo boundary. Use
the live driver for automated gameplay and this command only for human-demo
capture/storage.

## Outputs

- `human_demos/<demo_id>/demo.sqlite`
- `human_demos/<demo_id>/report.html`
- SQLite `action_facts` rows for structured facts.

## Boundaries

- No live gameplay mutation.
- No rules runner or action-selection policy.
- No automatic turn ending.
- No strategy asset writes.
- Human-demo evidence is reference material until it enters a separate
  candidate, validation, and governance path.

## Examples

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record start --save-name "test 1" --turns 20
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record advance --db human_demos\<demo_id>\demo.sqlite
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record finish --db human_demos\<demo_id>\demo.sqlite
```

Watch mode:

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'O:\civ6\.tools\uv\uv.exe' run codex-hl-civ6-human-demo-record watch --save-name "test 1" --demo-id <demo_id> --poll-seconds 3 --stable-seconds 4 --max-turns 0
```
