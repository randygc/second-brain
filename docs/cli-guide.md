# Action item consolidator: command guide

Run commands from the project root, using `.venv/bin/python -m second_brain`. Google Calendar is read-only. Linear holds the action items and their user-managed workflow. For configurable scheduling and the shared successful-run checkpoint, see [scheduled ingestion](scheduled-ingestion.md).

For routine scheduled or manual combined execution, use `run --config .local/runner.json`. The lower-level commands remain useful for setup, previews and targeted troubleshooting.

## Commands at a glance

| Command | Purpose | External writes |
| --- | --- | --- |
| `run` | Execute the configured fresh preview, import and deletion review with shared checkpoint/lock. `--scheduled` skips when not due. | Creates missing issues and posts relevant review comments. |
| `schedule-install` | Enable a native macOS LaunchAgent after a successful manual consolidated run. | Local scheduler configuration only. |
| `schedule-status` | Check whether the LaunchAgent is loaded. | None. |
| `schedule-uninstall` | Disable/remove the LaunchAgent while preserving state. | Local scheduler configuration only. |
| `auth` | Authorize Google Calendar access and save a local token. | Grants read-only access; saves credentials locally. |
| `preview` | Read Calendar, extract actions, and write private HTML/JSON reports. | None. |
| `candidates` | List title-defined actions eligible for the original single-action import. | None; reads a local report. |
| `linear-destinations` | Discover the connected Linear workspace and accessible teams. | None. |
| `import-one` | Plan or import one selected title-defined action. | Only with `--execute`: creates the missing Linear issue. |
| `import-batch` | Plan or import all extracted actions from a complete report. | Only with `--execute`: creates missing issues and posts applicable source-change review comments. |
| `review-sources` | Check previously imported Calendar identities for reliable deletion/cancellation evidence. | Only with `--execute`: posts unresolved Linear review comments. |

Use `--help` for the complete arguments of any command:

```bash
.venv/bin/python -m second_brain --help
.venv/bin/python -m second_brain preview --help
.venv/bin/python -m second_brain import-batch --help
```

## Initial setup

See [Google Calendar setup](google-calendar-setup.md) for installing dependencies and creating a Desktop OAuth client, then authorize:

```bash
.venv/bin/python -m second_brain auth \
  --client-secrets .local/google-client.json \
  --token-file .local/google-token.json
```

For calendars you do not own, see the setup guide before using `auth --include-shared`. Existing valid credentials can be reused; authorization is not required for every import.

Store the Linear key in `.local/linear-api-key`, then discover destination IDs:

```bash
.venv/bin/python -m second_brain linear-destinations \
  --api-key-file .local/linear-api-key
```

The examples below use placeholders `YOUR_CALENDAR_ID`, `WORKSPACE_UUID` and `TEAM_UUID`. Replace them with the selected Calendar ID and the discovered Linear IDs. Commands do not automatically create a team. See [Linear setup](linear-setup.md) for credentials and Backlog selection.

## Normal import workflow

### 1. Read Calendar and inspect the preview

```bash
.venv/bin/python -m second_brain preview \
  --calendar-id YOUR_CALENDAR_ID \
  --start-date 2026-07-01 \
  --end-date 2026-10-28 \
  --token-file .local/google-token.json \
  --output-dir .local/reports/calendar-range
```

Dates are inclusive and interpreted in the Calendar's timezone. `--end-date` is optional: without it, the preview covers the start date plus four more days. Explicit ranges support 1–3,660 dates, including future dates when requested. The date range is configuration, not hard-coded.

Open `.local/reports/calendar-range/report.html` to inspect extracted actions, complete source details, review flags and daily statistics. The companion `report.json` is the input to import commands. Only a successful complete retrieval should be imported; an old file left after a failed preview is stale.

For an offline demonstration, replace `--token-file` with `--input-json tests/fixtures/calendar_cases.json` and use `--calendar-id fixture` with the sample September 28, 2026 start date. Offline fixture reports contain synthetic examples, not current Calendar data.

### 2. Plan the Linear import

```bash
.venv/bin/python -m second_brain import-batch \
  --report .local/reports/calendar-range/report.json \
  --workspace-id WORKSPACE_UUID --team-id TEAM_UUID
```

This is local-only and sends no Linear requests. It validates the extraction and lists candidate actions; it does not check current Linear capacity or determine exact new-versus-existing counts. Check destination capacity before a bulk write; the current implementation does not automatically enforce the subscription's issue limit.

### 3. Execute the import

```bash
.venv/bin/python -m second_brain import-batch \
  --report .local/reports/calendar-range/report.json \
  --workspace-id WORKSPACE_UUID --team-id TEAM_UUID \
  --api-key-file .local/linear-api-key \
  --journal .local/linear-imports.sqlite3 \
  --results-file .local/import-results.json \
  --execute
```

The import uses the report's dates and payload; it does not read Calendar again. Run a fresh preview when you want new Calendar changes included. Add `--backlog-state-id BACKLOG_UUID` if the team's Backlog-category status is ambiguous.

New issues start in Backlog. Reruns use the same journal to recognize existing issues, preserve Linear edits/status and avoid duplicate creates. Changed source records are held for review; comments are posted only for relevant changed, removed or ambiguous actions, not unchanged siblings. Do not replace the journal to work around an error. Back it up with your private local data.

Results report `created`, `already_imported`, `reconciled`, `changed` and `failed`. The `changed` count means current extracted slots held because their source changed; it is not the number of changed individual actions or newly posted comments. See `source_reviews` and `affected_existing_actions` for review context. Read-back failures can occur after a successful write: inspect the saved outcome rather than assuming no issue exists or starting over with another journal.

### 4. Review deleted/cancelled sources separately

An ordinary date-range import does not infer deletion from an event's absence. Check saved source identities independently:

```bash
.venv/bin/python -m second_brain review-sources \
  --calendar-id YOUR_CALENDAR_ID \
  --token-file .local/google-token.json \
  --workspace-id WORKSPACE_UUID --team-id TEAM_UUID \
  --journal .local/linear-imports.sqlite3 \
  --results-file .local/source-review-plan.json
```

The default checks Calendar and reports planned reviews without posting anything to Linear. To post confirmed deletion/cancellation comments, rerun with `--api-key-file .local/linear-api-key --execute`. It checks up to 100 distinct source records by default; increase `--max-records` explicitly for a larger journal. Existing issues remain intact, and reviews are not automatically resolved. See [source-deletion review](source-deletion-review.md) for evidence and recurrence rules.

## Import one title-defined action

The normal workflow uses `import-batch`. For the earlier single-action workflow:

```bash
.venv/bin/python -m second_brain candidates \
  --report .local/reports/calendar-range/report.json

.venv/bin/python -m second_brain import-one \
  --report .local/reports/calendar-range/report.json \
  --source-record-id SOURCE_RECORD_ID \
  --workspace-id WORKSPACE_UUID --team-id TEAM_UUID
```

`candidates` is intentionally limited to title-defined actions such as `Action: Call plumber`; it does not list every description-defined action. Supply its selected source record ID to `import-one`. To create the selected issue, add `--api-key-file .local/linear-api-key --journal .local/linear-imports.sqlite3 --execute`. Use the same journal as batch imports.

## Exit codes and local files

- `0`: success; inspect the command's mode to distinguish a plan from execution.
- `1`: setup, validation, retrieval or report-writing failure.
- `2`: partial action-import/source-review failure; inspect the saved per-record results. Applicable to `import-batch` and `review-sources`.

Credentials, tokens, reports, result files and the journal belong under ignored `.local/` and must remain private. Normal commands reuse saved deterministic code; they do not regenerate the program or HTML template with an agent each run. HTML reports are static inspection artifacts, while action editing and workflow management happen in Linear.

More detail: [batch import](batch-import.md), [bounded historical import](bulk-import.md), [source-deletion review](source-deletion-review.md).
