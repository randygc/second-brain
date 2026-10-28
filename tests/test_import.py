import contextlib
from copy import deepcopy
from dataclasses import replace
from datetime import date
import io
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from second_brain.action_store import ImportResult, StoreError, import_one, select_title_action
from second_brain.cli import main
from second_brain.google_calendar import JSONCalendarSource
from second_brain.linear_store import LinearActionStore, LinearClient, destinations, issue_description
from second_brain.preview import preview


FIXTURE = Path(__file__).parent / "fixtures" / "calendar_cases.json"


def report():
    return preview(JSONCalendarSource(FIXTURE), "fixture", date(2026, 9, 28))


class TestActionStore:
    """Controlled second adapter using only the shared action-store interface."""

    def __init__(self):
        self.actions = {}

    def review_source(self, observation):
        from second_brain.action_store import SourceReview
        return SourceReview("unseen")

    def ensure_action(self, draft):
        if draft.import_identity in self.actions:
            return ImportResult("existing", draft.import_identity, "TEST-1", "https://example.com/action")
        self.actions[draft.import_identity] = draft
        return ImportResult("created", draft.import_identity, "TEST-1", "https://example.com/action")


class ControlledLinear:
    """Controlled HTTP-client seam, modelling stored provider-visible records."""

    def __init__(self):
        self.issues = {}
        self.comments = {}
        self.attempted_creates = 0
        self.lose_create_response = False
        self.fail_create_before_commit = False
        self.workspace = "workspace"
        self.normalize_markdown = False
        self.states = [{"id": "backlog", "name": "Backlog", "type": "backlog"},
                       {"id": "done", "name": "Done", "type": "completed"}]

    def query(self, document, variables):
        if "query ImportDestination" in document:
            return {"organization": {"id": self.workspace}, "team": {"id": "team"}}
        if "query ImportBacklog" in document:
            return {"team": {"states": {"nodes": self.states, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
        if "query ImportedIssue" in document:
            issue = self.issues.get(variables["id"])
            return {"issues": {"nodes": [deepcopy(issue)] if issue else []}}
        if "query ImportReview(" in document:
            comment = self.comments.get(variables["id"])
            return {"issue": {"comments": {"nodes": [deepcopy(comment)] if comment else []}}}
        if "mutation ImportReviewComment" in document:
            p = variables["input"]
            self.comments[p["id"]] = deepcopy(p)
            return {"commentCreate": {"success": True, "comment": deepcopy(p)}}
        if "mutation ImportAction" in document:
            self.attempted_creates += 1
            if self.fail_create_before_commit:
                raise StoreError("Connection failed")
            p = variables["input"]
            if p["id"] in self.issues:
                raise StoreError("Duplicate ID")
            issue = {"id": p["id"], "identifier": "TEST-1", "url": "https://example.com/issue/TEST-1",
                     "title": p["title"], "description": p["description"],
                     "team": {"id": p["teamId"]}, "state": {"id": p["stateId"], "type": "backlog", "name": "Backlog"}}
            self.issues[p["id"]] = issue
            if self.normalize_markdown:
                issue["description"] = issue["description"].replace("\n---\n##", "\n---\n\n##").replace("\n- Source:", "\n* Source:")
                issue["description"] = issue["description"].strip()
                # Canonicalize only the rendered body, not the JSON code fence.
                body, marker, metadata = issue["description"].partition("## Import provenance")
                body = re.sub(r"\]\((https?://[^\s)]+)\)", r"](<\1>)", body)
                body = re.sub(r"(?m)^--(?!-)", r"\\--", body)
                issue["description"] = body + marker + metadata
                issue["title"] = issue["title"].strip()
            if self.lose_create_response:
                raise StoreError("Lost mutation response")
            return {"issueCreate": {"success": True, "issue": deepcopy(issue)}}
        raise AssertionError("Unexpected operation")


class ImportTests(unittest.TestCase):
    def test_application_selects_only_explicit_title_action(self):
        store = TestActionStore()
        result = import_one(report(), "case-4", store)
        self.assertEqual(result.outcome, "created")
        self.assertEqual(len(store.actions), 1)
        draft = next(iter(store.actions.values()))
        self.assertEqual(draft.title, "loading tools for automated coding")
        self.assertIn("https://example.com/video-one", draft.details)
        self.assertEqual(draft.provenance["source_created_at"], "2026-09-01T09:00:00Z")
        self.assertEqual(draft.provenance["scheduled_date"], "2026-09-28")
        with self.assertRaises(StoreError):
            import_one(report(), "case-3", store)
        with self.assertRaises(StoreError):
            import_one(report(), "case-1", store)

    def test_identity_ignores_text_dates_and_destination_ids(self):
        original = report()
        first = select_title_action(original, "case-4")
        changed = deepcopy(original)
        action = next(a for a in changed["actions"] if a["source_record_id"] == "case-4")
        action["original_content"]["title"] = "Action: New words"
        action["text"] = "New words"
        action["scheduled_date"] = "2026-10-05"
        self.assertEqual(first.import_identity, select_title_action(changed, "case-4").import_identity)
        action["calendar_id"] = "another-source"
        self.assertNotEqual(first.import_identity, select_title_action(changed, "case-4").import_identity)

    def test_linear_create_then_rerun_preserves_native_edits_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            journal = Path(tmp) / "imports.sqlite3"
            store = LinearActionStore(client, "workspace", "team", journal)
            result = import_one(report(), "case-4", store)
            self.assertEqual(result.outcome, "created")
            issue = client.issues[result.destination_id]
            self.assertEqual(issue["state"]["id"], "backlog")
            self.assertIn('"source_created_at": "2026-09-01T09:00:00Z"', issue["description"])
            self.assertIn('"original_content"', issue["description"])
            issue.update(title="User edit", description="User notes", state={"id": "done", "type": "completed"})
            second = import_one(report(), "case-4", LinearActionStore(client, "workspace", "team", journal))
            self.assertEqual(second.outcome, "existing")
            self.assertEqual(second.destination_id, result.destination_id)
            self.assertEqual(issue["title"], "User edit")
            self.assertEqual(issue["description"], "User notes")
            self.assertEqual(issue["state"]["id"], "done")
            self.assertEqual(client.attempted_creates, 1)
            self.assertEqual(journal.stat().st_mode & 0o777, 0o600)

    def test_lost_create_response_reconciles_without_second_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            client.lose_create_response = True
            store = LinearActionStore(client, "workspace", "team", Path(tmp) / "imports.sqlite3")
            first = import_one(report(), "case-4", store)
            self.assertEqual(first.outcome, "reconciled")
            self.assertEqual(import_one(report(), "case-4", store).outcome, "existing")
            self.assertEqual(client.attempted_creates, 1)
            self.assertEqual(len(client.issues), 1)

    def test_linear_markdown_normalization_does_not_fail_semantic_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            client.normalize_markdown = True
            store = LinearActionStore(client, "workspace", "team", Path(tmp) / "imports.sqlite3")
            self.assertEqual(import_one(report(), "case-4", store).outcome, "created")
            self.assertEqual(client.attempted_creates, 1)

    def test_uncertain_absent_issue_is_not_recreated_on_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            client.fail_create_before_commit = True
            journal = Path(tmp) / "imports.sqlite3"
            with self.assertRaisesRegex(StoreError, "uncertain"):
                import_one(report(), "case-4", LinearActionStore(client, "workspace", "team", journal))
            client.fail_create_before_commit = False
            with self.assertRaisesRegex(StoreError, "No replacement"):
                import_one(report(), "case-4", LinearActionStore(client, "workspace", "team", journal))
            self.assertEqual(client.attempted_creates, 1)
            self.assertEqual(len(client.issues), 0)

    def test_explicit_workspace_and_backlog_checks_prevent_wrong_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            store = LinearActionStore(client, "WRONG", "team", Path(tmp) / "imports.sqlite3")
            with self.assertRaisesRegex(StoreError, "does not match"):
                import_one(report(), "case-4", store)
            client.states = []
            with self.assertRaisesRegex(StoreError, "Backlog"):
                import_one(report(), "case-4", LinearActionStore(client, "workspace", "team", Path(tmp) / "other.sqlite3"))
            self.assertEqual(client.attempted_creates, 0)

    def test_dry_run_needs_no_key_and_writes_no_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "report.json"
            source.write_text(json.dumps(report()))
            journal = Path(tmp) / "imports.sqlite3"
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = main(["import-one", "--report", str(source), "--source-record-id", "case-4",
                             "--workspace-id", "workspace", "--team-id", "team", "--journal", str(journal)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["mode"], "plan_only")
            self.assertFalse(journal.exists())

    def test_missing_source_timestamp_and_backticks_preserved_in_provenance(self):
        draft = select_title_action(report(), "case-4")
        draft.provenance["source_created_at"] = None
        draft.provenance["original_content"]["description"] += '\n```\nembedded fence'
        text = issue_description(draft)
        self.assertIn("Unavailable (not substituted)", text)
        self.assertIn('"source_created_at": null', text)
        self.assertIn("````json", text)


class ProviderResponse:
    def __init__(self, data, headers=None):
        self.data = io.BytesIO(json.dumps(data).encode())
        self.headers = headers or {}

    def read(self, *args):
        return self.data.read(*args)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class ProviderFailureTests(unittest.TestCase):
    def test_utf8_bom_in_key_file_is_not_sent_in_authorization_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "key"
            key.write_text("\ufeffsynthetic-key-for-test", encoding="utf-8")
            client = LinearClient(key)
            def respond(request, **kwargs):
                self.assertEqual(request.get_header("Authorization"), "synthetic-key-for-test")
                return ProviderResponse({"data": {"ok": True}})
            with patch("urllib.request.build_opener") as opener:
                opener.return_value.open.side_effect = respond
                self.assertTrue(client.query("query Test", {})["ok"])

    def test_graphql_partial_data_is_rejected_without_leaking_error_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "key"
            key.write_text("synthetic-key-for-test")
            client = LinearClient(key)
            data = {"data": {"organization": {}}, "errors": [{"message": "sensitive-provider-detail"}]}
            with patch("urllib.request.build_opener") as opener:
                opener.return_value.open.return_value = ProviderResponse(data)
                with self.assertRaises(StoreError) as caught:
                    client.query("query Test { organization { id } }", {})
            self.assertNotIn("sensitive-provider-detail", str(caught.exception))
            self.assertNotIn("synthetic-key-for-test", str(caught.exception))

    def test_exhausted_provider_budget_stops_subsequent_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "key"
            key.write_text("synthetic-key-for-test")
            client = LinearClient(key)
            with patch("urllib.request.build_opener") as opener:
                opener.return_value.open.return_value = ProviderResponse({"data": {"ok": True}}, {"X-RateLimit-Requests-Remaining": "0"})
                self.assertTrue(client.query("query Test", {})["ok"])
                with self.assertRaisesRegex(StoreError, "budget exhausted"):
                    client.query("query Test", {})

    def test_destination_discovery_follows_all_team_pages(self):
        class PagedClient:
            def query(self, document, variables):
                return {"organization": {"id": "workspace", "name": "Test"}, "teams": {
                    "nodes": [{"id": "two" if variables["after"] else "one"}],
                    "pageInfo": {"hasNextPage": not variables["after"], "endCursor": "next"}}}
        self.assertEqual([t["id"] for t in destinations(PagedClient())["teams"]], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
