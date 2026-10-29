# Bounded historical import

`preview` accepts `--end-date` as an inclusive boundary. Omitting it retains the five-day default. Ranges must contain between 1 and 3,660 calendar dates, interpreted in the selected Calendar's timezone. Retrieval completes all Google pages before publishing a successful report. Recurring actions are extracted once per series, dated to its earliest matching occurrence within the requested range; existing journal snapshots keep their initially recorded dates on reimport.

```bash
.venv/bin/python -m second_brain preview \
  --calendar-id YOUR_CALENDAR_ID \
  --start-date 2025-11-13 --end-date 2026-10-28 \
  --token-file .local/google-token.json \
  --output-dir .local/reports/historical-range
```

The JSON report can be validated/planned with `import-batch`. Its validation now checks the complete contiguous date range rather than requiring exactly five dates. Reuse the same destination and journal. The existing import request budget is capped at 1,000 per invocation, so large destination runs can need safe resume; full operational batching and capacity handling still need verification before declaring issue #7 complete.

On October 28, 2026, the requested November 13, 2025–October 28, 2026 extraction completed: 350 dates, 469 matching occurrences, 141 matching source records, and 441 independent extracted actions. Private source data is retained only in the ignored local report. No destination writes were performed for this bulk run: the destination workspace returned no paid subscription, while Linear's published Free plan supports 250 issues. The user must choose sufficient destination capacity or a smaller import scope. No upgrade, charge, truncation, or partial import was authorized as a substitute for the full request.

73 tests pass, including multi-month inclusive boundaries, single-day ranges, invalid ranges, missing daily statistics, recurrence deduplication across the range, and repeated imports through the existing application interface.

References: [Linear pricing](https://linear.app/pricing), [billing and plans](https://linear.app/docs/billing-and-plans), checked October 28, 2026.

## Capacity-constrained first run

The user selected July 1–October 28, 2026 after reviewing Free-plan capacity. A fresh Calendar read returned 172 matching event occurrences, 52 matching source records and 185 extracted actions; 172 actions belong to previously unseen sources. The workspace's prior created-issue count was 18, so the expected post-import total is about 190. Import uses the existing journal, destination and Backlog status, with no subscription upgrade or Calendar writes. Completion and failure counts must be taken from the saved private result after the run, not inferred from these planned numbers.

Nine newly created issues initially failed strict read-back due to provider Markdown rewriting: nested ordered lists flattened, ordered marker changes, indented supporting content became code, adjacent emphasis escaped, and one multiline title was flattened. Original provenance JSON was exact in all nine. The renderer now flattens display-title whitespace while retaining full source text, and uses literal detail blocks for structures the destination rewrites. Each of the nine issues was repaired only after verifying its live title/description/status/team still matched the captured just-created version; no existing user edits were overwritten. All nine were read back successfully. The new regression test checks that literal list hierarchy cannot silently flatten and still pass verification.

Final live reconciliation completed with zero creates, 179 already-imported current actions, six current action slots held from one previously changed source, and zero failures. Three original actions in that source warrant review; unchanged siblings produce no new comments. Across the first run and guarded repairs, 172 new issues were created and verified. The journal has 186 confirmed imported actions, retaining the original action that became a bullet, and the workspace reports 190 created issues overall. Existing Linear content/status was preserved. No Calendar events were modified.
