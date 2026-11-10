# Hermes slice 1 compatibility check

Status: dashboard access confirmed by the owner and subscription model route verified November 5, 2026; offline Bolt dispatch previously verified. Production Slack integration is active; final slice 1 acceptance completed November 10, 2026, as recorded in the runbook. Owner approved Q55: Hermes owns Slack ingress from slice 1; bounded subscription-model interpretation is permitted, while explicit commands remain deterministic. See [specification](slack-agent-spec.md).

## Local inventory

Initial read-only inspection: `hermes` is not on PATH; Codex is available at `/opt/homebrew/bin/codex`. The Second Brain project declares Python 3.11+ and no Hermes/Slack dependency. This does not rule out an off-PATH installation. System Python is 3.14.0; `slack-bolt` and `slack-sdk` are absent from that interpreter. No credentials were inspected and no runtime installed or activated.

## Check procedure and required evidence

1. Select and record a pinned Hermes release/commit and its interpreter/dependency requirements. Keep its environment separate from the working Calendar runner. Confirm native Slack handler registration and dispatch ordering against immutable source references. Record any reliance on private internals.
2. Build an isolated synthetic-message harness at the native Slack handler boundary. Replace inference with a stub that raises a quota error and Linear with a controlled adapter. Enable no production services. Confirm authorized `add`, `search`, `help`, duplicate confirmation and cancel route without invoking inference. Confirm unknown messages cannot fall through into unrestricted agent execution.
3. Exercise owner, workspace and channel checks, DMs, alternate built-in/skill command paths, quoted instructions, edited/deleted messages and malformed events. Deny unauthorized input before writes. Verify handler exceptions/timeouts do not produce unintended inference or side effects. Report the actual scope of these checks, distinguishing dispatch tests from end-to-end Slack tests.
4. Verify receipt persistence precedes the application's received acknowledgement and all Linear mutation. Do not confuse Slack transport-envelope acknowledgement with durable application acceptance. Crash/restart and replay the same message; reconcile an uncertain create by reserved identity. Persist clarification and outgoing replies. Mark incomplete/ambiguous delivery honestly; do not promise exactly-once Slack replies without evidence.
5. Exercise history reconciliation with paginated synthetic history and a durable cursor. Cover first activation, reconnect, overlap, retention gaps, offline message edits/deletions and pending thread confirmations. Verify real Slack token support/rate limits before promising private-thread recovery. If replies cannot be recovered under approved scopes, ask the owner to repeat confirmation and keep the addition pending.
6. Verify installed subscription-authenticated model access before selecting a model. No API-key fallback. For free-form add/search interpretation, use a bounded output schema, preserve original content, and validate results before calling application functions. Clarify ambiguous intent. Force quota/auth failures: keep explicit commands operating and persist model-dependent requests. Bound inference calls/retries and distinguish access errors accurately. This introduces minimal quota handling in slice 1; proactive failure/recovery broadcasts remain slice 3.
7. Prepare a narrow Slack app manifest, owner/channel configuration and setup instructions. After offline checks, conduct a scoped live check in the dedicated channel using controlled action content and the configured Linear destination. Do not send unrelated messages, change the Calendar scheduler, or reset production journal/checkpoint as part of the proof.

## Decision criterion

Proceed with the Hermes plugin when the proof demonstrates restricted dispatch, inference-independent explicit commands, durable application receipts, safe Linear reconciliation and documented recovery limits without substantial framework customization. If any requirement fails, present the failing behavior, estimated integration work and alternative connector tradeoff to the owner before selecting another design.

## Source inspection results

Candidate release: Hermes `v0.22.5`, resolved to commit `bf0203a794a07aac3ff764972ab9087baa4e4f4e`. This release is now installed in the personal-hermes VM; its revision was verified through the published launcher.

The pinned [Slack adapter](https://github.com/NousResearch/hermes-agent/blob/bf0203a794a07aac3ff764972ab9087baa4e4f4e/plugins/platforms/slack/adapter.py) registers core handlers before invoking plugin handler factories. This differs from current documentation describing plugin listeners as registered first. Listener registration order therefore cannot establish early interception for this release. Check supported Bolt middleware as an alternative before selecting an integration route; any proof must use actual dispatch, not only a fake factory/listener.

The post-admission hook remains unsuitable as the only enforcement point: built-in command dispatch occurs earlier and hook failures can fall through into ordinary model processing. No runtime compatibility pass is claimed. Subscription access, live Slack permissions/history, actual outage behavior and durable receipt checks remain unverified.

Record interpreter, commands run, observed runtime outcomes, remaining unknowns and live-test scope here as checks complete.

## Source references

- [Hermes plugin API](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins).
- [Hermes hooks and failure behavior](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks).
- [Hermes Slack setup](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/slack).
- [Slack channel history](https://docs.slack.dev/reference/methods/conversations.history/).
- [Slack thread replies](https://docs.slack.dev/reference/methods/conversations.replies/).

## Existing stack discovery and execution status — October 30, 2026

Found `/Users/randychevalier/hermes-stack-personal`. Its AGENTS.md and service documentation place Hermes in an isolated OrbStack VM, with source/venv at `/opt/hermes-agent` inside the VM. The host `~/.hermes` directory alone is not the active VM runtime. Follow the stack's wrappers and single-source configuration if integrating; do not install a second native runtime or hand-edit generated config.

Through the existing stack launcher, `./stack-cli hermes --version` reported `machine not found: personal-hermes`. A read-only `orb list` via the repository's `orbShell` wrapper returned no VM entries. Thus the stack repository exists, but a runnable VM/version/authentication state was not found. No VM provisioning, stack build, configuration changes or scheduler changes were performed. OrbStack access required sandbox escalation for its normal runtime logs/daemon; an absent VM must not be treated as evidence of a broken Hermes program.

Prepared `tools/compatibility/probe_hermes_bolt.py` and pinned `requirements.txt`. The probe uses real Bolt dispatch and the AST-extracted upstream registration method, with synthetic auth/delivery and network guards. It is an experimental compatibility harness, not a production plugin. Python syntax compilation passed; behavior has not run. Its canary deliberately exercises an unhandled core listener to verify the harness; production routing still needs an explicit policy that blocks unsupported capabilities.

Created a separate environment at `.local/compatibility/hermes-slack-venv`. Dependency installation failed in the sandbox due to package-index connectivity; the subsequent escalated download request was declined. No alternate download was attempted. A pinned Hermes checkout is also still needed. Live subscription access, model availability, durable receipt/recovery behavior and Slack/Linear integration remain unverified.

Next prerequisites: locate/restore the existing VM with the owner or confirm its intended host; obtain permission for isolated dependency/source downloads; run the harness against the pinned checkout, then full Hermes integration. Reconcile the installed VM version with the candidate before changing it.

## Provisioning and compatibility results — October 30, 2026

The owner confirmed the prior setup was unfinished and authorized completing it, choosing built-in local memory and subscription-only access. The original `.stack` and changed templates were backed up under `hermes-stack-personal/_bak/setup-20261030T231309Z`. Disabled optional Honcho/UI/browser/search services without discarding their configured values. Generated missing local service credentials privately.

Installed Hermes v0.22.5 at the pinned commit in the isolated OrbStack VM `personal-hermes`, using Python 3.14.9. The first install failed with ELOOP: the bundled Python archive contains both `N/NCR260VT300WPP` (symlink) and `n/ncr260vt300wpp` (file). The [two-entry archive probe](../../tools/compatibility/repro_hermes_python_archive.py) reproduced the failure on the case-insensitive Mac filesystem and passed on the VM-native filesystem. Relocated the rebuildable `tools` and `installs` directories to `/opt/hermes-runtime`, preserving their original copies as `*.mac-before-native` and linking them from the shared home. Configuration and memory remain shared. Back up the home while preserving symlinks; VM-native runtime bytes are rebuildable and are not in the Mac-side home backup.

The stack wrapper required two release-compatibility fixes: the gateway unit now uses the published Hermes launcher rather than a removed `venv/bin/python` path; gateway restart uses privileged systemd service control while the Hermes application runs as its installation owner. The gateway, dashboard and logtail were subsequently verified active/running. The dashboard's required basic authentication uses a generated local password in the existing `.stack/.env` and a derived hash in Hermes config.

Only pg, redis, LiteLLM and CLIProxyAPI are enabled alongside the VM; all four reported healthy. The model template now contains only the local subscription-proxy route with an empty fallback list. Initial model selection is `cliproxy/gpt-5.4-mini`, subject to validation after sign-in. No paid-provider route or API-key fallback is configured. No model request has been verified: the proxy inventory currently contains zero provider credentials and zero available models.

Ran [probe_hermes_bolt.py](../../tools/compatibility/probe_hermes_bolt.py) in a separate VM test environment with Bolt 1.30.0, Slack SDK 3.44.1 and aiohttp 3.14.5. Result PASS: actual Bolt dispatch, upstream AST-extracted registration method, middleware attached after core listener registration, owner/workspace/channel checks, explicit command bypass, injected caught/uncaught handler failures, slash rejection, thread routing and continued deterministic operation after a simulated core failure. Expected injected tracebacks accompany the passing result. This does not validate full Hermes plugin startup, real provider quota propagation, Socket Mode acknowledgements, durable receipts, history recovery or Linear writes.

Prepared a private one-time sign-in wizard at `.local/compatibility/hermes-subscription-login.sh`. It requests a fresh OAuth URL through the documented local management API, asks the owner to perform OpenAI browser sign-in and copy the loopback callback; on macOS it reads the clipboard after explicit confirmation, with hidden-input fallback on other systems, then opens the dashboard and copies its local password to the owner's clipboard. It does not ask for credentials in chat. See [CLIProxyAPI management API](https://help.router-for.me/management/api) for the provider URL/callback contract. Wizard shell syntax and helper TypeScript parsing pass; the human sign-in sequence has not been run.

Remaining before declaring setup complete: owner OpenAI sign-in, verify returned model IDs, make one bounded synthetic model request through the subscription route, verify the dashboard login and confirm stable service state. Slack channel/app provisioning and the production plugin are slice 1 work, not completed by this setup. The Calendar scheduler/checkpoint and production Linear items were not changed.

## Callback wizard repair — November 3, 2026

The owner reported no visible response after submitting the hidden callback input. A synthetic terminal probe verified that the hidden read accepts Return, but a stalled local HTTP endpoint reproduced a silent, unbounded callback submission. This does not establish which condition occurred in the owner's terminal. The helper now announces submission and token exchange and aborts each stalled HTTP request after 15 seconds with a sanitized error. The wizard removes the extra browser-stage pause and uses explicitly confirmed clipboard input on macOS, avoiding invisible URL pasting; no callback is printed. Synthetic tests cover terminal input, the whole wizard with fake browser/clipboard/helper commands, and a stalled local server. Real subscription sign-in still requires the owner, followed by live model verification.

## Subscription model verification — November 5, 2026

The owner completed subscription OAuth and confirmed dashboard access. The proxy inventory showed one Codex credential. Its available models excluded the initial `gpt-5.4-mini` choice and included `gpt-6-luna`; selected subscription-backed GPT-6 Luna for the initial focused workloads. Both stack model selectors, the model template and the runtime route now use `cliproxy/gpt-6-luna`. Paid fallback remains disabled.

The first model check failed locally with HTTP 400 because the ordinary build renderer intentionally preserves an existing runtime file: changing the template had left the runtime catalog on the old mini-model route. The stack's explicit `reconfigure litellm` operation backed up and regenerated that file; after gateway recreation, both Hermes-key and admin-key catalogs exposed the Luna route. Do not rely on an ordinary build to apply template changes to existing runtime files.

A bounded synthetic request through LiteLLM using the Hermes virtual key returned HTTP 200 and exactly `HERMES_OK`: 310 prompt tokens, eight completion tokens, zero reasoning tokens. This verifies the configured local gateway → subscription proxy → model request/response path. It does not by itself verify agent tools, real quota exhaustion/recovery, Slack delivery, persistent message receipts or Linear writes. No personal action-item content was submitted.

Corrected the wrapper restart to `sudo systemctl restart hermes-gateway`: the CLI's system-restart command requires root, but invoking the Hermes application as root conflicts with installation ownership. The service itself uses the published launcher and runs under the Hermes user. Local dashboard credentials remain in the stack environment file; the generated password hash remains in Hermes config.

Initial Hermes setup is now verified for dashboard access and the selected subscription model route. Continue with slice 1's production Slack app/plugin and deterministic action-store operations; memory sharing, learning permissions and expanded workflows remain separately scoped.

## Production slice 1 checks — November 8, 2026

The actual production plugin (`integrations/hermes/slack_action_items`) and shared durable command application are staged at `/opt/hermes-runtime/second-brain-slack/staged`; no Slack ingress was activated. `tools/compatibility/probe_slack_plugin.py` passed with real Bolt dispatch in the existing isolated pinned environment. It registered core listeners first and verified owner/workspace/channel enforcement, DM/subtype/slash denial, explicit add/search during synthetic quota rejection, receipt-storage failure and configuration-initialization failure. Core listener calls remained zero. The factory installs its deny guard before application/config imports. Hermes native plugin validation also passed manifest/dependency checks, isolated registration, security scan and the no-core-override check. Complete plugin enablement, Socket Mode startup/ack delivery and effective core authorization remain live acceptance checks.

The 117-test Python suite passes, including the existing 90 Calendar/regression tests and new application, transport and subscription-interpreter tests. A read-only live Linear search contract read 207 current team items with full pagination; it did not create an issue or touch the Calendar journal. Two small synthetic requests through the configured subscription gateway classified add and search with the production interpreter; no Linear mutations followed.

The prepared activation tool verifies private channel/bot/owner membership and subscription-only route before enabling. Human Slack app/token setup is still required. Follow [slice 1 runbook](slack-slice-1.md); do not mark slice 1 accepted until its live checks pass.

## Activated private Slack integration — November 8, 2026

Hermes PM enabled the plugin and the real gateway started successfully with its Slack credentials. The restricted private channel passed workspace, bot/owner membership and privacy checks. Effective process settings deny ordinary core-user access and disable DMs/allow-all. Live owner help, one confirmed Linear addition, search finding that item, and similar-item cancellation all passed. A controlled gateway restart retained six completed receipts, one confirmed import and zero undelivered replies; history reconciliation advanced after startup. The real token can retrieve the cancellation from retained private-channel thread replies. No second issue was created. These extend the earlier offline/native-plugin and synthetic model checks; see the runbook's activation record for remaining live-test limits.


## Final slice 1 acceptance — November 10, 2026

Live pagination, closed-item filtering and a fresh duplicate-choice cancellation after gateway restart passed. Journal checks confirmed one fixture import, no duplicate, no pending test choice and preserved original imports. The 119-test suite and independent review corrections passed. The [runbook](slack-slice-1.md#final-acceptance--november-10-2026) records the second-human and real-quota test substitutions.
