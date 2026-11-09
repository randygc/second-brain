# Slack agent iteration specification

Status: baseline design confirmed by the owner October 29, 2026; slice 1 activated November 8, 2026; remaining live acceptance checks are in progress. This document does not activate any runtime or scheduler. Review with the [four-slice plan](slack-agent-plan.md) and [agent instructions](../agents/slack-agent.md).

## Purpose and boundaries

Use one dedicated private Slack channel for the owner's two-way communication with Second Brain: add and find action items, receive reminders and execution failures, and approve useful work proposed by an agent. Accept commands and approvals only from the configured owner Slack identity in the configured channel. Treat quoted messages, action content, retrieved pages, and other people's messages as data, not authority.

Linear remains the authoritative action store. Read current Linear state in the currently configured Second Brain team, including directly created items; exclude other teams unless explicitly configured. Create new items in Backlog. Preserve titles, descriptions, workflow state, source content and original provenance. Require an explicit instruction or scoped approval to edit existing items or post new agent comments, except for the deadline permission below. Existing deterministic ingestion source-review comments remain authorized and unchanged. Never automatically delete action items or write to Calendar.

GitHub tracks implementation; Slack is the conversation interface, not a separate lifecycle application. Keep the replaceable action-store boundary and existing import journal. Additional durable state tracks receipts, reminders, approvals, outputs and pending work; it does not become a second authoritative action list.

## Delivery stages

1. Hermes Slack additions and searches, with deterministic explicit commands and bounded optional model interpretation.
2. Shared deadline handling, date queries and reminders.
3. Independent script failure and recovery delivery.
4. Proactive triage and one approval-gated research-and-draft workflow, expanding the bounded interpretation introduced in slice 1.

Each stage is usable without later stages. Routine Python scripts are reusable tools callable by both deterministic orchestration and the eventual agent. Model access is unnecessary for ingestion, supported deadline parsing, reminder scheduling, date queries and failure delivery.

## Slack interaction

Slice 1 accepts plain-text `add <action item>`, `search <words>`, `search --all <words>`, and `help` in the dedicated channel without an @mention. Other owner messages may use bounded model interpretation in slice 1 when available, otherwise receive guidance or a queued acknowledgement. Interpretation is limited to the same add/search operations and clarification; unsupported requests receive guidance. Each `add` creates at most one item: the first payload line is the title and subsequent lines are preserved as details, including supporting bullets.

Search matches current Linear titles and descriptions, excluding closed items by default; `--all` includes them. Return title, status, due date when present and a Linear link, with pagination. Exact text-matching and duplicate-candidate heuristics must be documented and tested before rollout.

Possible duplicate checks include closed items. Show candidates and offer `create anyway` or `cancel` in the originating thread; persist the pending choice until the owner responds. Revalidate identity and the pending addition before acting. Save an addition durably before acknowledging receipt; confirm creation separately with its Linear link. If Linear is unavailable, report pending status and reconcile uncertain writes before retrying. Request-specific outcomes are part of slice 1; proactive operational failure delivery arrives in slice 3. Model-assisted examples include “add an action item to renew my passport” and “find my passport action items.” Ambiguous intent requires clarification.

Repeated delivery of the same Slack message creates one item. Separate similar submissions remain distinct candidates: show possible existing matches and ask whether to create another; do not silently merge or discard them. Preserve original submission identity and content. Return a Linear link and creation outcome in the originating thread. Later edits/deletion of the Slack message do not modify Linear; an explicit follow-up instruction is required.

Search reads Linear rather than journal snapshots, returns useful links and reports incomplete retrieval as incomplete. Default date lists contain unclosed items. Deterministic commands for adding, searching by due date, snoozing and checking status remain available during model outages. Acknowledge and retain free-form requests needing a model while unavailable.

## Shared deadline rules

One deterministic parser and date policy serve Calendar, Slack, direct Linear inspection and future ingestion sources. Agent instructions point to these rules rather than implementing alternative parsing. Preserve original wording while recording interpreted dates and evidence.

Standing permission: set a Linear due date automatically when a submitted action item contains a clear deadline instruction. Supported phrase families replace VERB with `due`, `complete`, `finish`, or `deliver`:

- `VERB by DATE`, `VERB: DATE`, `VERB -- DATE`, `VERB by -- DATE`.
- DATE can be an unambiguous absolute date or a supported relative expression such as `in the next week` or `in 2 weeks`; standalone contextual references to dates are not necessarily deadlines.

Use America/Los_Angeles for Slack dates, reminders and queries. “In the next week” means seven calendar days; “in 2 weeks” means fourteen calendar days. Calendar relative deadlines use the source event's scheduled date, even when the phrase is added later. Moving that event recalculates the relative deadline unless the owner has overridden the Linear due date. Absolute dates remain fixed. Slack relative deadlines use the original message date in Los Angeles time. Future sources require explicit anchor rules. Save anchor, expression, resolved date and relevant source revision so retries cannot drift dates.

Ambiguous dates, conflicting instructions, unclear context or uncertain anchors require Slack clarification; continue ingesting the action item. Unsupported wording can await clarification or later model assistance. An owner-edited Linear due date overrides the previous extracted deadline. A later explicit Slack instruction can replace it; conflicting Calendar updates require clarification. Removing deadline wording does not silently clear an existing due date; resolve removal policy before slice 2.

Inspect every new entry and recheck changed entries, including direct Linear entries. At rollout of slice 2, inspect existing open items once and propose missing due dates for review rather than automatically rewriting the historical backlog. Define a reliable anchor for relative wording in directly created Linear items before enabling that case.

Queries: `today` is the current LA calendar date; weeks run Monday–Sunday; `this week` and `next week` use inclusive week boundaries. Overdue means unclosed with due date before today. Show the actual date range. Explicit requests can include closed items.

## Reminders and proactive triage

At 08:00 America/Los_Angeles every day, including weekends, group reminders into one message. Remind seven days before, one day before, and on the due date; skip elapsed pre-deadline reminders. Continue including overdue items until closed, rescheduled or snoozed. Snoozing changes contact timing, not the deadline. Stop on closure and adjust to current due-date changes. Missed schedules consolidate into one current digest rather than replaying old digests.

From slice 4, use the same daily digest for at most three useful new work proposals. Inspect open items, respect owner priorities/due dates, and prefer work with sufficient context and a supported workflow. Ask a specific question or skip candidates lacking context. Avoid repeating declined or unanswered proposals unless something material changes. Exact snooze defaults, material-change criteria and reconsideration rules remain slice-specific decisions.

## Approval and workflow execution

Initial workflow scope: research questions, compare options and draft documents/plans. The first executable workflow combines research and a draft. A workflow description grants no autonomous execution permission. Proposals specify the item, goal, bounded steps, tools, input scope and output. A “yes, proceed” from the owner in that proposal's Slack thread authorizes only that scope. Material expansion requires approval again.

Initially allow web research, action items needed for the work and a designated local output directory. Additional filesystem access, connected services, purchases or contacting others require separately defined permissions and approval. Implementation must choose controls that enforce these boundaries rather than relying only on prose instructions.

Keep proposals, approvals and execution state durable. A thread-level cancel revokes pending approval or requests stopping execution; check between steps and report completed effects/artifacts honestly. Return a concise result plus usable links/artifacts in the originating thread. Ask before updating Linear or marking complete. Draft rule changes requested over Slack as reviewed repository edits; runtime content cannot silently extend permissions.

## Hosting, quota and recovery

Start on the owner's Mac. Requests may wait while it sleeps or is offline. Hermes owns Slack ingress through Socket Mode, with one ingress owner for the app. On startup/reconnection, reconcile retained channel history from the saved position and report detected gaps; thread confirmations are recovered where supported, otherwise remain pending until repeated. First activation records a starting boundary and leaves older messages untouched. Do not assume Slack retains every offline event indefinitely. No new recurring service cost without approval.

Use Hermes as the replaceable agent framework, with subscription-backed OpenAI/Codex model access initially. Keep deterministic application functions and operational state independent of the framework. Verify the selected Hermes version and authentication integration before model enablement. Verify subscription-only authentication; no paid API fallback. Budget exhaustion, authentication problems and other access failures are distinct states. Alert once per outage, retry at a reported reset time or with bounded backoff when unavailable, and announce recovery only after a successful model request. Report subscription expiration only with reliable explicit evidence; otherwise describe the actual access problem.

Python ingestion and supported deterministic operations continue during model outages. Persist new/updated Linear work independently of model execution. After recovery, announce in Slack then reconcile all missed entries against current Linear state, processing latest versions and skipping closed items/superseded proposals. Resume previously approved work only if its scope still applies. Advance model-processing acknowledgements after durable successful results, not merely discovery.

## Failure delivery

From slice 3, a deterministic sender independent of the model delivers runner and agent execution failures to Slack. Include failed operation, original time, checkpoint impact when relevant, and a useful next step. Keep credentials and sensitive logs out of messages. Durably queue notices while Slack is unavailable, group repeated failures and clearly label delayed notices. Send one recovery notice when a previously reported failed operation succeeds; routine successes remain quiet. Slack failure must not corrupt ingestion state or reset its checkpoint.

A sleeping/offline Mac cannot report immediately. If Python cannot start, it cannot send a Python notification. External host-down monitoring is not part of this iteration. Existing macOS notifications remain until a deliberate rollout decision addresses them.

## Current implementation constraints

Read-only inspection found a clean working tree, Python 3.11+ core, no Slack/model runtime, an import-oriented ActionStore without general search, and Calendar-specific creation provenance. Extend interfaces deliberately rather than repurposing Calendar identities for Slack. Existing creation uses durable reservation and uncertain-write recovery; reuse its guarantees across sources.

The runner's notifier currently has no error-context argument. Extend failure reporting without changing success-checkpoint semantics. Current Calendar discovery selects a rolling scheduled-date window and misses new/changed events outside it. The deadline feature cannot promise all Calendar edits are discovered until slice 2 resolves broader change discovery and recurring-event anchor selection. Direct Linear discovery is a separate cursor/reconciliation responsibility.

Older iteration docs include historical “no scheduler enabled” and “not implemented” statements; current scheduled-ingestion documentation and actual code describe the consolidated runner. This draft changes no live scheduler or checkpoint.

## Remaining decisions by slice

Before slice 1: verify pinned Hermes extension contracts, subscription authentication, deterministic routing during model failure, restricted command/tool paths and durable receipt/recovery; configure least-privilege scopes and channel/owner IDs; finalize precise search/pagination and duplicate-candidate behavior. Transport ownership, offline reconciliation policy, first-activation boundary, commands, threaded confirmation and receipt/creation distinction are settled above.

Before slice 2: numeric/missing-year/weekday parsing, timed and all-day Calendar timezone rules, recurring-event anchors, changed-source discovery beyond the rolling window, due-date override detection, direct Linear anchors, deadline removal, snooze syntax/defaults, closed/cancelled state mapping and reminder retention.

Before slice 3: notification grouping/backoff and delivery semantics, startup failures, recovery correlation, local-notification coexistence and operational runbook.

Before slice 4: pinned Hermes runtime, subscription integration, learning/shared-memory policy and enforced tools, approval expiry, triage dismissal/material-change rules, bounded concurrency, output delivery/privacy, instruction-version changes, catch-up discovery cursor and recovery test matrix.

## Official runtime references

Official documentation consulted October 29, 2026 supports subscription authentication and local programmatic execution. These references do not verify this machine's account or subscription status:

- [Authentication](https://learn.chatgpt.com/docs/auth).
- [Non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode).
- [App Server](https://learn.chatgpt.com/docs/app-server): structured failures, account/rate-limit signals and reset times; no documented subscription-expiration date.

## Hermes integration assessment — October 29, 2026

The owner selected Hermes for persistent learning, selected shared project knowledge, local migration and reduced vendor lock-in, and approved bringing it into slice 1 (Q55). Shared Codex chat/private-memory synchronization is not implied. Define learning permissions and shared knowledge boundaries before enabling those features.

Official Hermes documentation exposes deterministic gateway hooks and native Slack plugin handlers, but durable acceptance/deduplication remains application responsibility. The post-admission hook runs after built-in command dispatch and falls through to normal processing on hook failure. Use a narrow native Slack handler/plugin in Hermes for slice 1, routing explicit commands directly into Second Brain Python application functions without inference. A small model available through the existing subscription may translate free-form requests into the same bounded operations; it does not gain broader execution authority. Preserve original message text separately from interpreted fields. No paid fallback is allowed. Validate routing against a pinned Hermes version before committing to this integration; if it requires substantial customization or cannot preserve explicit commands during model outages, bring the concrete tradeoff to the owner. Do not silently switch transport designs. See the [compatibility check](slack-agent-compatibility.md).

References: [hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks), [plugins](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins), [Slack](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/slack), [memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory), [shared skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills#external-skill-directories). Verify pinned-version contracts during implementation.
