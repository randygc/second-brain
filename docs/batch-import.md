# Five-day action-set import

The `import-batch` command imports every action in one complete five-day extraction into the explicitly configured Linear destination. It uses the same replaceable `ActionStore.ensure_action` interface as single-action import. No custom lifecycle UI or additional source connector is introduced.

## Plan and execute

Start with the JSON report produced by `preview`. The default is a local-only plan, without credentials, journal writes or network access:

```bash
.venv/bin/python -m second_brain import-batch \
  --report .local/reports/calendar-2026-09-28/report.json \
  --workspace-id WORKSPACE_UUID --team-id TEAM_UUID
```

To execute, add:

```bash
  --api-key-file .local/linear-api-key \
  --results-file .local/import-batch-results.json \
  --execute
```

Use the same workspace, team and `.local/linear-imports.sqlite3` journal as the single-action import. The journal is shared, so the earlier issue is recognized instead of recreated. Optionally specify `--backlog-state-id` if the team's Backlog-category status is ambiguous. No team or status is silently created.

The report lists daily matching-event/action counts and an outcome for every action: `created`, `already_imported`, `reconciled` after an uncertain create response, or `failed`. Exit code 0 means a complete successful batch, 2 means per-action failures occurred, and 1 means validation/setup/report-writing failed. A failure does not imply that a destination issue was never created: the reservation allows read-only reconciliation. Private machine-readable results are saved owner-only. Original source and action data remain local or in your selected Linear workspace, not in public source control.

## Identity and preservation

Title-defined actions keep the existing title-slot identity. Description-defined actions use their initial ordinal within a source record; identity is scoped by source type, calendar and event/series, never by text. Equal text from different records or separate slots remains independent. Recurring-series extraction is already deduplicated by preview and is not expanded again by import.

The adapter freezes original source content in its initial journal snapshot. If it changes, this slice refuses to add or replace slots rather than guessing how lines moved. Review handling for source changes belongs to issue #5. User edits, status, original creation timestamps, initial scheduled dates and initial provenance remain unchanged on reruns.

Every new issue starts in Backlog and retains full associated details, links, bullets and a structured provenance section. Parentless supporting content is kept as one item with a visible unresolved review flag. If the action exceeds the destination title limit, the display title is shortened and its full original text remains in the description and exact extracted-payload JSON. Display-only Markdown normalization (blank lines, list markers, link angle brackets and escaped leading dashes) is permitted during verification; the original content and extracted payload in provenance remain exact.

## Partial failures and resume

Each reservation is committed before its create can be attempted. The journal records whether a create was claimed, distinguishing failures before a write from uncertain attempted writes. Read-only preflight failures or insufficient request budget can safely resume the same reservation on a later run. Once a create may have been sent, no blind second mutation is attempted: read the reserved UUID, return the existing issue if visible, or stop for manual resolution. Concurrent runs cannot both claim the same creation.

The earlier single-action journal is migrated in place. Existing rows are conservatively marked as potentially attempted; their reserved UUIDs and snapshots stay intact. Back up the journal and never switch journals to work around a failure.

Workspace/team and Backlog reads are cached within one invocation; the request budget is bounded by batch size and capped at 1,000 requests. Actual provider exhaustion stops further requests. Limits or permissions can cause partial runs; the result records those failures rather than claiming complete success.

## Verification

43 automated tests pass, covering all six historical parsing structures, multiple-action slots, independent identical text, parentless content, recurrence, native edit/status preservation, partial-run outcomes, preflight/budget resume, uncertain-create safety and actual observed Markdown canonicalization patterns.

Live validation on October 27, 2026 used the accepted September 28–October 2 extraction: 9 matching event occurrences and 14 actions. Thirteen new Linear issues were created; the single-action issue already existed. Every issue's title, Backlog state, associated details and exact original provenance JSON were checked. The initial run surfaced strict Markdown-verification failures; read-only inspection confirmed the writes and content, the checks were corrected, and a rerun returned all 14 existing issues with zero new creates and zero failures. No Calendar events were modified.
