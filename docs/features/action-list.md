# Action ingestion: feature overview

The current [iteration spec](action-list-iteration-1-spec.md) is the authoritative feature-detail document. It includes the accepted parsing examples 1–6, provenance and date rules, five-day statistics, recurrence handling, and unchanged read-only source behavior.

Linear is the initial authoritative action store and lifecycle UI, behind a replaceable adapter. New issues start in the selected team's Backlog status; ingestion preserves later user edits and status. Custom interactive lifecycle UI work is superseded.

Delivery uses small end-to-end slices in the [approved ticket plan](action-list-ticket-plan.md). The local spec and approved plan are published in GitHub issues #1–#7.

Future features are maintained in [the roadmap](../ROADMAP.md); adapter architecture is described in [the action-store design](action-store-design.md).
