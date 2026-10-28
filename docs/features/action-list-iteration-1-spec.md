## Problem Statement

Personal actions are embedded in Google Calendar events. Manually extracting them and maintaining a separate action list adds work and can lose context. The owner wants repeatable, inexpensive ingestion with a destination that can change as the system grows.

## Solution

Build reusable source connectors and mostly shared parsing rules that import independent action items into Linear. Linear is the initial authoritative action store and the interface for reviewing, editing, completing, cancelling, and otherwise managing actions. Use a replaceable action-store adapter so a future Jira or other destination can reuse the ingestion logic. Do not build an interactive lifecycle webpage.

Deliver small end-to-end slices, starting with repeatable five-day extraction, followed by a narrow Linear import. Google Calendar is the only initial production input; Slack, email, and audio are future sources.

## User Stories

1. As the owner, I want a read-only connection to one selected Google Calendar, so that my events remain unchanged.
2. As the owner, I want to specify a start date and inspect five calendar days, so that I can validate a small import.
3. As the owner, I want calendar-timezone date boundaries, so that scheduled dates are interpreted consistently.
4. As the owner, I want Action or Actions matched case-insensitively as the first title word, so that irrelevant events are excluded.
5. As the owner, I want title-defined actions extracted without the marker and separator, so that their titles are usable.
6. As the owner, I want a title-defined action to retain the entire event description as details, so that its context survives.
7. As the owner, I want marker-only descriptions split on original non-bullet action lines, so that independent responsibilities remain independent.
8. As the owner, I want visual wrapping ignored, so that display width does not change action boundaries.
9. As the owner, I want sentences within one source line retained together, so that prose is not split arbitrarily.
10. As the owner, I want supporting bullets and indented lines retained with their parent action, so that steps and nuances survive.
11. As the owner, I want leading double dashes treated as bullets, so that my existing writing convention works.
12. As the owner, I want links, formatting, questions, and original wording retained, so that extraction preserves intent.
13. As the owner, I want parentless bullet content retained as one flagged item, so that ambiguous content is not lost.
14. As the owner, I want daily matching-event and extracted-item counts including empty days, so that I can check ingestion completeness.
15. As the owner, I want recurring occurrences counted as events but their actions extracted once per series, so that statistics and actions serve their different purposes.
16. As the owner, I want one Linear issue per independent action, so that Linear manages my workflow.
17. As the owner, I want newly imported issues in Backlog, so that I can review them before starting work.
18. As the owner, I want original source content, source type, source identity, original creation timestamp, and scheduled date recorded, so that provenance remains accessible.
19. As the owner, I want identical actions from independent events or sources retained separately, so that matching text does not erase responsibilities.
20. As the owner, I want repeat imports and overlapping date windows to avoid duplicates, so that ingestion is safe to rerun.
21. As the owner, I want my Linear edits and workflow status preserved, so that import does not undo my work.
22. As the owner, I want source changes flagged without replacing recorded actions, so that I can review discrepancies.
23. As the owner, I want actions retained when sources are deleted or cancelled, so that source removal does not erase responsibilities.
24. As the owner, I want failures and partial imports reported accurately, so that an incomplete operation is not presented as success.
25. As the owner, I want broader import from a start date later, so that the five-day validation can grow into my full action list.
26. As the owner, I want a replaceable destination adapter, so that moving to Jira or another store does not require changing parsing.
27. As the owner, I want deterministic code for routine ingestion, so that each run does not require regenerating code or spending agent tokens.
28. As the owner, I want zero recurring service cost unless I approve otherwise, so that the system stays inexpensive.

## Implementation Decisions

- Use deep modules with small interfaces: source connectors, shared extraction, ingestion orchestration, and an action-store seam. Linear is the first production action-store adapter; a controlled test adapter provides a second implementation. Do not implement Jira speculatively.
- Linear owns action content and user-managed workflow. GitHub remains the implementation issue tracker. Team/workspace selection is configuration, not a parser concern; a dedicated Personal Actions team is recommended but has not been selected or created.
- Resolve the selected team's Backlog status explicitly for new issues. Existing issues never reset to Backlog on reimport. Workflow labels and provider status identifiers remain adapter details.
- The first repeatable preview searches the specified start date plus four subsequent calendar dates in the calendar timezone. The accepted sample is Randy Chevalier basic, September 28–October 2, 2026; runtime configuration can choose another start date.
- Match Action or Actions as the first word, case-insensitively, followed by optional punctuation or text. Exclude Action123, Actionable ideas, and titles with preceding text.
- For title-defined actions, remove the leading marker and separator and retain the full description as details. For marker-only events, each explicit nonblank, non-bullet, unindented source line starts an action; supporting bullet/indented lines attach to the preceding item. Blank lines do not break associations.
- Preserve actual source carriage-return/newline boundaries before content conversion. Visual wrapping is not a delimiter. Leading --, including after indentation, is a bullet; inline -- is not. Preserve wording, links, formatting, and full source content. Parentless bullets retain the entire description as one flagged item.
- For the five-day window, count matching recurring occurrences in each day's event count; extract each independent action once per series and attribute action counts and displayed scheduled dates to the earliest matching occurrence in that window.
- Keep portable source provenance and application-owned import identity independent of destination issue IDs and action text. Every item records original creation time, unchanged after edits, separately from modification time, scheduled date, and destination issue creation time. Source links are optional.
- Repeated imports recognize previously imported actions by source record/series identity and the stable identity of each initially extracted action. Do not match by text or recompute identity from changed content. The precise multi-item identity representation is an implementation decision.
- New source records can create issues. Changed imported records retain recorded actions and user edits and generate review evidence. Deleted/cancelled sources retain destination issues and workflow state. Initially flags remain unresolved; automated reconciliation remains deferred even though Linear offers native editing/deletion.
- The adapter isolates provider fields, destination configuration, authentication, pagination, budgets, errors, and uncertain-write reconciliation. An ambiguous create response must not lead to blind retries and duplicate issues. Partial runs remain resumable through recorded identities and outcomes.
- Determine whether portable destination metadata can support import identity and source snapshots before adding a separate synchronization store. Any such state is ingestion bookkeeping, not a second authoritative action database.
- Use available least privilege controls. The user accepts Linear Free's access limitations; do not extend that exception to Google Calendar or unrelated systems. No paid services without approval.
- Reusable preview/report code may render a static local artifact and statistics. It is not a lifecycle UI. The earlier HTML snapshot was manually generated and corrected, not a verified reusable parser.

## Testing Decisions

- Accepted revised primary seam: exercise ingestion through the same application interface used by routine runs, with controlled source inputs and a test action-store adapter. Assert extracted actions, destination write outcomes, provenance, identity, review evidence, and preserved user-managed fields rather than private implementation details.
- Preserve historical examples 1–6: expected item counts are 1, 1, 3, 1, 8, and 7. Example 6 has four double-dash bullets on its research-list item; annotation asterisks are not production delimiters.
- Verify source line fidelity through the actual Google Calendar adapter, including adjacent action lines and wrapped long lines. The chat connector snapshot alone cannot establish original line boundaries.
- Cover five-day/timezone boundaries, empty-day statistics, recurrence attribution, pagination, independent identical content, overlapping windows, unchanged original creation timestamps, and repeat import.
- Contract-check the Linear adapter's actual issue creation, configured team, Backlog state, provenance rendering, identity lookup, and error handling with minimal approved test writes. Do not test Linear's own lifecycle UI implementation.
- Verify reruns preserve user-edited titles/details and status; source changes produce evidence without overwrites. Test failed/incomplete source reads do not imply deletion, and ambiguous destination writes do not duplicate issues.
- No production implementation or test framework exists yet. The user approved the ingestion-focused testing seam and revised ticket plan on October 13, 2026.

## Out of Scope

- Custom interactive lifecycle webpage, custom completion/edit/delete/reopen controls, and a separate authoritative action database.
- Additional production source connectors, Jira implementation, or destination migration in the first slices.
- Automatic cross-source merging, research assistance, prioritization, reminders, and scheduled ingestion.
- Automatic review resolution, recurring labels, Google Sheets interfaces, and project grouping.
- Overwriting user-managed Linear text/status, modifying Calendar events, or executing instructions contained in source content.

## Further Notes

- The revised Linear-ingestion spec and six-slice plan were approved on October 13, 2026 and supersede the custom lifecycle UI direction.
- Before Linear writes: select the actual workspace/team, credentials, metadata mapping, and identity/state strategy. Do not create a team or infer a destination silently.
- Persistent recurrence date selection across overlapping windows and broader start-date imports remains to be designed. A rerun must not overwrite the initially recorded date merely because a different occurrence is returned.
- Handling unavailable original timestamps, removed/reordered actions in changed records, destination deletion, and review evidence representation require explicit implementation decisions. Broader retrieval must avoid expanding infinite recurrence forever.
- Linear's current free limits and API restrictions are summarized in the action-store design notes; verify current capacity and respect returned API budgets during implementation.
- Native Linear editing/deletion replaces the former iteration-2 custom-control priority. Completing automated source-change reconciliation remains future work.

## Source-change comment refinement — October 27, 2026

Present updated extracted action names and formatted descriptions directly in action-specific review comments, with the source update timestamp. If a former independent action no longer has a corresponding action because it was removed or became supporting content, explain these possibilities and suggest manual deletion. Preserve the issue and its user-managed fields. Do not infer correspondence from shifted action ordinals; uncertain matches require review without a deletion recommendation. Keep source snapshots in private import evidence rather than displaying raw JSON in review comments.

A changed Calendar event must not produce change comments on unchanged sibling actions. Compare each confidently matched original extracted name/details/review flags with the updated extraction before commenting; source-level formatting, action reorder, and changed action counts alone do not make every action changed. Previously posted review history is retained.
