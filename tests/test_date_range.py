from datetime import date
import unittest

from second_brain.action_store import StoreError, import_batch, plan_batch
from second_brain.preview import SourceError, preview
from test_import import TestActionStore
from test_preview import MemorySource, event


class DateRangeTests(unittest.TestCase):
    def test_inclusive_multi_month_range_excludes_later_events(self):
        source = MemorySource([
            event('before', start='2025-11-12T23:59:59-08:00'),
            event('first', start='2025-11-13T00:00:00-08:00'),
            event('last', start='2026-10-28T23:59:59-07:00'),
            event('after', start='2026-10-29T00:00:00-07:00')])
        r = preview(source, 'fixture', date(2025, 11, 13), date(2026, 10, 28))
        self.assertEqual(len(r['daily_stats']), 350)
        self.assertEqual(r['action_count'], 2)
        self.assertEqual({a['source_record_id'] for a in r['actions']}, {'first', 'last'})
        store = TestActionStore()
        self.assertEqual(import_batch(r, store)['counts']['created'], 2)
        self.assertEqual(import_batch(r, store)['counts']['already_imported'], 2)

    def test_recurring_range_extracts_once_at_earliest_in_range_occurrence(self):
        r = preview(MemorySource([
            event('later', start='2026-10-01T09:00:00-07:00', recurringEventId='series'),
            event('earliest', start='2025-11-13T09:00:00-08:00', recurringEventId='series'),
        ]), 'fixture', date(2025, 11, 13), date(2026, 10, 28))
        self.assertEqual(r['matching_events'], 2)
        self.assertEqual(len(plan_batch(r)), 1)
        self.assertEqual(r['actions'][0]['scheduled_date'], '2025-11-13')

    def test_single_day_and_invalid_ranges(self):
        source = MemorySource([])
        r = preview(source, 'fixture', date(2026, 10, 28), date(2026, 10, 28))
        self.assertEqual(len(r['daily_stats']), 1)
        for end in [date(2026, 10, 27), date(2040, 1, 1)]:
            with self.assertRaises(SourceError):
                preview(source, 'fixture', date(2026, 10, 28), end)

    def test_incomplete_daily_range_cannot_be_imported(self):
        r = preview(MemorySource([]), 'fixture', date(2026, 10, 1), date(2026, 10, 28))
        r['daily_stats'].pop(10)
        with self.assertRaises(StoreError):
            plan_batch(r)

    def test_complex_details_preserve_literal_hierarchy_and_safe_title(self):
        from dataclasses import replace
        from second_brain.action_store import select_title_action
        from second_brain.linear_store import issue_description, description_matches, display_title
        from test_import import report
        draft = replace(select_title_action(report(), "case-4"), title="Multi\n  line title",
                        details="1. Parent\n  1. Child\n2) Next\n**Adjacent**emphasis")
        description = issue_description(draft)
        self.assertIn("```\n1. Parent\n  1. Child\n2) Next", description)
        self.assertEqual(display_title(draft), "Multi line title")
        self.assertTrue(description_matches(description, draft))
        self.assertFalse(description_matches(description.replace("  1. Child", "2. Child", 1), draft))
