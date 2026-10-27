# Single-action Linear import

This slice creates exactly one explicitly selected title-defined action from a completed five-day extraction. It does not import the full list or implement lifecycle controls.

## Credentials and destination

The Linear connection in the chat is useful for choosing the workspace/team but does not authorize standalone code. For personal scripts, Linear supports a personal API key in Settings → Account → Security & Access. Restrict it to the selected team and the available read/create-issue permissions. No admin, delete, or update permission is needed by this slice. Your workspace may expose coarser controls; review what you grant.

Keep the raw key in a local file, preferably `.local/linear-api-key`, readable only by your account. Do not paste its contents into chat, use it in command arguments, or commit it. The program receives only its path. No new Python packages are required for the Linear adapter.

Read-only destination discovery:

```bash
.venv/bin/python -m second_brain linear-destinations \
  --api-key-file .local/linear-api-key
```

Use the returned workspace and team UUIDs explicitly. The importer checks the actual key's workspace and selected team before writing. It resolves the team's Backlog status, preferring a uniquely named Backlog within that category; if ambiguous, supply `--backlog-state-id` explicitly. It never silently creates a team or relies on Linear's default/Triage status.

## Select and plan

```bash
.venv/bin/python -m second_brain candidates \
  --report .local/reports/calendar-2026-09-28/report.json

.venv/bin/python -m second_brain import-one \
  --report .local/reports/calendar-2026-09-28/report.json \
  --source-record-id SOURCE_RECORD_ID \
  --workspace-id WORKSPACE_UUID --team-id TEAM_UUID
```

The second command prints the complete plan, including original content/provenance, without network calls, credentials, journal writes, or destination writes. Treat its output as personal data. Marker-only or multiple-action source records are refused in this slice.

To execute that same selection, add:

```bash
  --api-key-file .local/linear-api-key --execute
```

New issues start in Backlog. Details retain their extracted wording and links, followed by readable provenance and complete original source content in a fenced JSON section. Original source creation time, modification time, scheduled calendar date, and the destination issue's own creation time remain distinct. Missing source creation times are explicitly unavailable, never inferred. The returned URL identifies the issue actually read back from Linear.

## Identity and uncertain writes

An application import identity uses source type, calendar identity, source record/recurring-series identity, and the title-action slot. It does not depend on action text, timestamps, or Linear issue IDs. The title slot is the only supported slot in this slice; multi-action slot assignment is deferred.

The Linear adapter keeps a small owner-only SQLite journal at `.local/linear-imports.sqlite3`. It is synchronization bookkeeping, not a second authoritative action database. It stores the initial source snapshot and a random UUID v4 reserved before sending the create request. Linear accepts a caller-supplied issue UUID, allowing read-only recovery by that exact identity, including archived issues. A rerun returns the existing issue without editing its title, description, date provenance, or workflow status.

Keep this journal and back it up securely. Do not delete it or change `--journal` between runs: edited descriptions cannot reliably serve as a uniqueness index, and a fresh journal would lose reserved destination IDs. The visible import identity and portable metadata provide migration/recovery evidence but are not an immutable provider custom field. A separate portable migration flow remains future work.

If a create response is lost, the adapter makes one read-only reconciliation. If the reserved issue is visible, it returns it. If not, it stops and preserves the reservation; later runs only look it up. It never blindly sends a second create, including after a crash, destination deletion, or access change. This deliberately means manual resolution may be needed after a failure before any mutation was actually sent. No automatic journal reset is provided.

Requests are bounded per invocation, check GraphQL errors even on HTTP 200, observe exhausted rate-budget headers, reject redirects, and do not automatically retry mutations. Credential values and raw provider error responses are not logged.

UTF-8 key files with a byte-order mark are supported; other non-ASCII characters and embedded whitespace are rejected before requests. TLS always verifies certificates and hostnames. When available, the trusted `certifi` bundle installed with the Google libraries supplements the platform trust store, accommodating Python installations without configured default CA certificates.

## Verification

Application tests exercise the same `import_one` interface using a controlled action-store adapter. Linear contract tests use controlled provider responses for Backlog creation, provenance, workspace/team checks, persisted identity, uncertain responses, and preservation of native user edits/status. Live validation additionally requires the actual selected issue to be created once, read back, and found unchanged on a repeated import.

Live validation passed October 27, 2026: the user-selected title-defined record was created in the explicitly selected workspace/team's Backlog status; actual details and fenced provenance JSON matched the extracted action, and rerunning returned the same issue without creating another. All 31 tests pass. Linear canonicalizes Markdown list markers and blank lines; read-back verification compares actual details and structured provenance rather than byte-identical presentation formatting. Code delivery/commit is tracked separately from this live verification.

References: [Linear API](https://linear.app/developers/graphql), [API key permissions](https://linear.app/docs/security-and-access), [rate limits](https://linear.app/developers/rate-limiting), [official schema](https://github.com/linear/linear/blob/master/packages/sdk/src/schema.graphql).
