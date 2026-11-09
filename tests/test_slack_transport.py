import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock

from second_brain.slack_commands import SlackCommands
from second_brain.slack_runtime import validate_intent
from second_brain.slack_transport import SlackTransport
from test_slack_commands import POLICY, message


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = SlackCommands(POLICY, Path(self.tmp.name)/'slack.sqlite', Mock())
        self.client = Mock()
        self.client.auth_test = AsyncMock(return_value={'team_id':'TTEST'})
        self.client.conversations_info = AsyncMock(return_value={'channel':{'is_private':True,'is_member':True,'is_shared':False}})
        self.client.chat_postMessage = AsyncMock(return_value={'ok':True,'ts':'200.000001'})
        self.transport = SlackTransport(self.app, self.client)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_offline_history_replay_and_cursor_commit(self):
        event = message('help')['event']
        self.client.conversations_history = AsyncMock(side_effect=[
            {'ok':True,'messages':[event], 'has_more':True,'response_metadata':{'next_cursor':'cursor'}},
            {'ok':True,'messages':[], 'has_more':False,'response_metadata':{}}])
        await self.transport.history()
        self.assertEqual(len(self.app.outbox()), 1)
        cursor = self.app.history_cursor()
        self.assertGreater(float(cursor), 100)
        self.client.conversations_history = AsyncMock(return_value={'ok':True,'messages':[event], 'has_more':False})
        await self.transport.history()
        self.assertEqual(len(self.app.outbox()), 1)

    async def test_partial_history_failure_does_not_advance_cursor(self):
        self.client.conversations_history = AsyncMock(side_effect=[
            {'ok':True,'messages':[message('help')['event']], 'has_more':True,'response_metadata':{'next_cursor':'cursor'}},
            RuntimeError('Offline')])
        with self.assertRaises(RuntimeError):
            await self.transport.history()
        self.assertEqual(self.app.history_cursor(), POLICY.activation_ts)
        self.assertEqual(len(self.app.outbox()), 1)

    async def test_history_failure_does_not_block_live_help(self):
        self.client.conversations_history = AsyncMock(side_effect=RuntimeError('No history'))
        self.app.receive(message('help'))
        await self.transport.tick()
        self.assertEqual(len(self.app.outbox()), 0)
        sent = [c.kwargs['text'] for c in self.client.chat_postMessage.call_args_list]
        self.assertTrue(any('Commands:' in text for text in sent))

    async def test_private_workspace_and_channel_verification(self):
        self.client.auth_test.return_value = {'team_id':'TOTHER'}
        with self.assertRaises(ValueError):
            await self.transport.verify()
        self.assertFalse(self.transport.ready)
        self.client.auth_test.return_value = {'team_id':'TTEST'}
        self.client.conversations_info.return_value = {'channel':{'is_private':False,'is_member':True}}
        with self.assertRaises(ValueError):
            await self.transport.verify()
        self.assertFalse(self.transport.ready)

    async def test_delivery_failure_retains_outbox_and_disables_mentions(self):
        self.app.receive(message('add <!channel>'))
        self.client.chat_postMessage.side_effect = RuntimeError('Delivery timeout')
        with self.assertRaises(RuntimeError):
            await self.transport.deliver()
        self.assertEqual(len(self.app.outbox()), 1)
        self.client.chat_postMessage.side_effect = None
        await self.transport.deliver()
        self.assertFalse(self.app.outbox())
        kwargs = self.client.chat_postMessage.call_args.kwargs
        self.assertEqual(kwargs['thread_ts'], '101.000001')
        self.assertFalse(kwargs['mrkdwn'])
        self.assertEqual(kwargs['parse'], 'none')
        self.assertFalse(kwargs['unfurl_links'])
        # Transport always escapes explicit mention markers in result text.
        with self.app.db() as db:
            self.app._notice(db, 'synthetic', '101.000001', 'mention', '<!channel> <@UOWNER>')
        await self.transport.deliver()
        self.assertEqual(self.client.chat_postMessage.call_args.kwargs['text'], '&lt;!channel&gt; &lt;@UOWNER&gt;')

    async def test_pending_choice_reply_recovered_from_retained_thread(self):
        from test_slack_commands import action
        store, reader = Mock(), Mock()
        reader.list_actions.return_value = [action()]
        self.app.store_factory = lambda: (store, reader)
        self.app.receive(message('add Renew passport'))
        self.app.work()
        self.assertEqual(self.app.pending_threads(), ['101.000001'])
        self.client.conversations_replies = AsyncMock(return_value={
            'ok':True, 'messages':[message('cancel','102.000001','101.000001')['event']]})
        await self.transport.recover_choices('103.000001', '104.000001')
        self.app.work()
        self.assertFalse(self.app.pending_threads())
        self.assertIn('Cancelled', '\n'.join(x['text'] for x in self.app.outbox()))
        self.assertEqual(self.client.conversations_replies.call_args.kwargs['oldest'], POLICY.activation_ts)

    async def test_missing_thread_permission_asks_repeat_once_per_boot(self):
        from test_slack_commands import action
        store, reader = Mock(), Mock()
        reader.list_actions.return_value = [action()]
        self.app.store_factory = lambda: (store, reader)
        self.app.receive(message('add Renew passport')); self.app.work()
        self.client.conversations_replies = AsyncMock(side_effect=RuntimeError('Scope unavailable'))
        await self.transport.recover_choices('100.000000', '104.000001')
        await self.transport.recover_choices('100.000000', '104.000001')
        repeat = [x for x in self.app.outbox() if 'please repeat' in x['text']]
        self.assertEqual(len(repeat), 1)
        self.assertEqual(self.app.pending_threads(), ['101.000001'])

    async def test_limited_history_warns(self):
        self.client.conversations_history = AsyncMock(return_value={'ok':True,'messages':[], 'is_limited':True})
        await self.transport.history()
        self.assertIn('limited retained history', self.app.outbox()[0]['text'])


class IntentTests(unittest.TestCase):
    def test_only_narrow_shapes_admitted(self):
        for value in [{'op':'run','command':'anything'}, {'op':'add','title':'x','details':'','tools':['shell']},
                      {'op':'search','query':'x','all':'false'}, {'op':'add','title':'a\nb','details':''}, None]:
            self.assertEqual(validate_intent(value), {'op':'clarify'})
        value = {'op':'add','title':'Call dentist','details':'- Ask about cost'}
        self.assertEqual(validate_intent(value), value)
