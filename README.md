# Second Brain

Read-only Google Calendar action extraction and single-action or bounded date-range ingestion into Linear through a replaceable action-store interface. Preview never writes to Linear or modifies Calendar events. Both `import-one` and `import-batch` default to a local-only plan and require `--execute` to create missing issues.

For the command reference and normal operating workflow, see the [action item consolidator CLI guide](docs/cli-guide.md).

For credentials, single-action selection, and import identity, see [Linear setup](docs/linear-setup.md). For full-set imports, daily/per-action outcomes, partial failures, and safe reruns, see [batch import](docs/batch-import.md).

## Run without credentials or dependencies

Python 3.11+ is required (including IANA timezone data). From the repository root:

```bash
python3 -m unittest discover -s tests -v
python3 -m second_brain preview \
  --calendar-id fixture \
  --start-date 2026-09-28 \
  --input-json tests/fixtures/calendar_cases.json \
  --output-dir .local/reports/historical-cases
```

Open `.local/reports/historical-cases/report.html` in a browser. The six historical examples produce 21 actions (1, 1, 3, 1, 8, 7). This is synthetic test data, **not a fresh read of your calendar**. JSON output retains extracted payloads, complete source descriptions, identities, timestamps, and daily counts.

The report is static and private to your local filesystem. No server, external scripts, images, or lifecycle controls are used. Reports and credentials are ignored by Git, written owner-only, and contain personal data. Do not put them in a public hosting directory.

## Connect Google Calendar

See [Google setup](docs/google-calendar-setup.md). A chat-connected Calendar plugin does not supply credentials to this standalone program. The live adapter reads raw Google API responses so actual newlines are not confused with Markdown wrapping.

After Google support is installed and you have downloaded a Desktop OAuth client JSON:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[google]'
.venv/bin/python -m second_brain auth \
  --client-secrets .local/google-client.json \
  --token-file .local/google-token.json
.venv/bin/python -m second_brain preview \
  --calendar-id primary \
  --start-date 2026-09-28 \
  --token-file .local/google-token.json \
  --output-dir .local/reports/calendar-2026-09-28
```

Authorization opens Google's browser page and a temporary loopback callback on `127.0.0.1`. Tokens stay local. Default event permission is read-only for calendars you own; calendar-property read access supplies the actual timezone. Only the configured calendar is fetched. Use `auth --include-shared` only if selecting a calendar you do not own; this requests broader read-only event access. No event-write permission is requested.

By default, preview searches the start date plus four calendar dates; pass `--end-date` for an inclusive bounded range, using the calendar's timezone, including daylight-saving transitions. It retrieves all pages before writing a successful report. It counts matching occurrences by scheduled start date; a recurring series contributes its actions only on its earliest matching occurrence in the window. Matching events with no actions are still counted and shown. Missing creation timestamps stay null, with a warning.

Failures return exit code 1 and do not publish partial retrieval as an empty success. A previous report may remain on disk; the error explicitly identifies it as stale. Preview output paths are local, and preview performs no destination writes. Imports require an explicit execute command; no scheduled runs are enabled.

## Modules and verification

- `preview` is the application interface used by both CLI runs and behavioral tests. It accepts a source adapter and returns a complete report or an error.
- `extraction` applies shared action-line rules to normalized source content. Raw source content is preserved separately. Explicit newlines, HTML breaks/blocks, lists, emphasis, and links are handled without inferring actions from sentence boundaries.
- `google_calendar` implements raw REST pagination, timezone-aware reads, an offline JSON replay adapter, and Google-library authentication.
- `report` renders escaped static HTML and portable JSON; Linear ingestion consumes the application output without depending on presentation.

Synthetic fixtures preserve the structure and expected counts of the six supplied examples while excluding personal details and real links. Example 6’s explanatory end-of-item asterisks are not production delimiters. Tests cover application behavior, raw JSON/HTML line fidelity, recurrence, independent identical actions, timezone boundaries, DST, pagination failures, safe rendering, and repeatable local output. The HTTP contract tests use an injected session; live Google login and real-calendar line verification passed on October 26, 2026 after dependency installation and authorization. The September 28–October 2 live run produced 9 matching occurrences and 14 actions, including Example 6’s seven actions and four double-dash bullets. The current suite has 73 passing tests, including date-range imports and source-deletion reviews.

Feature scope: [spec](docs/features/action-list-iteration-1-spec.md), [ticket plan](docs/features/action-list-ticket-plan.md), [action-store design](docs/features/action-store-design.md).

For confirmed Calendar deletions/cancellations, run the separate [source-deletion review](docs/source-deletion-review.md) step. It checks saved event/series identities, posts unresolved Linear comments only with reliable evidence, and never deletes issues or treats absence from a date window as deletion.
