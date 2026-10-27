# Replaceable action store

## Accepted scope

Linear initially owns stored actions and their user-managed workflow. Do not build an interactive action-lifecycle webpage. The existing five-day HTML snapshot is a parsing review artifact, not a production workflow interface.

Google Calendar remains the first read-only input. Slack, email, and audio remain future input sources. Shared extraction produces provider-independent action items; an action-store adapter writes them to Linear. Jira is a future replacement candidate, not an additional implementation in the first slice.

All newly imported issues start in the selected team's Backlog status. Resolve its provider identifier through configuration; preserve user-managed status on subsequent imports. A dedicated Personal Actions team is recommended, but the actual workspace/team is not selected yet.

## Interface design direction

- Keep action text, supporting details, original source content, source identity, original creation timestamp, scheduled date, and review evidence in a portable domain representation.
- Keep an application-owned import identity separate from the destination issue ID. Identical content from independent source records remains independent. Linear team IDs, issue IDs, workflow states, labels, and GraphQL types stay inside the adapter/configuration.
- Design the smallest interface needed for importing new actions, recognizing prior imports, and recording source-change evidence while preserving user-managed text and workflow. Exact operations and persistence mechanics require implementation validation.
- Put authentication, provider field mapping, pagination, request budgets, retry behavior, and uncertain-write reconciliation inside the adapter. An ambiguous create response must not trigger blind retries that produce duplicate issues.
- Preserve original source creation timestamps as provenance; the destination issue creation date is a different timestamp.
- Keep ingestion identity/mapping state distinct from the authoritative user-managed action. Determine whether portable metadata in Linear is sufficient before introducing a separate synchronization datastore.
- Test ingestion through its application interface with controlled source inputs and a test action-store adapter. Contract checks verify the Linear adapter without exposing provider details to parsing tests. Do not implement a speculative Jira adapter yet.
- Replacing the adapter supports new imports; moving existing actions and user-managed state needs a separate migration flow. Preserve provenance and import identities so migration remains feasible.

## Current limits relevant to implementation

Verified against official Linear documentation on October 13, 2026:

- Free: two teams and 250 issues; API/webhook access is listed. Do not assume which archived/deleted items count without checking before capacity handling is implemented. [Pricing](https://linear.app/pricing)
- API-key requests: 2,500 per user per hour, shared across that user's keys. OAuth applications: 5,000 per user/app user per hour. Query complexity and endpoint-specific budgets also apply; use returned limits rather than embedding a permanent quota. [Rate limiting](https://linear.app/developers/rate-limiting)
- Personal API keys support specific permissions and optional team scoping. Actual workspace capabilities must be checked during setup. The user accepts Free-plan least-privilege limitations; use available restrictions. [Security & Access](https://linear.app/docs/security-and-access)

## Planning impact

The local spec and approved ticket plan have been rewritten around Linear ingestion and published in GitHub issues #1–#7. GitHub remains the project implementation issue tracker; Linear is the destination for personal actions.

Use saved deterministic connector/parser/ingestion code for routine operation. The earlier HTML generation was one-off session code, not a reusable parser or renderer.
