# Deterministic scheduled ingestion

The user approved this design on October 28, 2026. Routine execution uses Python, Google Calendar and Linear APIs, plus a native per-user macOS LaunchAgent. There are no LLM calls, cloud hosting fees or Slack messages in this iteration.

## Agreed behavior

- Default schedule: daily at 06:00 in `America/Los_Angeles`, even when the Mac's timezone changes. Alternatively configure a fixed elapsed-time interval of at least 60 seconds. Schedule and overlap changes preserve the success checkpoint.
- The inclusive Calendar-date window starts five calendar days before the **last successfully imported end date** and ends on the current Calendar date at run start. The overlap is configurable. It includes events later on that date, not just those before the current clock time.
- Seed the first checkpoint with October 28, 2026, the end of the verified manual bulk import. Never initialize it to the installation date and accidentally skip intervening days.
- A run performs a fresh complete Calendar preview, action import and source deletion/cancellation review. Both operations and private result persistence must succeed before advancing the checkpoint. Recorded unresolved reviews count as processed; actual failed records do not.
- Manual and scheduled consolidated runs share a nonblocking OS lock and the same state. If one is running, another skips without advancing anything. Lock release after a crash is automatic.
- Failed/partial runs retain completed writes in the existing import journal and keep the success checkpoint unchanged. The next scheduled attempt uses that same checkpoint. There are no immediate blind retries of mutations.
- Missed schedules coalesce into one catch-up run: if several days are missed, start five days before the unchanged success checkpoint and end on the current date. Do not replay one run for each missed day.
- A sleeping Mac runs a due check when awakened. A powered-off Mac runs a check after boot and login. The LaunchAgent only runs while this user is logged in; it does not wake or power on the Mac.
- Failures request a macOS notification with constant generic text; successes are quiet. Private logs give the date window, counts and failure details. Credentials/action content never appear in notification text. macOS notification permissions/settings can suppress display.
- Keep disposable run reports/logs for 30 days by default. Keep credentials, import journal, lock file and checkpoint indefinitely. Cleanup only touches timestamped runner-owned directories with an ownership marker; unknown directories and symlink targets are retained.

## Scheduling mechanism

A native `StartCalendarInterval` entry for every minute plus `RunAtLoad` triggers a cheap Python due check. The actual daily timezone or interval is evaluated in Python, independent of the host timezone. An already-processed schedule slot causes no Calendar or Linear requests and writes no new run artifacts. macOS coalesces calendar triggers after sleep; the load trigger handles login after shutdown. Detection normally occurs at wake/login or within the next minute. This minute-level polling does not mean an API import every minute.

The most recent attempted schedule slot is recorded **before** network work. Failures and crashes therefore do not cause retries on every minute's due check. The successful-date checkpoint advances only after complete success. A manual invocation intentionally bypasses the due guard and can retry immediately; it still honors the lock and advances the shared checkpoint only on success.

The state is scoped to Calendar ID, Linear workspace/team and import journal path. A mismatched or corrupt state is an error, not an excuse to reset it. Configuration/startup errors also request at most one notification per 24 hours and retain a private startup-error record beside the configuration.

For a configurable daily time falling in the spring DST gap, Python's timezone conversion maps it forward across the gap; a fall repeated time uses its first occurrence. There is at most one due slot per local daily date. The default 06:00 is outside both transitions.

## Configuration

Create an owner-only JSON file such as `.local/runner.json`. Relative paths are resolved relative to this configuration file, not the invoking shell's directory. Only credential **paths**, never credential values, belong here.

```json
{
  "calendar_id": "YOUR_CALENDAR_ID",
  "workspace_id": "WORKSPACE_UUID",
  "team_id": "TEAM_UUID",
  "backlog_state_id": "BACKLOG_UUID",
  "token_file": "google-token.json",
  "api_key_file": "linear-api-key",
  "journal": "linear-imports.sqlite3",
  "state_file": "runner-state.json",
  "runs_dir": "runs",
  "initial_checkpoint": "2026-10-28",
  "overlap_days": 5,
  "retention_days": 30,
  "max_source_records": 100,
  "request_budget": 1000,
  "schedule": {
    "mode": "daily",
    "time": "06:00",
    "timezone": "America/Los_Angeles"
  }
}
```

```bash
chmod 600 .local/runner.json
```

For an elapsed interval, replace only `schedule` with `{"mode": "interval", "seconds": 3600}`. Daily schedule supports HH:MM; intervals are evaluated on UTC epoch-aligned slots and checked at minute resolution. Edit the configuration to change cadence, overlap or retention; a scheduler reinstall is unnecessary. Invalid configuration is rejected. State/credentials/journal must be distinct and outside the disposable runs directory.

## Commands

First run manually and verify successful results and the checkpoint:

```bash
.venv/bin/python -m second_brain run --config .local/runner.json
```

This performs real Linear writes where required; it is not a plan command. It always attempts execution immediately, unless another consolidated run holds the lock. Run it again to verify duplicate protection. A failure retains the old successful date; inspect the latest private `.local/runs/run-*/summary.json` plus `import-results.json` and `source-review-results.json`. A failed fresh preview never causes a stale report to be imported.

Only after a successful manual run, enable scheduling:

```bash
.venv/bin/python -m second_brain schedule-install --config .local/runner.json
.venv/bin/python -m second_brain schedule-status
```

The installer writes `~/Library/LaunchAgents/com.randygc.second-brain.plist` owner-only, registers it in the current GUI user domain and verifies that it is loaded. No root daemon or administrator account is used. The job references the selected Python interpreter, project directory and config path; credential values are absent. Keep the project, virtual environment and config at their installed locations.

Inspect a due check manually without forcing an API run:

```bash
.venv/bin/python -m second_brain run --config .local/runner.json --scheduled
```

Disable scheduling while retaining all durable state:

```bash
.venv/bin/python -m second_brain schedule-uninstall --config .local/runner.json
```

Exit code 0 includes success or a safe skip (`not_due`/`already_running`); code 2 means a consolidated run failed. Scheduler setup failures return 1. OS-level failures that prevent Python from starting cannot produce Python notifications; use `schedule-status` and macOS `launchctl print gui/$(id -u)/com.randygc.second-brain` to investigate. Scheduler stdout/stderr go to `/dev/null`; private runner artifacts contain normal operational diagnostics.

## Limits and future work

This iteration selects events by **scheduled date**. New/edited events before the lower boundary or after today are not discovered. Deletion review separately checks all known source identities and does not infer deletion from date-window absence. It does not discover content edits outside the window.

Request budgets, source-record limits, authorization failures and Linear capacity can prevent a complete run. No automatic paid upgrade is performed. Such failures preserve the checkpoint and are retried at the next configured schedule; human action may be needed. Increasing `max_source_records` explicitly supports a growing journal. More than 3,660 catch-up dates exceeds the existing preview bound and needs operator attention.

The low-level `preview`, `import-batch` and `review-sources` tools remain available, but do not update the consolidated runner checkpoint or participate in its whole-run lock. Use `run` for routine combined manual/scheduled operation. Back up configuration, credentials, import journal and checkpoint together; never delete state as an automatic recovery strategy.

The future agent wrapper and Slack UI should report failed script executions via Slack. Delivery, permissions, deduplication and acknowledgment requirements are deliberately deferred; the Python runner will remain independent of that wrapper.

Reference: Apple's [launchd guide](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html) and the installed `launchd.plist(5)` manual, which documents coalesced `StartCalendarInterval` wake behavior. Checked October 28, 2026.

## Verification and initial activation

90 tests pass. Coverage includes daily/interval due decisions, LA timezone and DST, manual-versus-scheduled locking, failure/crash attempt guards, multi-day catch-up, checkpoint scope protection, configuration validation, owner-only state, retention boundaries and symlinks, startup-notification throttling, and the full pipeline over controlled Google/Linear adapters. A failed preview never imports stale data; a deletion-review failure after successful issue creation retains the old checkpoint and safely recognizes the existing issue on retry.

On October 28, 2026, two live manual consolidated runs both completed the October 23–28 window: nine already-imported actions, zero new issues, zero import failures, and 52 active source records with zero deletion-review failures. The shared successful Calendar date is October 28. A scheduled due check then skipped with `not_due` and made no API requests. Only after these checks was the per-user LaunchAgent installed and confirmed loaded; private config/state permissions are 0600. The next default daily slot is October 29 at 06:00 America/Los_Angeles. Physical sleep/shutdown catch-up relies on documented native launchd behavior and the tested due guard; the user's Mac was not deliberately powered off for testing.
