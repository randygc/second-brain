# Action ingestion ticket plan

Status: approved October 13, 2026 and published in GitHub issues #1–#7. Linear will hold personal actions; GitHub remains the implementation tracker.

Each slice delivers a verifiable path through source access, parsing, output/destination, and application-interface tests. Routine runs use saved deterministic code. No standalone schema/API/UI tickets.

## 1. Repeatable five-day extraction and report

Blocked by: none.

Build reusable code reading one selected Google Calendar with original line fidelity, applying all six accepted cases, and emitting extracted actions/full details/provenance plus daily statistics. A simple local report replaces manual HTML generation; no lifecycle controls. Include zero days, complete pagination, failure reporting, and the accepted recurring-occurrence/event-count convention. Retain available original creation timestamps without inventing them.

## 2. Import one title-defined action into Linear Backlog

Blocked by: 1.

Implement the action-store interface and Linear adapter. From the five-day extraction, explicitly select one title-defined candidate and create its issue in the configured team with Backlog status, original details, and provenance. Establish durable import identity and detect repeat/uncertain creates without duplicates. Verify content in Linear and behavior through the application interface. Do not create every action yet. Settle credentials and destination metadata/state mapping here.

## 3. Import the full five-day action set safely

Blocked by: 2.

Create one issue per independent action, including descriptions with bullets, parentless-content review evidence, and recurring-series actions once. Retain independent identical text, existing Linear edits, and status. Include full five-day statistics and created/already-imported/failed outcomes; report partial runs and resume safely. Repeat runs create nothing extra. Native Linear workflow controls require no custom implementation.

## 4. Import another window and flag changed sources

Blocked by: 3.

Import a newly selected five-day window, adding unseen records while recognizing overlapping events/series. Keep recorded dates, original timestamps, user-managed content, and statuses intact. Detect changed source records and record unresolved review evidence without silently adding/replacing their changed action lines. Verify overlap and change cases in stored Linear issues.

## 5. Retain actions and flag deleted or cancelled sources

Blocked by: 4.

Record unresolved evidence for reliably deleted/cancelled sources while retaining destination issues, user edits, and workflow states. Missing records outside the current window and failed/incomplete reads do not imply deletion. Demonstrate the evidence in Linear; do not automate resolution or delete actions.

## 6. Expand import beyond five days

Blocked by: 4.

Support the original inclusive start-date scope, including future events, with full pagination, bounded recurrence handling, resumable destination writes, deduplication, and accurate reporting. Settle series eligibility and recorded-date selection. Preserve the five-day validation/report mode. Deleted-source detection can land separately through ticket 5.

October 27 production requirement: the first broad import must support an explicit, user-selected start/end range spanning several months. Process bounded batches with durable progress and resume, retaining the same import journal and identities used by five-day imports. Report aggregate and per-day outcomes.

## 7. Scheduled daily ingestion (planned; not yet published)

Blocked by: broad-range import.

After the initial bulk import, run saved ingestion code daily to discover new actions, with safe catch-up after missed or failed runs. Reuse shared parsing, source identity, change review, and the replaceable action store. Define discovery of newly created backdated/future-dated records, checkpoint persistence, execution time/timezone, hosting cost, and credential renewal before enabling the schedule. Do not equate new actions with events scheduled today. No scheduler is enabled by this plan update.

## Published issues

- #2: repeatable five-day extraction/report
- #3: one action into Linear Backlog
- #4: full five-day Linear import
- #5: another window and changed-source flags
- #6: deleted/cancelled sources
- #7: broader import

The October 13 plan was published in the six child issues above. The October 27 broad-range clarification and daily-ingestion follow-on are recorded locally and have not yet been published to GitHub.
