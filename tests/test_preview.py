import contextlib
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest

from second_brain.cli import main
from second_brain.google_calendar import GoogleCalendarSource, JSONCalendarSource
from second_brain.preview import CalendarWindow, SourceError, preview
from second_brain.report import render_html


FIXTURE = Path(__file__).parent / "fixtures" / "calendar_cases.json"
START = date(2026, 9, 28)


class MemorySource:
    def __init__(self, events, timezone="America/Los_Angeles"):
        self.events, self.timezone = events, timezone

    def read_window(self, calendar_id, start, days):
        return CalendarWindow(calendar_id, "Test calendar", self.timezone, self.events)


def event(id, title="Action", description="Do a thing", start="2026-09-28T12:00:00-07:00", **extra):
    return {"id": id, "summary": title, "description": description,
            "start": {"dateTime": start}, **extra}


class PreviewTests(unittest.TestCase):
    def test_all_six_historical_cases_through_application(self):
        result = preview(JSONCalendarSource(FIXTURE), "fixture", START)
        self.assertEqual([r["action_count"] for r in result["source_records"]], [1, 1, 3, 1, 8, 7])
        self.assertEqual(result["action_count"], 21)
        by_id = lambda id: [a for a in result["actions"] if a["source_record_id"] == id]
        self.assertIn("https://example.com/team/", by_id("case-2")[0]["text"])
        self.assertIn("https://example.com/video-one", by_id("case-4")[0]["details"])
        electrical = by_id("case-5")[1]
        self.assertEqual(sum(l.lstrip().startswith("* ") for l in electrical["details"].splitlines()), 5)
        case6 = by_id("case-6")
        self.assertEqual(sum(l.startswith("-- ") for l in case6[3]["details"].splitlines()), 4)
        self.assertEqual(case6[4]["text"].strip(), "Call the learner at 7pm.")
        self.assertEqual(case6[-1]["text"].strip(), "Submit the learner time sheet.")
        self.assertEqual([d["action_items"] for d in result["daily_stats"]], [21, 0, 0, 0, 0])

    def test_first_word_matching_and_title_details(self):
        titles = ["Action", "aCTions", "action: Call plumber", "action -- Call plumber",
                  "Action123", "Actionable ideas", "My Action", " Action"]
        result = preview(MemorySource([event(str(i), t, "Detail one\nDetail two") for i, t in enumerate(titles)]), "test", START)
        self.assertEqual(result["matching_events"], 4)
        title_items = [a for a in result["actions"] if a["text"] == "Call plumber"]
        self.assertEqual(len(title_items), 2)
        self.assertEqual(title_items[0]["details"], "Detail one\nDetail two")

    def test_source_newlines_bullets_long_prose_and_blank_lines(self):
        long_line = "Several sentences. " * 200
        raw = long_line + "\r\nNext action\r-- one\r\n\r\n  continuation\nFinal -- inline\n"
        result = preview(MemorySource([event("a", description=raw)]), "test", START)
        self.assertEqual([a["text"] for a in result["actions"]], [long_line, "Next action", "Final -- inline"])
        self.assertIn("-- one\n\n  continuation", result["actions"][1]["details"])
        self.assertEqual(result["actions"][0]["original_content"]["description"], raw)

    def test_parentless_bullets_preserve_entire_description(self):
        raw = "-- orphan\nNext line\n  * child"
        result = preview(MemorySource([event("a", description=raw)]), "test", START)
        self.assertEqual(result["action_count"], 1)
        self.assertEqual(result["actions"][0]["text"], raw)
        self.assertIn("parentless_supporting_content", result["actions"][0]["review_flags"])

    def test_leading_double_dash_needs_no_space(self):
        result = preview(MemorySource([event("a", description="Main action\n--step without space\nNext -- inline")]), "test", START)
        self.assertEqual(result["action_count"], 2)
        self.assertEqual(result["actions"][0]["details"], "--step without space")

    def test_html_structural_breaks_and_formatting(self):
        raw = '<div>First sentence. Still same action.</div><div>Second<br>Third</div><ul><li>A step <a href="https://example.com">link</a></li><li>Another</li></ul><div><b>Fourth</b></div>'
        result = preview(MemorySource([event("a", description=raw)]), "test", START)
        self.assertEqual([a["text"] for a in result["actions"]], ["First sentence. Still same action.", "Second", "Third", "**Fourth**"])
        self.assertIn("[link](https://example.com)", result["actions"][2]["details"])
        self.assertEqual(result["actions"][0]["original_content"]["description"], raw)

    def test_html_pretty_printing_is_not_indentation_of_action(self):
        raw = '<div>First</div>\n  <div>Second</div>\n <ul>\n <li>Step</li>\n </ul>'
        result = preview(MemorySource([event("a", description=raw)]), "test", START)
        self.assertEqual([a["text"] for a in result["actions"]], ["First", "Second"])
        self.assertIn("* Step", result["actions"][1]["details"])

    def test_inline_html_does_not_erase_original_newlines(self):
        raw = 'Read <a href="https://example.com">this</a>\nCall plumber\n-- Ask about warranty'
        result = preview(MemorySource([event("a", description=raw)]), "test", START)
        self.assertEqual([a["text"] for a in result["actions"]], ['Read [this](https://example.com)', 'Call plumber'])
        self.assertEqual(result["actions"][1]["details"], '-- Ask about warranty')

    def test_recurrence_counts_earliest_and_independent_identical_content(self):
        events = [event("later", start="2026-09-29T12:00:00-07:00", recurringEventId="series"),
                  event("earlier", recurringEventId="series"), event("independent"),
                  event("cancelled", status="cancelled")]
        result = preview(MemorySource(events), "test", START)
        self.assertEqual(result["matching_events"], 3)
        self.assertEqual(result["action_count"], 2)
        self.assertEqual([d["matching_events"] for d in result["daily_stats"]], [2, 1, 0, 0, 0])
        self.assertEqual([d["action_items"] for d in result["daily_stats"]], [2, 0, 0, 0, 0])
        recurring = next(a for a in result["actions"] if a["recurring_series_id"])
        self.assertEqual(recurring["source_event_id"], "earlier")
        self.assertIsNone(recurring["source_created_at"])
        self.assertTrue(result["warnings"])

    def test_timezone_boundaries_overlap_and_all_day(self):
        events = [event("overlap", start="2026-09-27T23:59:00-07:00"),
                  event("first", start="2026-09-28T07:00:00Z"),
                  event("last", start="2026-10-03T06:59:59Z"),
                  event("outside", start="2026-10-03T07:00:00Z"),
                  {"id": "all-day", "summary": "Action", "description": "All day", "start": {"date": "2026-09-29"}}]
        result = preview(MemorySource(events), "test", START)
        self.assertEqual(result["matching_events"], 3)
        self.assertEqual([d["matching_events"] for d in result["daily_stats"]], [1, 1, 0, 0, 1])

    def test_original_creation_time_is_not_substituted(self):
        result = preview(MemorySource([event("a", created="2025-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z")]), "test", START)
        item = result["actions"][0]
        self.assertEqual(item["source_created_at"], "2025-01-01T00:00:00Z")
        self.assertEqual(item["source_updated_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(item["scheduled_date"], "2026-09-28")

    def test_empty_success_is_distinct_from_failure(self):
        result = preview(MemorySource([]), "test", START)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["daily_stats"]), 5)
        class BrokenSource:
            def read_window(self, *args):
                raise SourceError("incomplete retrieval")
        with self.assertRaises(SourceError):
            preview(BrokenSource(), "test", START)

    def test_cli_report_is_safe_repeatable_and_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["preview", "--calendar-id", "fixture", "--start-date", "2026-09-28", "--input-json", str(FIXTURE), "--output-dir", tmp]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
                first = (Path(tmp) / "report.json").read_bytes()
                self.assertEqual(main(args), 0)
            self.assertEqual((Path(tmp) / "report.json").read_bytes(), first)
            self.assertEqual((Path(tmp) / "report.json").stat().st_mode & 0o777, 0o600)
        report = preview(MemorySource([event("a", title='Action: <img src=x onerror=alert(1)>', description='<script>bad()</script>')]), "test", START)
        html = render_html(report)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src", html)
        self.assertIn("&lt;img", html)

    def test_cli_failed_input_leaves_prior_report_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.html"
            output.write_text("prior report")
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                code = main(["preview", "--calendar-id", "fixture", "--start-date", "2026-09-28", "--input-json", str(Path(tmp) / "missing.json"), "--output-dir", tmp])
            self.assertEqual(code, 1)
            self.assertIn("ERROR", errors.getvalue())
            self.assertEqual(output.read_text(), "prior report")


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class Session:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


class GoogleAdapterTests(unittest.TestCase):
    def test_raw_line_fidelity_pagination_and_dst_window(self):
        raw = "One\r\nTwo\n-- child"
        session = Session([Response({"id": "test", "timeZone": "America/Los_Angeles"}),
                           Response({"items": [event("one", description=raw, start="2026-10-31T12:00:00-07:00")], "nextPageToken": "next"}),
                           Response({"items": []})])
        result = preview(GoogleCalendarSource(session), "test", date(2026, 10, 31))
        self.assertEqual(result["action_count"], 2)
        self.assertEqual(result["actions"][0]["original_content"]["description"], raw)
        params = session.calls[1][1]["params"]
        self.assertEqual(params["timeMin"], "2026-10-31T00:00:00-07:00")
        self.assertEqual(params["timeMax"], "2026-11-05T00:00:00-08:00")
        self.assertEqual(session.calls[2][1]["params"]["pageToken"], "next")
        self.assertNotIn("q", params)  # Title filtering is local, not broad full-text search.

    def test_failure_after_first_page_never_returns_partial_success(self):
        session = Session([Response({"timeZone": "America/Los_Angeles"}),
                           Response({"items": [event("a")], "nextPageToken": "next"}), Response({}, 403)])
        with self.assertRaisesRegex(SourceError, "HTTP 403"):
            preview(GoogleCalendarSource(session), "test", START)

    def test_repeated_pagination_token_rejected(self):
        session = Session([Response({"timeZone": "America/Los_Angeles"}),
                           Response({"nextPageToken": "same"}), Response({"nextPageToken": "same"})])
        with self.assertRaisesRegex(SourceError, "pagination"):
            preview(GoogleCalendarSource(session), "test", START)


if __name__ == "__main__":
    unittest.main()
