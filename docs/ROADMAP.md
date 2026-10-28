# Second Brain roadmap

## Foundations

- Build small end-to-end slices, then layer feature richness and edge cases.
- Zero recurring service cost unless explicitly approved.
- Use least privilege access; the user accepts Linear Free's limitations only within that integration.
- Design deep modules with small interfaces and reusable deterministic code for routine ingestion.

## Current feature: action ingestion

Google Calendar is the first read-only source. Shared extraction creates portable action items and a replaceable adapter writes to Linear, the initial authoritative action store and lifecycle UI. All new issues start in the configured team's Backlog status; reruns preserve user-managed status and content. Do not build an interactive lifecycle webpage.

The current local [spec](features/action-list-iteration-1-spec.md) and [approved ticket plan](features/action-list-ticket-plan.md) replace the earlier custom-store/UI direction. The approved plan is published in GitHub issues #1–#7.

The six accepted parsing examples and original provenance requirements remain in scope. The accepted sample window is Randy Chevalier basic, September 28–October 2, 2026. A repeatable five-day report comes first; Linear imports follow in narrow slices.

## Production import workflow

Requirement recorded October 27, 2026: perform an initial bulk import spanning a user-selected range of several months, then run scheduled daily imports for newly added actions. Keep the five-day report as a validation tool.

Extend GitHub issue #7's broader-import scope with explicit start/end dates, bounded batches, durable progress, safe resume, and aggregate/per-day outcomes. Bulk and daily runs must share source identities, parsing rules, the action-store adapter, and the persistent import journal so overlaps do not create duplicates or overwrite user edits.

Follow bulk import with a separate daily-ingestion slice. Define how daily runs discover newly created records dated in the past or future, recover missed runs, and retain durable synchronization state before enabling a scheduler. Scanning only today's scheduled events would miss backdated entries. The daily discovery strategy, execution time/timezone, hosting, and credential renewal remain open; preserve minimum cost and least privilege. No scheduled job has been enabled.

## Later iterations

- Complete source-change review/reconciliation using Linear's native editing/deletion workflows. Native editing and deletion supersede the former priority to build custom controls.
- Add a recurring indicator to each action imported from a recurring series.
- Add Slack, email, and eventually audio source connectors; define source-specific selection, permissions, transcription, and additional parsing as needed.
- Research answers to questions, including embedded questions and supporting bullets; define presentation and approval behavior.
- Consider source filtering and explicit combining of related actions; never automatically merge by matching text.
- Replace Linear with Jira or another action store when needed. Implement the new adapter and a separate migration flow preserving provenance, identity, and user-managed state.

## Decisions and open implementation details

See [ADR 0001](adr/0001-replaceable-action-store.md) and [action-store design](features/action-store-design.md). Actual destination workspace/team, credential setup, identity metadata/state storage, and source-change evidence representation remain to be settled during implementation. Vercel and a separate action database are no longer selected architecture directions.
