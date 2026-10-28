from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from second_brain.action_store import ActionDraft
from second_brain.linear_store import LinearActionStore
from second_brain.source_review import review_comments
from test_import import ControlledLinear


class ReadableReviewTests(unittest.TestCase):
    def original(self, title, name):
        return asdict(ActionDraft(name, title, "", {
            "source_type": "google_calendar", "calendar_id": "fixture", "source_record_id": "example",
            "source_event_id": "example", "recurring_series_id": None, "scheduled_date": "2026-09-28",
            "scheduled_start": "2026-09-28", "source_created_at": "2026-09-01T00:00:00Z",
            "source_updated_at": "2026-09-02T00:00:00Z",
            "original_content": {"title": "Actions", "description": "Setup grid\n15 minute timeframe, intraday."}}))

    def observation(self, description, title="Actions"):
        p = self.original("Setup grid", "first")["provenance"]
        return dict(p, original_content={"title": title, "description": description},
                    source_updated_at="2026-10-27T18:00:00Z")

    def test_live_adapter_seam_two_actions_become_one_with_bullet(self):
        from second_brain.action_store import ActionDraft
        originals = [self.original("Setup grid", "first"), self.original("15 minute timeframe, intraday.", "second")]
        observation = self.observation("Setup grid\n- 15 minute timeframe, intraday.")
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            store = LinearActionStore(client, "workspace", "team", Path(tmp) / "journal")
            ids = [store.ensure_action(ActionDraft(**d)).destination_id for d in originals]
            for issue in client.issues.values():
                issue.update(title="User title", description="User details", state={"id": "done"})
            saved = deepcopy(client.issues)
            for _ in range(2):
                result = store.review_source(observation)
                self.assertEqual(result.affected_actions, 2)
            comments = {c["issueId"]: c["body"] for c in client.comments.values()}
            self.assertEqual(len(comments), 2)
            first, second = [comments[i] for i in ids]
            self.assertIn("Setup grid\n\n- 15 minute timeframe, intraday.", first)
            self.assertIn("2026-10-27T18:00:00Z", first)
            self.assertNotIn("```json", first)
            self.assertIn("added as a bullet", second)
            self.assertIn("Suggested action: delete", second)
            self.assertEqual(client.issues, saved)

    def test_reorder_matches_names_instead_of_ordinals(self):
        old = [self.original("Setup grid", "first"), self.original("Another action", "second")]
        bodies = review_comments(old, self.observation("Another action\n- Its detail\nSetup grid\n- Grid detail"))
        self.assertIn("Setup grid\n\n- Grid detail", bodies[0])
        self.assertNotIn("Its detail", bodies[0])
        self.assertIn("Another action\n\n- Its detail", bodies[1])

    def test_ambiguous_renames_do_not_suggest_deletion_or_assign_by_position(self):
        old = [self.original("Old first", "first"), self.original("Old second", "second")]
        for body in review_comments(old, self.observation("New one\nNew two")):
            self.assertIn("could not be identified confidently", body)
            self.assertNotIn("Suggested action: delete", body)

    def test_title_defined_rename_and_html_details(self):
        old = self.original("Old name", "first")
        old["provenance"]["original_content"]["title"] = "Action: Old name"
        body = review_comments([old], self.observation("<ul><li>Supporting detail</li></ul>", "Action: Updated name"))[0]
        self.assertIn("Updated name\n\n* Supporting detail", body)
        self.assertNotIn("<li>", body)

    def test_missing_timestamp_is_not_invented(self):
        observation = self.observation("Setup grid\n- detail")
        observation["source_updated_at"] = None
        self.assertIn("Unavailable in source", review_comments([self.original("Setup grid", "first")], observation)[0])

    def test_unchanged_action_gets_no_comment_when_sibling_becomes_bullet(self):
        originals = [self.original("Setup grid", "first"),
                     self.original("15 minute timeframe, intraday.", "second"),
                     self.original("Research ideas", "third")]
        originals[2]["details"] = "-- Keep this question?\n-- Keep this step"
        observation = self.observation("Setup grid<br><ul><li>15 minute timeframe, intraday.</li></ul>"
                                       "<br>Research ideas<br>-- Keep this question?<br>-- Keep this step")
        with tempfile.TemporaryDirectory() as tmp:
            client = ControlledLinear()
            store = LinearActionStore(client, "workspace", "team", Path(tmp) / "journal")
            ids = [store.ensure_action(ActionDraft(**d)).destination_id for d in originals]
            result = store.review_source(observation)
            self.assertEqual(result.affected_actions, 2)
            self.assertFalse(any(c["issueId"] == ids[2] for c in client.comments.values()))

    def test_reorder_and_source_timestamp_alone_create_no_comments(self):
        originals = [self.original("Setup grid", "first"), self.original("Another action", "second")]
        self.assertEqual(review_comments(originals, self.observation("Another action<br>Setup grid")), [None, None])

    def test_real_detail_change_is_not_suppressed(self):
        original = self.original("Research ideas", "first")
        original["details"] = "-- Original question?"
        body = review_comments([original], self.observation("Research ideas\n-- Updated question?"))[0]
        self.assertIn("-- Updated question?", body)
