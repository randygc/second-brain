# Slice 1: Slack additions and current Linear searches

Implementation tracked in [issue #8](https://github.com/randygc/second-brain/issues/8). Code is **active** in the configured private Slack channel. Workspace, private-channel/bot/owner membership and effective deny defaults passed verification. Live help, add → Linear → search, possible-match cancellation and a controlled gateway restart passed. Exactly one verification item was created; six receipts remained complete with no pending replies across restart. The existing Calendar scheduler, credentials, journal and checkpoint were preserved.

## Use after activation

Post plain text in the configured private channel, from the configured owner:

```text
add Renew my passport
- Check expiration date
- Find a photo appointment

search passport
search --all passport
help
```

Each `add` is one action item; its first payload line is the title and following lines are preserved as details. Original Slack text, timestamp, owner/channel identity and source link remain in portable provenance. Long titles retain their full text in the description. Items start in the configured team's Backlog. Editing/deleting the Slack source leaves Linear unchanged.

Search re-reads every page of the configured Linear team. It matches each case-folded search word as a substring of title or action details, excluding the generated provenance section. Default results exclude completed, canceled and archived items; `--all` includes them. Results sort by identifier, show five per page, with title, status, existing due date and link. Reply `next` in that search thread. Each page refreshes Linear, so intervening edits can move results between pages. Retrieval failures produce a pending response rather than an empty or partial result. Start separate top-level messages for separate searches.

Before creating, the application checks all team titles, including closed/archived items. It warns on equal normalized titles, a `SequenceMatcher` similarity of at least 0.80, or at least two shared words covering 80% of the shorter title. This heuristic deliberately asks rather than merging. Reply `create anyway` or `cancel` in the original thread. Pending choices survive restart. Resolve one pending addition before adding another in the same thread, or start a new top-level message.

Optional subscription interpretation accepts direct natural-language add/search requests through `cliproxy/gpt-6-luna`. A bounded classification call returns only an add/search/clarify shape; it receives no tools, Linear results or execution privileges. Unsupported or ambiguous requests receive command guidance. Explicit commands bypass inference. Model access failures retain natural-language requests, probe at most once per 15 minutes, announce successful recovery, then resume saved requests. There is no paid fallback. Deadline extraction, date queries, reminders, proactive failure monitoring and research workflows remain later slices.

## Prepare the Slack app

The owner must create/install the app in their chosen Slack workspace and supply its tokens. The local wizard is `/Users/randychevalier/Second_brain/.local/slack-setup.sh`:

```sh
bash /Users/randychevalier/Second_brain/.local/slack-setup.sh
```

It opens the relevant pages, copies the prepared manifest, and captures values privately in `.local/slack-setup.env` (mode 0600). Three stages:

1. Create an app from `integrations/hermes/slack-app-manifest.json`; install it; capture the bot token.
2. Under Basic Information → App-Level Tokens, generate a token with `connections:write`; capture it.
3. Choose/create a private channel (suggested `#second-brain`), invite the bot, and capture the workspace, channel and owner member IDs.

The [manifest workflow](https://docs.slack.dev/app-manifests/configuring-apps-with-app-manifests/) and [Socket Mode scope](https://docs.slack.dev/reference/scopes/connections.write/) are documented by Slack. Bot scopes are limited to `chat:write`, `groups:read`, `groups:history`; only `message.groups` is subscribed. There are no DM scopes, slash commands, public-channel subscriptions or second Socket Mode consumer. Return to Codex after capture; never paste tokens into chat.

## Deployment

`tools/slack/deploy-hermes.ts` uses the existing stack's OrbStack and block-aware configuration wrappers. It verifies the pinned Hermes revision, stages/compiles code, and has a separate activation path:

```sh
bun tools/slack/deploy-hermes.ts stage
# After private setup values exist, operator runs:
bun tools/slack/deploy-hermes.ts activate
```

Activation verifies the bot's workspace and private-channel membership, owner membership and the single subscription-only model route. It backs up the stack environment under the stack repository's `_bak/slack-*`, writes source selections/tokens to `.stack/.env`, generates the local profile and enables declared dependencies through Hermes's plugin manager. It installs a systemd environment drop-in and restarts the gateway. It refuses to overwrite an existing plugin directory; partial installations/upgrades require inspection rather than blind retries. The initial activation timestamp is retained in stack configuration; old channel history is not ingested. A rerun must retain that timestamp and both journals.

Hermes remains the only Slack ingress owner. The plugin installs global Bolt middleware before loading configuration, handles authorized receipts, and terminates all dispatch paths without calling core listeners. Core fallback user allowlists contain a non-user sentinel, allow-all flags are false, DMs and bot/reaction handling are disabled. These are defense in depth; complete Hermes startup and effective authorization settings must be checked after activation. The plugin registers no ordinary Hermes agent tools. The dashboard remains available independently.

Source configuration lives in the stack's `.stack/.env`, existing Calendar destination configuration, and its existing Linear key file. Copies under the generated Hermes plugin directory are derived runtime data. Changes to stack Slack selections/keys require regeneration/review; ordinary stack build is not a plugin deployment. The capture file is temporary private setup input, not an additional runtime source.

## State, recovery and portability

The portable Python application is `second_brain.slack_commands.SlackCommands`; the Hermes adapter and `python -m second_brain.slack_cli` use it. The owner-only Slack receipt/outbox database and Slack import reservation journal live on the VM's native filesystem at `/opt/hermes-runtime/second-brain-slack/state`. The application reuses `LinearActionStore` and its reserved-UUID reconciliation, with source-neutral provenance. Calendar's existing host journal remains in place; Slack uses its own source-specific journal rather than concurrent cross-OS SQLite writes on the Mac shared mount. Linear remains authoritative for action content/status.

Receipts deduplicate by workspace/channel/message timestamp, covering both event replay and history catch-up. Store before application acknowledgement; confirm creation separately after reconciliation. A durable creation phase ensures a timeout/restart goes straight to the same reservation instead of asking about the item it just created. If a prior create might have been sent but the reserved issue is absent, the importer refuses a replacement. Preserve the reservation for operator investigation. Unexpected application failures are held for review; safe destination failures remain pending.

A single worker lock protects command processing. Slack delivery uses a durable outbox, with stable message IDs and no mention/unfurl parsing. A lost Slack response can still produce a repeated **notification**; it cannot create another Linear issue. Do not claim exactly-once Slack delivery.

Every minute, retained channel history is paginated from a saved cursor. Advance only after all pages are saved; partial failures replay safely. History outages do not disable live explicit commands. Pending duplicate-choice threads are queried for retained replies; an actual permission/API failure asks the owner once per gateway boot to repeat `create anyway` or `cancel`. The [Slack replies API](https://docs.slack.dev/reference/methods/conversations.replies/) and real token permissions determine availability. History retention limits signaled by Slack produce a resubmission notice. Deleted/expired messages cannot be recovered or always detected.

For reliable offline ingestion, submit new add/search requests as top-level messages. Offline thread recovery in this slice covers pending duplicate choices; other offline thread replies, especially on roots before activation, may require resubmission. Repeat an offline `next` after reconnecting. No source edit/delete changes an accepted receipt.

Once per minute during normal transport operation, backups acquire the same lock as command processing (and defer while a CLI worker is active), snapshot both journals into a complete generation, then atomically publish `current.json` in `/home/hermes/.hermes/second-brain-slack-backup`, which is in the existing Mac-backed Hermes home and stack backup scope. The manifest selects a `generation-*` directory containing both journals; retain the current and previous complete generations. Old root-level snapshots from before this fix are historical and must not be combined with a generation. These are portable operational recovery snapshots, not authoritative action content. Do not destroy/recreate the VM without a current backup of both journals, runtime configuration and source selections. Stop the gateway before a reviewed restore; preserve the live files, resolve `current.json` once, restore both journals from that one generation with their original policy/activation identity, then reconcile reserved Linear UUIDs. Never initialize a fresh journal to bypass an uncertain write.

The CLI accepts `--config /absolute/path/runtime.json` plus `check`, `receive` (Slack envelope on stdin), `work` or `status`. `check` is offline; `status` prints counts only. `work` can create authorized pending additions and must use the same configured journals as Hermes. Do not run ad-hoc creation against a new state directory.

## Validation and live acceptance

Offline verification: `python3 -m unittest discover -s tests -q`. The production middleware probe is `tools/compatibility/probe_slack_plugin.py`; run it in the pinned isolated Bolt environment after staging. It imports the actual production plugin and durable command application, uses real Bolt dispatch with core listeners installed first, and blocks network calls. The older exploratory probe establishes the pinned Hermes registration contract.

Verified before activation: 117 application/regression tests; native Hermes plugin manifest/isolated-registration/security validation; production plugin dispatch and failure-closed checks; synthetic quota rejection with explicit commands still succeeding; replay/restart, duplicate choice, uncertain Linear mutation reconciliation, current-state pagination, partial read failures, retained-history recovery and pending reply fallback. A read-only live Linear contract check fetched 207 team items. Two synthetic intent requests through the existing subscription gateway returned add/search classifications; neither created a Linear item. The full live gateway/Slack path is still unverified.

After credentials and activation:

1. Verify gateway active, plugin loaded, correct pinned dependencies, owner/channel checks, core sentinel allowlists and no broad grants/pairings. Send `help` and confirm one threaded response.
2. Submit a clearly labeled owner-approved smoke-test addition with a supporting bullet. Verify a single Backlog issue, exact details/provenance and its returned link; find it via `search` and check `--all` against a closed item.
3. Submit a similar item; cancel it. Repeat and authorize `create anyway` only if a second smoke-test item is wanted. Verify an unauthorized user/other channel/DM cannot create or trigger the core agent.
4. Restart once while a receipt/choice is pending, verify history replay and outbox recovery, and test a repeat confirmation if retained thread permission is unavailable. Test `next` on a multi-page search.
5. Temporarily reject interpretation at the application seam; verify direct commands still work and a saved natural-language request resumes on successful access. Restore the original configuration. Do not exhaust the real subscription as a test.

Leave this issue open until those checks pass. The operator may archive/close smoke-test items only with owner authorization; the plugin has no delete or completion capability.

## Disable

Stop the gateway before changing plugin selection. Remove/disable the Slack token environment drop-in or Slack ingress, retain deny defaults, and disable the plugin through Hermes. Keep both journals, original activation timestamp, generated configuration and private backups. Do not disable only the middleware while leaving a broadly authorized native bot active. Dashboard/Calendar operation does not require this plugin.

## Activation record — November 8, 2026

The initial channel was public; Slack correctly required `channels:read`, which the restricted app does not have. The owner supplied a private channel instead. Workspace, bot/owner membership, private-channel status and the subscription-only route passed preflight, then the plugin was enabled through Hermes PM and the gateway restarted. No public-channel scope was added.

The running process has the configured channel, core sentinel user allowlists, allow-all false and DMs disabled. Live owner help delivered both acknowledgement and response. One owner-approved verification addition reached Linear and returned a confirmed link; a plain-text search returned that item. A second similar addition produced a possible-match question, and the owner's cancellation was delivered without creating a second issue. A controlled restart retained all six completed receipts, one confirmed import, zero undelivered replies, and completed a new history reconciliation. A read-only `conversations.replies` check confirmed that the real bot can retrieve the owner's cancellation from the retained private-channel thread. Generated credentials/configuration and the receipt backup have mode 0600.

One search pasted with surrounding backticks returned clarification; resubmitting the plain text command succeeded. Submit deterministic commands without code/quote wrappers.

Automated quota rejection/recovery, pagination, closed filtering, unauthorized identity/DM/channel dispatch and pending-choice recovery coverage remains the 117-test suite plus real-Bolt production probe described above. Additional live pagination/closed-filter checks, restart during a pending choice, and a second real Slack identity were not exercised in this activation. The configured route was not deliberately exhausted. These limits remain tracked in issue #8; activation/core live checks are complete.

The deployment tool now creates an initial activation timestamp only after Slack preflight passes, preventing a failed preflight on a future fresh setup from establishing an earlier history boundary. Existing live journals and their activation identity were preserved.
