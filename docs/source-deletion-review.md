# Deleted or cancelled Calendar source review

`review-sources` checks the source identities already recorded in the shared import journal for the explicitly selected workspace, team and Calendar. It is a separate step from the five-day preview/import, so an event moved outside the current window is never mistaken for a deletion. It creates no actions and performs no Calendar writes.

## Plan and execute

Run a read-only check first (Google access is required; no Linear key is needed):

```bash
.venv/bin/python -m second_brain review-sources \
  --calendar-id YOUR_CALENDAR_ID \
  --workspace-id WORKSPACE_UUID --team-id TEAM_UUID \
  --token-file .local/google-token.json \
  --results-file .local/source-review-plan.json
```

To post unresolved comments for confirmed deletions/cancellations, add:

```bash
  --api-key-file .local/linear-api-key --execute
```

Keep the same `.local/linear-imports.sqlite3` journal used by imports, or specify its existing path with `--journal`. The command checks at most 100 distinct source records by default; increase `--max-records` explicitly when needed. The Linear request budget is capped at 1,000 requests per invocation. The command has no scheduler; future daily ingestion should invoke source review as well as action discovery.

## Evidence and preservation

For each known source, verify Calendar access and GET the exact saved event identity. For recurring actions, GET the parent series identity, not an occurrence. A confirmed parent series remains active even if an occurrence was cancelled. A cancelled parent series warrants review on each of its imported actions.

Only an explicit `status: cancelled` response for the saved identity, or an event GET returning HTTP 410 with the specific `deleted` reason, is accepted as deletion evidence. Google uses cancelled status for deleted Calendar events; minimal tombstones may contain only the event ID. Such evidence does not establish who deleted the event or why. A missing deletion timestamp stays unavailable, rather than substituting the original creation date.

HTTP 404, access errors, expired sync tokens, malformed responses, failed connections, empty lists and absence from a date window never imply deletion. They produce failed/unknown checks with no deletion comments. Each failed check is reported independently; safely confirmed evidence for other records can still be processed.

An unresolved readable comment identifies the deleted/cancelled source and retains the original extracted action name/details for context. Linear issue titles, descriptions, original provenance, creation timestamps and workflow statuses are untouched. No issue is automatically deleted, cancelled, completed or resolved. Previously posted evidence remains unresolved even if a source later reappears; restoration/resolution automation is outside this slice.

The existing durable comment reservations prevent repeated runs from adding duplicates. Tombstone and explicit-deleted HTTP representations share one deletion review identity. Lost write responses are reconciled by reserved comment UUID, without a second blind mutation. Back up the journal; do not replace it to work around an uncertain outcome.

## Results

Results are written owner-only and include one outcome per checked source:

- `active`: confirmed/tentative source still exists; no comment.
- `planned`: reliable deletion evidence found during the default read-only check.
- `flagged`: reliable evidence processed in execute mode; its review comments are present, including already-recorded ones.
- `failed`: no reliable result, or a destination/journal failure; never interpreted as deletion.

`affected_existing_actions` counts original actions covered by deletion reviews, not newly created comments. Exit code 0 means all checks completed, 2 means partial failure, and 1 means configuration/setup/report-writing failure. No imported sources yields a complete zero-check result, not evidence about Calendar deletions.

## Verification

68 automated tests pass. The source-review application interface is exercised with the real Google adapter over controlled HTTP responses and the real Linear adapter over a controlled provider. Coverage includes multi-action event deletion, parent-series cancellation, single-occurrence protection, out-of-window retention, ID-only tombstones, HTTP 410 reason distinctions, 404/access failures, partial runs, unchanged user content/status, durable duplicate prevention, lost comment responses, record limits, and private CLI result files.

Live read-only validation on October 27, 2026 checked five imported source records: all five active, no planned comments and no failures. No Calendar data or Linear issues were modified. On October 28, the user accepted automated coverage for this slice and explicitly deferred the live deletion-comment test. No deletion was manufactured to trigger a test.

## Provider references

Google documents that cancelled events are returned by GET, distinguishes recurring exceptions from deleted events, and warns that tombstones are not retained indefinitely: [Calendar event status](https://developers.google.com/workspace/calendar/api/v3/reference/events#status).

Google documents that 404 may indicate missing access and that 410 has several distinct reasons, including invalid sync tokens and deleted resources: [Calendar API errors](https://developers.google.com/workspace/calendar/api/guides/errors). If a tombstone has expired and the provider returns only ambiguous absence, this implementation leaves the source unresolved rather than guessing.
