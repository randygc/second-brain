# Slice 1 review and closure evidence

Reviewed baseline: `e50fbf7`. Initial implementation: `c1fc27b`. Review corrections: `d84f210`. The code-review skill ran independent Standards and Spec reviews; both re-reviews report no remaining material blocker.

## Standards

Initial findings:

- **P2, inconsistent backups:** `SlackCommands.backup` did not share the processing lock, so a concurrent operator CLI could interleave a reservation/uncertain create between the two journal snapshots. This violated ADR 0002's reserved-UUID recovery guarantee.
- **P2, adapter isolation:** `LinearActionReader` owned GraphQL, provider fields and pagination inside the shared search module, contrary to ADR 0001. The reviewer also identified possible Feature Envy; this was a judgment call supporting the documented module-placement finding.

Both resolved: backups and processing share a lock; complete generations are selected by an atomic manifest, retaining current/previous snapshots. The reader now lives in the Linear adapter. Re-review found no new material standards or correctness regression.

## Spec

Initial finding:

- **P2, restore could lose a reservation:** an import snapshot taken before a concurrent create, paired with a later pending receipt, could allow restoration to reserve a new UUID. This violated the slice 1 requirement to reconcile uncertain writes without a second create.

Resolved by the lock and complete-generation publication. A regression first failed against the initial code, then passed after the fix: active-worker backups defer; an uncertain creation is restored and reconciled without another mutation. Another regression verifies interrupted manifest publication keeps the prior complete generation. The independent re-review ran all 119 tests successfully and reported no unresolved material blocker or scope creep.

Initial totals: Standards 2 findings (worst: backup/restore consistency); Spec 1 finding (backup/restore consistency). After correction: Standards 0 unresolved; Spec 0 unresolved.

## Verification

- All 119 Python tests pass, including the previous Calendar behavior and new concurrent-backup/restore regressions.
- Native Hermes plugin validation, real-Bolt production dispatch with zero ordinary core listener calls, bounded synthetic subscription interpretation and live read-only Linear pagination passed.
- Live owner help/add/search, duplicate cancellation and ordinary restart passed, preserving one confirmed verification issue.
- Live Slack `search --all a` and threaded `next` returned two pages.
- Closure checks for closed filtering and restart while a choice is pending are recorded in the runbook after journal verification.
- No second human Slack account was available. This live-human scenario is explicitly unperformed; real-Bolt unauthorized-user/channel/workspace/DM tests and mismatched-identity checks against the deployed application provide the substitute evidence. Do not describe them as a second-human live test.
- No real subscription quota was exhausted. Rejection/recovery is covered with controlled failure tests; no paid fallback is configured.
- Clickable Slack links remain follow-up issue #9 and are not bundled into this merge.

## Existing Hermes stack prerequisites

The active upstream clone (`simple10/hermes-stack`, base `0ee03e30688a7cc803e8ee9fa928292b26c1b605`) retains three local setup customizations: published Hermes launcher instead of the obsolete fixed venv path, systemd restart under the correct service user, and the minimal subscription-only LiteLLM route. Their non-secret source diff is versioned at `integrations/hermes/stack-compatibility.patch`; reverse-apply validation confirms it matches the running clone. It includes no `.stack` state, tokens, dashboard password, journals or personal action content. These local upstream-clone changes are intentionally not pushed to the vendor repository.
