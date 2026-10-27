"""Run extraction without an agent, browser automation, or destination writes."""

import argparse
from datetime import date
from pathlib import Path
import sys

from .google_calendar import (GoogleCalendarSource, JSONCalendarSource,
                              authorize, authorized_session)
from .preview import SourceError, preview
from .report import write_report


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
    args = parser.parse_args(argv)
    try:
        if args.command == "auth":
            authorize(args.client_secrets, args.token_file, args.include_shared)
            print(f"Read-only credentials saved locally to {args.token_file}.")
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
    except (SourceError, OSError) as exc:
        suffix = ("Authorization did not complete."
                  if args.command == "auth" else
                  "No successful report for this run. Any prior report is unchanged or stale.")
        print(f"ERROR: {exc}\n{suffix}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
