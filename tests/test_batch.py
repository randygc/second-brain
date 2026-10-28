import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from second_brain.action_store import StoreError, import_batch, plan_batch, select_title_action
from second_brain.linear_store import LinearActionStore
from second_brain.cli import main
from test_import import ControlledLinear, TestActionStore, report


class BatchTests(unittest.TestCase):
    def test_all_cases_import_once_and_match_prior_title_identity(self):
        r = report()
        store = TestActionStore()
        drafts = plan_batch(r)
        self.assertEqual(len(drafts), 21)
        title = select_title_action(r, "case-4")
        store.ensure_action(title)
        first = import_batch(r, store)
        self.assertEqual(first["counts"], {"created": 20, "already_imported": 1, "reconciled": 0, "changed": 0, "failed": 0})
        second = import_batch(r, store)
        self.assertEqual(second["counts"]["already_imported"], 21)
        self.assertEqual(len(store.actions), 21)
        case6 = [d for d in drafts if d.provenance["source_record_id"] == "case-6"]
        self.assertEqual(len(case6), 7)
        self.assertEqual(sum(l.startswith("-- ") for l in case6[3].details.splitlines()), 4)

    def test_identical_text_from_different_events_and_slots_stays_independent(self):
        r = report()
        for a in r["actions"]:
            if a["source_record_id"] != "case-4":
                a["text"] = "Same words"
        drafts = plan_batch(r)
        self.assertEqual(len({d.import_identity for d in drafts}), 21)

    def test_partial_run_reports_failures_and_resumes_safe_records(self):
        class FlakyStore(TestActionStore):
            failed = False
            def ensure_action(self, draft):
                if not self.failed and draft.provenance["source_record_id"] == "case-2":
                    self.failed = True
                    raise StoreError("Read-only preflight failed")
                return super().ensure_action(draft)
        store = FlakyStore()
        first = import_batch(report(), store)
        self.assertEqual(first["status"], "partial_failure")
        self.assertEqual(first["counts"]["created"], 20)
        self.assertEqual(first["counts"]["failed"], 1)
        second = import_batch(report(), store)
        self.assertEqual(second["counts"]["created"], 1)
        self.assertEqual(second["counts"]["already_imported"], 20)

    def test_cli_saves_partial_results_and_returns_nonzero_exit(self):
        class FailedStore(TestActionStore):
            def ensure_action(self, draft):
                if draft.provenance["source_record_id"] == "case-2":
                    raise StoreError("Controlled import failure")
                return super().ensure_action(draft)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "report.json"
            output = Path(tmp) / "results.json"
            source.write_text(json.dumps(report()))
            with patch("second_brain.cli.LinearClient"), patch("second_brain.cli.LinearActionStore", return_value=FailedStore()), contextlib.redirect_stdout(io.StringIO()):
                code = main(["import-batch", "--report", str(source), "--workspace-id", "workspace", "--team-id", "team",
                             "--api-key-file", str(Path(tmp) / "unused-key"), "--results-file", str(output), "--execute"])
            self.assertEqual(code, 2)
            result = json.loads(output.read_text())
            self.assertEqual(result["status"], "partial_failure")
            self.assertEqual(result["counts"]["failed"], 1)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_batch_lost_responses_reconcile_without_duplicate_creates(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            client.lose_create_response = True
            path = Path(tmp) / "imports.sqlite3"
            first = import_batch(report(), LinearActionStore(client, "workspace", "team", path))
            self.assertEqual(first["counts"]["reconciled"], 21)
            second = import_batch(report(), LinearActionStore(client, "workspace", "team", path))
            self.assertEqual(second["counts"]["already_imported"], 21)
            self.assertEqual(client.attempted_creates, 21)

    def test_corrupt_batch_rejected_before_any_write(self):
        r = report()
        r["actions"][-1]["source_action_ordinal"] = 0
        store = TestActionStore()
        with self.assertRaises(StoreError):
            import_batch(r, store)
        self.assertEqual(len(store.actions), 0)

    def test_noncontiguous_slots_are_rejected_before_writes(self):
        r = report()
        r["actions"][-1]["source_action_ordinal"] = 99
        store = TestActionStore()
        with self.assertRaisesRegex(StoreError, "ordinals"):
            import_batch(r, store)
        self.assertFalse(store.actions)

    def test_budget_exhaustion_before_create_allows_safe_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            client.remaining = 1
            path = Path(tmp) / "imports.sqlite3"
            first = import_batch(report(), LinearActionStore(client, "workspace", "team", path))
            self.assertEqual(first["counts"]["failed"], 21)
            self.assertEqual(client.attempted_creates, 0)
            client.remaining = 100
            second = import_batch(report(), LinearActionStore(client, "workspace", "team", path))
            self.assertEqual(second["counts"]["created"], 21)

    def test_linear_full_batch_preserves_edits_and_normalized_bullets(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            client.normalize_markdown = True
            journal = Path(tmp) / "imports.sqlite3"
            first = import_batch(report(), LinearActionStore(client, "workspace", "team", journal))
            self.assertEqual(first["counts"]["failed"], 0)
            self.assertEqual(first["counts"]["created"], 21)
            changed = next(iter(client.issues.values()))
            changed.update(title="User title", description="User details", state={"id": "done", "type": "completed"})
            second = import_batch(report(), LinearActionStore(client, "workspace", "team", journal))
            self.assertEqual(second["counts"]["already_imported"], 21)
            self.assertEqual(client.attempted_creates, 21)
            self.assertEqual(changed["title"], "User title")
            self.assertEqual(changed["description"], "User details")
            self.assertEqual(changed["state"]["id"], "done")

    def test_parentless_content_flag_and_full_text_are_stored(self):
        r = report()
        a = r["actions"][0]
        a["text"] = "-- orphan " + "long content " * 30
        a["review_flags"] = ["parentless_supporting_content"]
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            result = import_batch(r, LinearActionStore(client, "workspace", "team", Path(tmp) / "imports.sqlite3"))
            self.assertEqual(result["counts"]["failed"], 0)
            issue = client.issues[result["results"][0]["destination_id"]]
            self.assertLessEqual(len(issue["title"]), 255)
            self.assertIn(a["text"], issue["description"])
            self.assertIn("parentless_supporting_content", issue["description"])

    def test_changed_source_cannot_create_new_ordinal_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            path = Path(tmp) / "imports.sqlite3"
            import_batch(report(), LinearActionStore(client, "workspace", "team", path))
            changed = report()
            for action in changed["actions"]:
                if action["source_record_id"] == "case-6":
                    action["original_content"]["description"] += "\nNew content"
            changed.pop("observed_records", None)
            changed.pop("source_records", None)
            result = import_batch(changed, LinearActionStore(client, "workspace", "team", path))
            self.assertEqual(result["counts"]["changed"], 7)
            self.assertEqual(len(client.comments), 0)
            self.assertEqual(client.attempted_creates, 21)

    def test_preflight_failure_does_not_block_a_safe_resume(self):
        class ReadFailure(ControlledLinear):
            fail_read = True
            def query(self, document, variables):
                if "query ImportedIssue" in document and self.fail_read:
                    self.fail_read = False
                    raise StoreError("Read failed before any create")
                return super().query(document, variables)
        with tempfile.TemporaryDirectory() as tmp:
            client = ReadFailure()
            path = Path(tmp) / "imports.sqlite3"
            first = import_batch(report(), LinearActionStore(client, "workspace", "team", path))
            self.assertEqual(first["counts"]["failed"], 1)
            second = import_batch(report(), LinearActionStore(client, "workspace", "team", path))
            self.assertEqual(second["counts"]["created"], 1)
            self.assertEqual(second["counts"]["already_imported"], 20)
            self.assertEqual(client.attempted_creates, 21)

    def test_changed_revision_is_recorded_once_and_preserves_user_fields(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            journal = Path(tmp) / "journal.sqlite3"
            store = LinearActionStore(client, "workspace", "team", journal)
            original = report()
            import_batch(original, store)
            for issue in client.issues.values():
                issue.update(title="My title", description="My notes", state={"id": "done"})
            baseline = deepcopy(client.issues)
            changed = deepcopy(original)
            changed.pop("observed_records", None)
            changed.pop("source_records", None)
            for a in changed["actions"]:
                if a["source_record_id"] == "case-6":
                    a["original_content"]["description"] += " changed"
                    a["source_updated_at"] = "2026-10-27T12:00:00Z"
            for _ in range(2):
                result = import_batch(changed, LinearActionStore(client, "workspace", "team", journal))
                self.assertEqual(result["changed_sources"], 1)
                self.assertEqual(result["affected_existing_actions"], 1)
            self.assertEqual(len(client.comments), 1)
            self.assertEqual(client.issues, baseline)
            self.assertTrue(all("Source changed — unresolved" in c["body"] for c in client.comments.values()))

    def test_source_no_longer_matching_still_flags_prior_actions(self):
        from second_brain.provenance import fingerprint
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            store = LinearActionStore(client, "workspace", "team", Path(tmp) / "journal")
            r = report()
            import_batch(r, store)
            observation = dict(r["source_records"][0])
            observation.pop("original_content")
            observation["content_fingerprint"] = fingerprint({"title": "No longer action", "description": ""})
            observation["eligible"] = False
            empty = dict(r, actions=[], action_count=0, observed_records=[observation],
                         daily_stats=[dict(d, action_items=0) for d in r["daily_stats"]])
            result = import_batch(empty, store)
            self.assertEqual(result["changed_sources"], 1)
            self.assertGreater(len(client.comments), 0)
            self.assertEqual(len(client.issues), 21)

    def test_recurring_later_window_keeps_initial_date(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            journal = Path(tmp) / "journal"
            r = report()
            for a in r["actions"]:
                a["recurring_series_id"] = a["source_record_id"]
            r.pop("observed_records", None)
            r.pop("source_records", None)
            import_batch(r, LinearActionStore(client, "workspace", "team", journal))
            saved = deepcopy(client.issues)
            for a in r["actions"]:
                a["scheduled_date"] = "2026-10-01"
                a["scheduled_start"] = "2026-10-01"
                a["source_event_id"] += "_later"
                a["source_updated_at"] = "2026-10-27T12:00:00Z"
            result = import_batch(r, LinearActionStore(client, "workspace", "team", journal))
            self.assertEqual(result["counts"]["already_imported"], 21)
            self.assertEqual(result["changed_sources"], 0)
            self.assertEqual(client.issues, saved)

    def test_lost_comment_response_reconciles_without_duplicate(self):
        class LostComment(ControlledLinear):
            def query(self, document, variables):
                result = super().query(document, variables)
                if "mutation ImportReviewComment" in document:
                    raise StoreError("Lost comment response")
                return result
        with tempfile.TemporaryDirectory() as tmp:
            client = LostComment()
            store = LinearActionStore(client, "workspace", "team", Path(tmp) / "journal")
            r = report()
            import_batch(r, store)
            observation = dict(r["source_records"][0])
            observation["original_content"] = {"title": "Action: changed", "description": "new"}
            first = store.review_source(observation)
            second = store.review_source(observation)
            self.assertEqual(first.outcome, "changed")
            self.assertEqual(second, first)
            self.assertEqual(len(client.comments), first.affected_actions)

    def test_comment_failure_never_retries_uncertain_write(self):
        class FailedComment(ControlledLinear):
            attempts = 0
            def query(self, document, variables):
                if "mutation ImportReviewComment" in document:
                    self.attempts += 1
                    raise StoreError("Failed comment")
                return super().query(document, variables)
        with tempfile.TemporaryDirectory() as tmp:
            client = FailedComment()
            store = LinearActionStore(client, "workspace", "team", Path(tmp) / "journal")
            r = report()
            import_batch(r, store)
            observation = dict(r["source_records"][0])
            observation["original_content"] = {"title": "Action: changed", "description": "new"}
            for _ in range(2):
                with self.assertRaises(StoreError):
                    store.review_source(observation)
            self.assertEqual(client.attempts, 1)


if __name__ == "__main__":
    unittest.main()
