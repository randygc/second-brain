import contextlib
from copy import deepcopy
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from second_brain.action_store import StoreError, import_batch
from second_brain.cli import main
from second_brain.google_calendar import GoogleCalendarSource
from second_brain.linear_store import LinearActionStore
from second_brain.preview import preview
from second_brain.source_lifecycle import review_deleted_sources
from test_import import ControlledLinear
from test_preview import MemorySource, event


class Response:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return deepcopy(self.body)


class CalendarSession:
    """The real Google adapter sees raw HTTP responses, including tombstones."""
    def __init__(self, records, metadata_status=200):
        self.records, self.metadata_status = records, metadata_status
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if '/events/' not in url:
            return Response(self.metadata_status, {'id': 'fixture'})
        record = url.rsplit('/', 1)[-1]
        value = self.records[record]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            return Response(*value)
        return Response(200, value)

    def close(self):
        pass


def initial_report():
    return preview(MemorySource([
        event('deleted', description='First action\nSecond action'),
        event('outside', description='Retain outside-window action'),
        event('series_occurrence', description='Recurring action', recurringEventId='series'),
    ]), 'fixture', date(2026, 9, 28))


def statuses():
    return {'deleted': {'id': 'deleted', 'status': 'cancelled'},
            'outside': {'id': 'outside', 'status': 'confirmed'},
            'series': {'id': 'series', 'status': 'confirmed'}}


class SourceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'journal.sqlite3'
        self.client = ControlledLinear()
        self.store = LinearActionStore(self.client, 'workspace', 'team', self.path)
        import_batch(initial_report(), self.store)
        for issue in self.client.issues.values():
            issue.update(title='User title', description='User details', state={'id': 'done'})
        self.saved = deepcopy(self.client.issues)

    def check(self, records=None, execute=True, metadata_status=200):
        session = CalendarSession(records or statuses(), metadata_status)
        result = review_deleted_sources(GoogleCalendarSource(session), self.store, 'fixture', execute=execute)
        return result, session

    def test_confirmed_tombstone_flags_all_original_actions_once_and_preserves_fields(self):
        for _ in range(2):
            result, session = self.check()
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['counts'], {'active': 2, 'planned': 0, 'flagged': 1, 'failed': 0})
            self.assertEqual(result['affected_existing_actions'], 2)
        self.assertEqual(len(self.client.comments), 2)
        self.assertEqual(self.client.issues, self.saved)
        self.assertTrue(all('deleted or cancelled — unresolved' in c['body'] for c in self.client.comments.values()))
        self.assertTrue(all('Unavailable in source' in c['body'] for c in self.client.comments.values()))
        self.assertEqual(self.client.attempted_creates, 4)
        # A recurring master is checked; an absent/cancelled occurrence cannot delete a series.
        urls = [url for url, _ in session.calls]
        self.assertTrue(any(url.endswith('/events/series') for url in urls))
        self.assertFalse(any(url.endswith('/events/series_occurrence') for url in urls))

    def test_default_plan_reads_without_posting_comments(self):
        result, _ = self.check(execute=False)
        self.assertEqual(result['counts']['planned'], 1)
        self.assertEqual(result['counts']['flagged'], 0)
        self.assertFalse(self.client.comments)
        self.assertEqual(self.client.issues, self.saved)

    def test_full_series_cancellation_flags_series_action(self):
        records = statuses()
        records['deleted'] = {'id': 'deleted', 'status': 'confirmed'}
        records['series'] = {'id': 'series', 'status': 'cancelled', 'updated': '2026-10-27T12:00:00Z'}
        result, _ = self.check(records)
        self.assertEqual(result['affected_existing_actions'], 1)
        body = next(iter(self.client.comments.values()))['body']
        self.assertIn('source recurring series', body)
        self.assertIn('2026-10-27T12:00:00Z', body)

    def test_confirmed_410_deleted_is_evidence_and_does_not_duplicate_tombstone(self):
        self.check()
        records = statuses()
        records['deleted'] = (410, {'error': {'errors': [{'reason': 'deleted'}]}})
        result, _ = self.check(records)
        self.assertEqual(result['counts']['flagged'], 1)
        self.assertEqual(len(self.client.comments), 2)

    def test_404_access_expired_sync_and_failed_reads_never_infer_deletion(self):
        failures = [(404, {'error': {}}), (403, {'error': {}}),
                    (410, {'error': {'errors': [{'reason': 'fullSyncRequired'}]}}),
                    (500, {}), OSError('Connection failed'), (200, {'id': 'deleted'}),
                    (200, {'id': 'wrong', 'status': 'cancelled'})]
        for failure in failures:
            with self.subTest(failure=str(failure)):
                records = statuses()
                records['deleted'] = failure
                result, _ = self.check(records)
                self.assertEqual(result['status'], 'partial_failure')
                self.assertEqual(result['counts']['failed'], 1)
                self.assertFalse(self.client.comments)
                self.assertEqual(self.client.issues, self.saved)

    def test_calendar_access_failure_never_flags_any_action(self):
        result, _ = self.check(metadata_status=404)
        self.assertEqual(result['counts']['failed'], 3)
        self.assertFalse(self.client.comments)

    def test_occurrence_response_is_not_evidence_for_whole_series(self):
        records = statuses()
        records['deleted'] = {'id': 'deleted', 'status': 'confirmed'}
        records['series'] = {'id': 'series', 'status': 'cancelled', 'recurringEventId': 'parent'}
        result, _ = self.check(records)
        self.assertEqual(result['counts']['failed'], 1)
        self.assertFalse(self.client.comments)

    def test_lost_comment_response_reconciles_without_duplicate(self):
        class LostResponse(ControlledLinear):
            def query(self, document, variables):
                result = super().query(document, variables)
                if 'mutation ImportReviewComment' in document:
                    raise StoreError('Lost response')
                return result
        client = LostResponse()
        client.issues = deepcopy(self.client.issues)
        store = LinearActionStore(client, 'workspace', 'team', self.path)
        source = GoogleCalendarSource(CalendarSession(statuses()))
        for _ in range(2):
            self.assertEqual(review_deleted_sources(source, store, 'fixture', execute=True)['status'], 'complete')
        self.assertEqual(len(client.comments), 2)
        self.assertEqual(client.issues, self.saved)

    def test_record_budget_fails_before_any_source_read_or_comment(self):
        session = CalendarSession(statuses())
        with self.assertRaises(StoreError):
            review_deleted_sources(GoogleCalendarSource(session), self.store, 'fixture', execute=True, limit=1)
        self.assertFalse(session.calls)
        self.assertFalse(self.client.comments)

    def test_cli_partial_failure_is_saved_privately_and_returns_nonzero(self):
        records = statuses()
        records['deleted'] = (404, {})
        output = Path(self.tmp.name) / 'results.json'
        args = ['review-sources', '--calendar-id', 'fixture', '--workspace-id', 'workspace',
                '--team-id', 'team', '--journal', str(self.path), '--results-file', str(output)]
        with patch('second_brain.cli.authorized_session', return_value=CalendarSession(records)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 2)
        self.assertEqual(json.loads(output.read_text())['status'], 'partial_failure')
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.client.comments)

    def test_failed_read_does_not_block_confirmed_other_source_or_erase_state(self):
        records = statuses()
        records['deleted'] = (404, {})
        records['series'] = {'id': 'series', 'status': 'cancelled'}
        result, _ = self.check(records)
        self.assertEqual(result['status'], 'partial_failure')
        self.assertEqual(result['counts'], {'active': 1, 'planned': 0, 'flagged': 1, 'failed': 1})
        self.assertEqual(len(self.client.comments), 1)
        self.assertEqual(self.client.issues, self.saved)

    def test_journal_sources_are_scoped_to_calendar_and_destination(self):
        self.assertEqual(len(self.store.imported_sources('fixture')), 3)
        self.assertEqual(self.store.imported_sources('different-calendar'), [])
        other = LinearActionStore(self.client, 'other-workspace', 'team', self.path)
        self.assertEqual(other.imported_sources('fixture'), [])
