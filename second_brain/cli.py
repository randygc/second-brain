"""Reusable extraction and explicitly selected single-action ingestion."""

import argparse
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import sys

from .google_calendar import (GoogleCalendarSource, JSONCalendarSource,
                              authorize, authorized_session)
from .preview import SourceError, preview
from .report import write_report
from .action_store import StoreError, import_one, select_title_action
from .extraction import title_action_text
from .linear_store import LinearActionStore, LinearClient, destinations


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    auth = commands.add_parser("auth", help="Authorize read-only raw Google Calendar access")
    auth.add_argument("--client-secrets", type=Path, required=True)
    auth.add_argument("--token-file", type=Path, default=Path(".local/google-token.json"))
    auth.add_argument("--include-shared", action="store_true", help="Also authorize event reads from calendars you do not own")
    extract = commands.add_parser("preview", help="Extract five calendar days and write a local report")
    extract.add_argument("--calendar-id", required=True)
    extract.add_argument("--start-date", type=date.fromisoformat, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)
    inputs = extract.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--token-file", type=Path)
    inputs.add_argument("--input-json", type=Path, help="Complete raw API JSON: timeZone, items, optional summary/calendarId")
    candidates = commands.add_parser("candidates", help="List title-defined actions eligible for the single-issue slice")
    candidates.add_argument("--report", type=Path, required=True)
    discover = commands.add_parser("linear-destinations", help="Read the connected workspace and accessible teams; no writes")
    discover.add_argument("--api-key-file", type=Path, required=True)
    single = commands.add_parser("import-one", help="Plan or execute exactly one title-defined action import")
    single.add_argument("--report", type=Path, required=True)
    single.add_argument("--source-record-id", required=True)
    single.add_argument("--workspace-id", required=True)
    single.add_argument("--team-id", required=True)
    single.add_argument("--backlog-state-id")
    single.add_argument("--api-key-file", type=Path)
    single.add_argument("--journal", type=Path, default=Path(".local/linear-imports.sqlite3"))
    single.add_argument("--execute", action="store_true", help="Actually write the selected issue; default is a local-only plan")
    args = parser.parse_args(argv)
    try:
        if args.command == "auth":
            authorize(args.client_secrets, args.token_file, args.include_shared)
            print(f"Read-only credentials saved locally to {args.token_file}.")
            return 0
        if args.command == "linear-destinations":
            print(json.dumps(destinations(LinearClient(args.api_key_file)), indent=2))
            return 0
        if args.command in {"candidates", "import-one"}:
            try:
                report = json.loads(args.report.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                raise StoreError("Cannot read the extraction report JSON. Run preview first.") from exc
            if args.command == "candidates":
                if not isinstance(report, dict) or report.get("status") != "complete":
                    raise StoreError("Only a complete extraction report is eligible.")
                for action in report.get("actions", []):
                    if title_action_text(action["original_content"]["title"]):
                        draft = select_title_action(report, action["source_record_id"])
                        print(json.dumps({"source_record_id": action["source_record_id"], "title": draft.title,
                                          "scheduled_date": action["scheduled_date"]}, ensure_ascii=False))
                return 0
            draft = select_title_action(report, args.source_record_id)
            if not args.execute:
                print(json.dumps({"mode": "plan_only", "workspace_id": args.workspace_id,
                    "team_id": args.team_id, "initial_status": "Backlog", "action": asdict(draft)}, ensure_ascii=False, indent=2))
                return 0
            if not args.api_key_file:
                raise StoreError("--execute requires --api-key-file. Never pass the key as a command-line value.")
            store = LinearActionStore(LinearClient(args.api_key_file), args.workspace_id, args.team_id, args.journal, args.backlog_state_id)
            result = import_one(report, args.source_record_id, store)
            print(json.dumps(asdict(result), indent=2))
            return 0
        if args.input_json:
            source = JSONCalendarSource(args.input_json)
            result = preview(source, args.calendar_id, args.start_date)
        else:
            session = authorized_session(args.token_file)
            try:
                result = preview(GoogleCalendarSource(session), args.calendar_id, args.start_date)
            finally:
                session.close()
        write_report(result, args.output_dir)
        print(f'Complete: {result["matching_events"]} matching events; {result["action_count"]} actions.')
        for row in result["daily_stats"]:
            print(f'{row["date"]}: {row["matching_events"]} matching events; {row["action_items"]} actions')
        print(f"Report: {(args.output_dir / 'report.html').resolve()}")
        return 0
    except (SourceError, StoreError, OSError) as exc:
        suffix = ("Authorization did not complete."
                  if args.command == "auth" else
                  "No successful report for this run. Any prior report is unchanged or stale."
                  if args.command == "preview" else "Operation did not complete. No automatic create retry was sent.")
        print(f"ERROR: {exc}\n{suffix}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
