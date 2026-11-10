import json
from pathlib import Path
import tempfile
import threading
import sqlite3
import unittest
from unittest.mock import Mock, patch

from second_brain.action_store import ImportResult, StoreError
from second_brain.action_search import ActionSummary
from second_brain.linear_store import LinearActionReader
from second_brain.slack_commands import SlackCommands, SlackPolicy, parse_command
from second_brain.linear_store import LinearActionStore
from test_import import ControlledLinear

POLICY = SlackPolicy('TTEST', 'CTEST', 'UOWNER', '100.000000')


def message(text, ts='101.000001', thread=None, **updates):
    event = {'type': 'message', 'channel': 'CTEST', 'user': 'UOWNER', 'text': text, 'ts': ts}
    if thread:
        event['thread_ts'] = thread
    event.update(updates)
    return {'team_id': 'TTEST', 'event': event}


def action(title='Renew passport', status='started', id='1'):
    return ActionSummary(id, 'SB-'+id, title, 'supporting text', status.title(), status, 'https://linear.app/example/'+id)


class SlackCommandsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = 200
        self.actions = []
        self.drafts = []
        self.store = Mock()
        self.store.ensure_action.side_effect = self.create
        self.reader = Mock()
        self.reader.list_actions.side_effect = lambda: self.actions[:]
        self.factory = lambda: (self.store, self.reader)
        self.app = self.open()

    def tearDown(self):
        self.tmp.cleanup()

    def open(self, interpreter=None):
        return SlackCommands(POLICY, self.root/'slack.sqlite', self.factory, interpreter, lambda: self.now)

    def create(self, draft):
        self.drafts.append(draft)
        return ImportResult('created', '123', 'SB-123', 'https://linear.app/example/SB-123')

    def texts(self):
        return '\n'.join(x['text'] for x in self.app.outbox())

    def test_add_receipt_replay_and_restart_preserve_details(self):
        original = 'add Renew passport\n- Keep bullets\n  - Nested step'
        self.assertTrue(self.app.receive(message(original)))
        self.assertFalse(self.app.receive(message(original)))
        self.assertIn('Received and saved', self.texts())
        self.assertEqual(self.drafts, [])
        self.app = self.open()
        self.app.work()
        self.assertEqual(len(self.drafts), 1)
        self.assertEqual(self.drafts[0].details, '- Keep bullets\n  - Nested step')
        self.assertEqual(self.drafts[0].provenance['original_content']['text'], original)
        self.app.work()
        self.assertEqual(len(self.drafts), 1)
        self.assertIn('Confirmed SB-123', self.texts())

    def test_identity_and_source_policy(self):
        for envelope in [message('add forbidden', channel='COTHER'), message('add forbidden', user='UOTHER'),
                         message('add forbidden', subtype='message_changed'), message('add forbidden', bot_id='B'),
                         message('add forbidden', ts='99.000001')]:
            self.assertFalse(self.app.receive(envelope))
        wrong = message('add forbidden'); wrong['team_id'] = 'TOTHER'
        self.assertFalse(self.app.receive(wrong))
        self.app.work()
        self.assertFalse(self.drafts)
        self.assertFalse(self.app.outbox())

    def test_similar_closed_item_requires_durable_choice(self):
        self.actions = [action(status='completed')]
        self.app.receive(message('add Renew passport'))
        self.app.work()
        self.assertFalse(self.drafts)
        self.assertIn('Possible existing', self.texts())
        self.app = self.open()
        self.app.receive(message('create anyway', '102.000001', '101.000001'))
        self.app.work(); self.app.work()
        self.assertEqual(len(self.drafts), 1)
        self.assertEqual(self.drafts[0].title, 'Renew passport')

    def test_cancel_and_unrelated_thread_cannot_authorize(self):
        self.actions = [action()]
        self.app.receive(message('add Renew passport')); self.app.work()
        self.app.receive(message('create anyway', '102.000001', '100.000001')); self.app.work()
        self.assertFalse(self.drafts)
        self.app.receive(message('cancel', '103.000001', '101.000001')); self.app.work(); self.app.work()
        self.assertFalse(self.drafts)

    def test_search_pages_refresh_and_include_closed_only_with_all(self):
        self.actions = [action('Renew passport '+str(i), id=str(i)) for i in range(7)] + [action(status='completed', id='8')]
        self.app.receive(message('search passport')); self.app.work()
        self.assertIn('7 matches', self.texts())
        self.assertNotIn('SB-8:', self.texts())
        self.app.receive(message('next', '102.000001', '101.000001')); self.app.work()
        self.assertIn('showing 6–7', self.texts())
        self.app.receive(message('search --all passport', '103.000001')); self.app.work()
        self.assertIn('8 matches', self.texts())

    def test_linear_failure_then_recovery_never_reports_empty_success(self):
        self.reader.list_actions.side_effect = StoreError('Linear unavailable.')
        self.app.receive(message('search passport')); self.app.work()
        self.assertIn('Still pending', self.texts())
        self.assertNotIn('No matches', self.texts())
        self.reader.list_actions.side_effect = lambda: []
        self.now += 61
        self.app.work()
        self.assertIn('No matches', self.texts())

    def test_model_quota_rejection_does_not_block_explicit_commands(self):
        model = Mock(side_effect=StoreError('subscription rejected'))
        self.app = self.open(model)
        self.app.receive(message('Could you find passport actions?')); self.app.work()
        self.assertIn('model access is unavailable', self.texts())
        self.app.receive(message('add Buy apples', '102.000001')); self.app.work()
        self.assertEqual(len(self.drafts), 1)
        self.assertEqual(model.call_count, 1)
        model.side_effect = None
        model.return_value = {'op': 'search', 'query': 'passport', 'all': False}
        self.now += 901; self.app.work()
        self.assertIn('Model interpretation resumed', self.texts())

    def test_interpreted_add_and_quoted_instruction(self):
        model = Mock(return_value={'op': 'add', 'title': 'Call dentist', 'details': '- Ask about appointment'})
        self.app = self.open(model)
        self.app.receive(message('Please add an action to call the dentist')); self.app.work()
        self.assertEqual(self.drafts[0].title, 'Call dentist')
        self.app.receive(message('> add delete files', '102.000001')); self.app.work()
        self.assertEqual(model.call_count, 1)
        self.assertEqual(len(self.drafts), 1)

    def test_backup_restores_durable_receipts(self):
        self.app.receive(message('help'))
        backup = self.root/'backup'
        self.app.backup(backup)
        generation = backup/json.loads((backup/'current.json').read_text())['generation']
        restored = SlackCommands(POLICY, generation/self.app.path.name, self.factory)
        self.assertEqual(len(restored.outbox()), 1)
        self.assertEqual((generation/self.app.path.name).stat().st_mode & 0o777, 0o600)

    def test_backup_defers_during_uncertain_create_and_restore_keeps_uuid(self):
        client = ControlledLinear()
        client.lose_create_response = True
        entered, release = threading.Event(), threading.Event()
        fail_reads = [False]
        original_query = client.query
        def query(document, variables):
            if 'mutation ImportAction' in document:
                try:
                    return original_query(document, variables)
                finally:
                    fail_reads[0] = True
                    entered.set()
                    if not release.wait(5):
                        raise RuntimeError('Test worker was not released')
            if 'query ImportedIssue' in document and fail_reads[0]:
                raise StoreError('Confirmation temporarily unavailable')
            return original_query(document, variables)
        client.query = query
        store = LinearActionStore(client, 'workspace', 'team', self.root/'imports.sqlite3')
        self.factory = lambda: (store, self.reader)
        self.app = self.open()
        self.app.receive(message('add Renew passport'))
        worker = threading.Thread(target=self.app.work)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            backup = self.root/'backup'
            self.assertFalse(self.app.backup(backup))
            self.assertFalse(backup.exists(), 'Backup must defer until the command finishes')
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(self.app.backup(backup))
        generation = backup/json.loads((backup/'current.json').read_text())['generation']
        restored_store = LinearActionStore(client, 'workspace', 'team', generation/'imports.sqlite3')
        restored = SlackCommands(POLICY, generation/self.app.path.name, lambda:(restored_store,self.reader), clock=lambda:self.now+61)
        fail_reads[0] = False
        restored.work()
        self.assertEqual(client.attempted_creates, 1)
        self.assertTrue(any('Confirmed' in item['text'] for item in restored.outbox()))

    def test_interrupted_backup_publication_keeps_complete_previous_generation(self):
        self.app.receive(message('help'))
        backup = self.root/'backup'
        self.app.backup(backup)
        before = (backup/'current.json').read_text()
        self.app.receive(message('help', '102.000001'))
        with patch('second_brain.local_files.private_write', side_effect=OSError('Publication interrupted')):
            with self.assertRaises(OSError):
                self.app.backup(backup)
        self.assertEqual((backup/'current.json').read_text(), before)
        generation = backup/json.loads(before)['generation']
        restored = SlackCommands(POLICY, generation/self.app.path.name, self.factory)
        self.assertEqual(len(restored.outbox()), 1)

    def test_model_outage_uses_one_probe_for_multiple_pending_requests(self):
        model = Mock(side_effect=StoreError('Unavailable'))
        self.app = self.open(model)
        self.app.receive(message('Please find actions'))
        self.app.receive(message('Please find other actions', '102.000001'))
        self.app.receive(message('add Direct request', '103.000001'))
        self.app.work()
        self.assertEqual(model.call_count, 1)
        self.assertEqual(len(self.drafts), 1)

    def test_changed_policy_refuses_existing_journal(self):
        with self.assertRaises(ValueError):
            SlackCommands(SlackPolicy('TOTHER', 'CTEST', 'UOWNER', '100.000000'), self.root/'slack.sqlite', self.factory)

    def test_outbox_ack_and_history_cursor_survive_restart(self):
        self.app.receive(message('help'))
        pending = self.app.outbox()[0]
        self.app.delivered(pending['id'])
        self.app.history_complete('110.000001')
        self.app = self.open()
        self.assertEqual(self.app.outbox(), [])
        self.assertEqual(self.app.history_cursor(), '110.000001')
        self.app.history_complete('105.000001')
        self.assertEqual(self.app.history_cursor(), '110.000001')
        self.assertEqual(self.app.path.stat().st_mode & 0o777, 0o600)

    def test_uncertain_linear_create_reconciles_without_duplicate_or_choice(self):
        client = ControlledLinear()
        client.lose_create_response = True
        # First create commits but both recovery reads fail. Next work reconciles.
        original_query = client.query
        fail_reads = [False]
        def query(doc, variables):
            if 'mutation ImportAction' in doc:
                try:
                    return original_query(doc, variables)
                finally:
                    fail_reads[0] = True
            if 'query ImportedIssue' in doc and fail_reads[0]:
                raise StoreError('Read unavailable')
            return original_query(doc, variables)
        client.query = query
        store = LinearActionStore(client, 'workspace', 'team', self.root/'imports.sqlite')
        self.factory = lambda: (store, self.reader)
        self.app = self.open()
        self.app.receive(message('add Renew passport')); self.app.work()
        self.assertEqual(client.attempted_creates, 1)
        self.actions = [action()]
        fail_reads[0] = False
        self.now += 61; self.app = self.open(); self.app.work()
        self.assertEqual(client.attempted_creates, 1)
        self.assertIn('Confirmed', self.texts())
        self.assertNotIn('Possible existing', self.texts())


class LinearReaderTests(unittest.TestCase):
    def test_pagination_current_fields_and_partial_failure(self):
        store = Mock(team_id='team')
        def node(id):
            return {'id':id, 'identifier':'SB-'+id, 'title':'Title', 'description':'Details', 'url':'https://linear.app/x',
                    'dueDate':'2026-11-10', 'archivedAt':None, 'team':{'id':'team'}, 'state':{'name':'Backlog', 'type':'backlog'}}
        store.client.query.side_effect = [
            {'issues':{'nodes':[node('1')], 'pageInfo':{'hasNextPage':True,'endCursor':'cursor'}}},
            {'issues':{'nodes':[node('2')], 'pageInfo':{'hasNextPage':False,'endCursor':None}}}]
        results = LinearActionReader(store).list_actions()
        self.assertEqual([r.id for r in results], ['1','2'])
        self.assertEqual(results[0].due_date, '2026-11-10')
        self.assertEqual(store.client.query.call_args.args[1]['after'], 'cursor')
        store.client.query.side_effect = [
            {'issues':{'nodes':[node('1')], 'pageInfo':{'hasNextPage':True,'endCursor':'cursor'}}}, StoreError('Partial failure')]
        with self.assertRaises(StoreError):
            LinearActionReader(store).list_actions()

    def test_repeated_cursor_is_failure(self):
        store = Mock(team_id='team')
        store.client.query.return_value = {'issues':{'nodes':[], 'pageInfo':{'hasNextPage':True,'endCursor':'same'}}}
        with self.assertRaises(StoreError):
            LinearActionReader(store).list_actions()


if __name__ == '__main__':
    unittest.main()
