# Five-day action-set import

The `import-batch` command imports every action in one complete five-day extraction into the explicitly configured Linear destination. It uses the same replaceable `ActionStore` interface (`review_source` and `ensure_action`) as single-action import. No custom lifecycle UI or additional source connector is introduced.

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

The report lists daily matching-event/action counts and an outcome for every action: `created`, `already_imported`, `reconciled` after an uncertain create response, `changed` (held for review), or `failed`. Exit code 0 means a complete successful batch, 2 means an action or source review failed, and 1 means validation/setup/report-writing failed. A failure does not imply that a destination issue was never created: the reservation allows read-only reconciliation. Private machine-readable results are saved owner-only. Original source and action data remain local or in your selected Linear workspace, not in public source control.

## Identity and preservation

Title-defined actions keep the existing title-slot identity. Description-defined actions use their initial ordinal within a source record; identity is scoped by source type, calendar and event/series, never by text. Equal text from different records or separate slots remains independent. Recurring-series extraction is already deduplicated by preview and is not expanded again by import.

The adapter freezes original source content in its initial journal snapshot. If source text changes, or a nonrecurring event is rescheduled, import compares each matched action with its original extracted payload, appends unresolved review comments only for changed, removed, or ambiguously matched actions, and holds all the source record’s current slots. New or reordered lines are not imported automatically. Each comment shows the formatted current action name and details, with the Calendar modification timestamp separate from original creation. Original snapshots remain in the import journal and original issue provenance; full source observations remain in the private preview. Comment UUIDs are reserved durably before writes; repeat observations do not duplicate comments. An uncertain comment write is reconciled by UUID without a blind retry. User edits, status, original creation timestamps, initial scheduled dates and initial provenance remain unchanged on reruns.

Every new issue starts in Backlog and retains full associated details, links, bullets and a structured provenance section. Parentless supporting content is kept as one item with a visible unresolved review flag. If the action exceeds the destination title limit, the display title is shortened and its full original text remains in the description and exact extracted-payload JSON. Display-only Markdown normalization (blank lines, list markers, link angle brackets and escaped leading dashes) is permitted during verification; the original content and extracted payload in provenance remain exact.

## Partial failures and resume

Each reservation is committed before its create can be attempted. The journal records whether a create was claimed, distinguishing failures before a write from uncertain attempted writes. Read-only preflight failures or insufficient request budget can safely resume the same reservation on a later run. Once a create may have been sent, no blind second mutation is attempted: read the reserved UUID, return the existing issue if visible, or stop for manual resolution. Concurrent runs cannot both claim the same creation.

The earlier single-action journal is migrated in place. Existing rows are conservatively marked as potentially attempted; their reserved UUIDs and snapshots stay intact. Back up the journal and never switch journals to work around a failure.

Workspace/team and Backlog reads are cached within one invocation; the request budget is bounded by batch size and capped at 1,000 requests. Actual provider exhaustion stops further requests. Limits or permissions can cause partial runs; the result records those failures rather than claiming complete success.

## Verification

56 automated tests pass, covering all six historical parsing structures, multiple-action slots, independent identical text, parentless content, recurrence, native edit/status preservation, partial-run outcomes, preflight/budget resume, uncertain-create safety and actual observed Markdown canonicalization patterns.

Live validation on October 27, 2026 used the accepted September 28–October 2 extraction: 9 matching event occurrences and 14 actions. Thirteen new Linear issues were created; the single-action issue already existed. Every issue's title, Backlog state, associated details and exact original provenance JSON were checked. The initial run surfaced strict Markdown-verification failures; read-only inspection confirmed the writes and content, the checks were corrected, and a rerun returned all 14 existing issues with zero new creates and zero failures. No Calendar events were modified.

## Overlapping windows and source review

Generate a fresh five-day preview with another `--start-date`, then use the same import command and journal. Previously imported event/series slots remain independent of text and dates. A recurring occurrence in the later window preserves the first imported scheduled date. Unseen records are created in Backlog; empty matching records create no issues.

Results include per-action outcomes, `source_reviews`, `changed_sources`, and `affected_existing_actions`. The per-action `changed` count describes current extracted slots held for review; the affected-existing count includes original actions whose lines have since disappeared. Observed records renamed away from Action are recognized by identity and content fingerprint, without retaining unrelated calendar text. Absence from a window, canceled records, and read failures never imply deletion; deletion/cancellation handling remains issue #6. Reviews stay unresolved until later explicit resolution support.

Live overlap verification on October 27 used September 30–October 4: seven matching event occurrences, four actions, all four recognized as existing, zero creates, zero changed sources, zero failures. The two new dates contained no extractable actions. Controlled adapter tests exercise unseen records, changed-source comments, preserved native edits, recurring later dates, removed action titles, and lost/failed comment responses. Linear's comment schema was checked read-only; this live window contained no changed source, so comment creation was not exercised against live Linear.

## Readable action-specific review comments

As requested October 27, comments show the extracted updated action name and associated formatted details instead of a raw provenance JSON dump. Include the Calendar source modification timestamp; Linear's own comment timestamp describes when the comment was posted, not when Calendar changed.

Match unique unchanged action names first, then unique prefix edits; title-defined single-action records retain their title slot across renames. Never match by shifted ordinals alone. When an original action is now supporting content or has no remaining independent counterpart, explain that it may have been removed or made a bullet and suggest manual deletion of its Linear issue. Include the updated parent action when its details contain the former action text. Ambiguous renames/duplicate names present updated candidates for manual review rather than asserting correspondence or recommending deletion. No issue is deleted or edited automatically.

The revised presentation adds one readable follow-up per original action for an already-recorded changed revision, preserving earlier raw-evidence comments. Subsequent runs reuse the same reservation and do not add another copy. Live verification of the accepted changed September 28 event created and read back seven readable comments on RAN-10–RAN-16; RAN-11 received the removal/bullet explanation and deletion suggestion, while RAN-10 received the updated grid action with its supporting timeframe bullet. No replacement issues or failures occurred.

### Suppress unchanged sibling reviews

A changed source record does not mean that each of its actions changed. Before generating a comment, compare the matched action's original name, details, and review flags with the current extraction, allowing the same display-only Markdown normalization used for read-back. An unchanged sibling gets no comment even when an action was inserted, removed, reordered, or moved into a bullet elsewhere in the source. Nonrecurring scheduled-date changes still warrant review; recurring occurrence dates and source modification timestamps alone do not.

Regression replay of the saved live change selects RAN-10, RAN-11, and RAN-12 for review, while RAN-13–RAN-16 remain unchanged. This replay is local and leaves previously posted comments intact. `affected_existing_actions` counts actions warranting review; the per-action `changed` result count continues to mean current extracted slots held because their source changed, not the number of newly posted comments.
