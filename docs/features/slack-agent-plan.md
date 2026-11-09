# Slack agent implementation plan

Status: slice 1 activated November 8, 2026; private-channel checks, live help/add/search, duplicate cancellation and controlled restart passed. Extended live validation limits are recorded in the runbook. Read the [specification](slack-agent-spec.md) and [initial agent instructions](../agents/slack-agent.md). Implementation is tracked in [GitHub issue #8](https://github.com/randygc/second-brain/issues/8). See the [slice 1 runbook](slack-slice-1.md) for commands, validation and activation.

Deliver four end-to-end slices in this order. Resolve each slice's open decisions from the specification before coding it. Keep common logic behind small interfaces; scripts and agent tools call the same application functions. Avoid a separate infrastructure-only slice or speculative tool framework.

## 1. Slack additions and searches

Outcome: Hermes connects the dedicated private Slack channel to additions/searches in Linear. Explicit commands create Backlog items and search current state without model calls; bounded optional subscription-model interpretation maps free-form messages to the same operations. Results return threaded Linear links.

First run the [Hermes compatibility check](slack-agent-compatibility.md). Hermes owns ingress; use a narrow native Slack plugin/handler and permit no unrelated agent commands/tools. Choose least-privilege app scopes based on verified platform capabilities. Reconcile retained history from saved state; first activation starts fresh. Confirm deterministic commands survive rejected inference before enabling model interpretation. Configure owner/channel/destination explicitly. Add source-neutral creation/provenance and current-state search to the action-store boundary. Persist Slack receipt identity, pending clarification and uncertain creation outcomes; reuse existing reservation/reconciliation guarantees. Ask about possible matches rather than merging separate submissions. Keep later Slack message edits/deletions from mutating Linear.

Acceptance: exercise authorized add → Linear result → search through the application interface, both directly and through bounded interpretation; force quota rejection and verify explicit commands still work; deny unauthorized/channel-mismatched messages; verify retry/restart and ambiguous-write recovery produce one item; verify distinct similar messages ask clarification; cover pagination, partial read failures, unavailable Linear and offline transport recovery. Existing Calendar behavior remains intact. Document setup and deterministic syntax. Any required human app/credential setup follows a concrete prepared implementation.

## 2. Shared deadlines, date queries and reminders

Outcome: clear deadline phrases from supported sources populate due dates through one Python implementation; the owner can query due windows and receive one 08:00 LA digest without a model.

Resolve date grammar, anchors, recurrence, manual overrides, discovery coverage and snoozes first. Make source adapters supply anchor/evidence to the same parser. Extend Calendar discovery as required for moved/new/edited events beyond its current scheduled window; keep ingestion identities and success checkpoint safe. Inspect new/changed Linear entries deterministically and perform a review-only backlog pass. Persist reminder identity and snooze state.

Acceptance: run Calendar and Slack inputs through the same parser and store contract. Cover all verb/separator families, relative anchors, moved events, manual due-date overrides, ambiguity, DST/week boundaries, overdue/closed items, supported direct Linear inputs and uncertain writes. Demonstrate an edit outside the old rolling window is discovered or explicitly narrow rollout scope with the owner. Verify retries do not drift dates or duplicate reminders; downtime yields one current digest. Document queries and remaining unsupported expressions.

## 3. Script failure and recovery delivery

Outcome: runner failures reach Slack even when the model is unavailable, and the next successful operation resolves the alert once.

Add structured failure context at the runner seam and durable notification delivery independent of model execution. Preserve the checkpoint and journal on failed/partial runs. Queue during Slack outages, group repeats and label original timestamps. Define recovery correlation, retry policy and macOS-notification coexistence.

Acceptance: simulate runner/agent-operation failure → queued notification → Slack delivery → later success/recovery. Cover Slack outage, retries/restart, duplicate suppression, startup/config failures, sanitized content and unchanged checkpoint behavior. Document limitations when the host is offline or Python cannot start. Agent-specific execution failures join this path when slice 4 introduces execution.

## 4. One approval-gated research-and-draft workflow

Outcome: natural-language workflow requests and daily triage can propose one bounded workflow; owner approval in the same thread produces research plus a draft and returns the result without automatically completing the Linear item.

Integrate the selected Hermes framework with subscription-authenticated OpenAI/Codex access and no paid fallback. Define learning and selected shared-project-memory policies. Keep Python application functions and durable operational state portable. Enforce read/write tool scope, persist proposals/approvals/cancellation, and expose the existing deterministic scripts as tools. Version the instruction file and define approval expiry. Add up to three useful daily proposals, bundled with reminders; avoid repeat suggestions. Persist model work independently of model availability and reconcile latest Linear state after outages.

Acceptance: proposal → scoped owner approval → bounded tools → artifact/thread result → optional separately authorized Linear update. Cover unauthorized/quoted approvals, cancellation, scope expansion, instruction changes, quota rejection/reset, unknown reset, authentication failure, model recovery announcement and missed-entry catch-up. During all model failures demonstrate additions, deterministic search/date queries, ingestion, reminders and failure delivery still work. Verify skipped closed/superseded items and stale approval handling. Expand workflows only after this path is proven.

## Review and rollout

Use focused application-level behavioral tests and adapter contract checks; avoid tests that merely mirror private implementation. Verify current platform contracts before integration choices. Keep test data synthetic and private credentials outside version control. Use minimal explicitly scoped live checks after offline verification; inspect real operational state before activation. Do not reset the existing journal/checkpoint to bypass errors. Prepare rollback/disable steps that preserve durable state for each slice.

The owner authorized proceeding with slice 1. Remaining human app/token setup and live acceptance are tracked in its runbook; later slices retain their own decision and review steps.
