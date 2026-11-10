"""Hermes-owned Bolt middleware and transport; never dispatch to core agent tools."""
import asyncio
import logging
import html
import time
from uuid import uuid4

LOG = logging.getLogger(__name__)


class SlackTransport:
    def __init__(self, app, client):
        self.app, self.client = app, client
        self.ready = False
        self.task = None
        self.backup_at = 0
        self.history_at = 0
        self.boot_id = str(uuid4())

    async def middleware(self, body, next):
        from slack_bolt.response import BoltResponse
        # This dedicated bot has no other capability. Never call next(), including
        # on malformed envelopes, failed storage or unsupported slash commands.
        try:
            await asyncio.to_thread(self.app.receive, body)
        except Exception:
            LOG.error('Second Brain receipt storage failed; retained-history recovery required.')
            return BoltResponse(status=503, body='Receipt storage unavailable')
        return BoltResponse(status=200, body='')

    async def verify(self):
        p = self.app.policy
        auth = await self.client.auth_test()
        info = (await self.client.conversations_info(channel=p.channel_id))['channel']
        if (auth.get('team_id') != p.workspace_id or not info.get('is_private')
                or not info.get('is_member') or info.get('is_shared') or info.get('is_archived')):
            raise ValueError('Slack identity/private channel verification failed')
        self.ready = True

    async def history(self):
        """Advance only after ALL retained pages are saved. Replay is harmless."""
        p = self.app.policy
        oldest = await asyncio.to_thread(self.app.history_cursor)
        latest = f'{time.time():.6f}'
        cursor, seen = None, set()
        for _ in range(200):
            args = dict(channel=p.channel_id, oldest=oldest, latest=latest, inclusive=True, limit=100)
            if cursor:
                args['cursor'] = cursor
            result = await self.client.conversations_history(**args)
            if not result.get('ok', False) or not isinstance(result.get('messages'), list):
                raise ValueError('Incomplete Slack history')
            if result.get('is_limited'):
                await asyncio.to_thread(self.app.recovery_notice,
                    'Slack reports limited retained history. Some offline messages may be unavailable; please resubmit missing requests.',
                    'history-limited:' + latest[:8])
            for event in result['messages']:
                await asyncio.to_thread(self.app.receive, {'team_id':p.workspace_id, 'event':dict(event, channel=p.channel_id, type='message')})
            cursor = result.get('response_metadata', {}).get('next_cursor', '')
            if not cursor:
                if result.get('has_more'):
                    raise ValueError('Slack history truncated without a cursor')
                await self.recover_choices(oldest, latest)
                await asyncio.to_thread(self.app.history_complete, latest)
                return
            if cursor in seen:
                raise ValueError('Repeated Slack history cursor')
            seen.add(cursor)
        raise ValueError('Slack history pagination budget exhausted')

    async def recover_choices(self, oldest, latest):
        # Scope to durable pending choices. If Slack denies retained replies,
        # ask the owner to repeat the response in its original thread.
        for thread in await asyncio.to_thread(self.app.pending_threads):
            cursor, seen = None, set()
            try:
                for _ in range(100):
                    args = dict(channel=self.app.policy.channel_id, ts=thread,
                                oldest=self.app.policy.activation_ts, latest=latest, inclusive=True, limit=100)
                    if cursor:
                        args['cursor'] = cursor
                    result = await self.client.conversations_replies(**args)
                    if not result.get('ok', False) or not isinstance(result.get('messages'), list):
                        raise ValueError('Incomplete retained thread replies')
                    for event in result['messages']:
                        await asyncio.to_thread(self.app.receive, {'team_id':self.app.policy.workspace_id,
                            'event':dict(event, channel=self.app.policy.channel_id, type='message')})
                    cursor = result.get('response_metadata', {}).get('next_cursor', '')
                    if not cursor:
                        if result.get('has_more'):
                            raise ValueError('Incomplete thread pagination')
                        break
                    if cursor in seen:
                        raise ValueError('Repeated thread cursor')
                    seen.add(cursor)
                else:
                    raise ValueError('Thread pagination budget exhausted')
            except Exception:
                await asyncio.to_thread(self.app.restart_notice, self.boot_id)
                LOG.error('Retained choice replies unavailable; owner asked to repeat confirmation.')
                return

    async def deliver(self):
        for item in await asyncio.to_thread(self.app.outbox):
            args = dict(channel=self.app.policy.channel_id, text=html.escape(item['text'][:35000], quote=False),
                        mrkdwn=False, parse='none', link_names=False, unfurl_links=False, unfurl_media=False,
                        client_msg_id=item['id'])
            if item['thread']:
                args['thread_ts'] = item['thread']
            result = await self.client.chat_postMessage(**args)
            if not result.get('ok', False) or not result.get('ts'):
                raise ValueError('Slack delivery not confirmed')
            await asyncio.to_thread(self.app.delivered, item['id'])

    async def tick(self):
        if not self.ready:
            await self.verify()
        # Run retained-history reconciliation before processing on every restart.
        # After a history outage, explicit live receipts can still be processed.
        if time.time() >= self.history_at:
            try:
                await self.history()
            except Exception:
                LOG.error('Second Brain retained-history reconciliation pending; live commands remain available.')
            finally:
                self.history_at = time.time()+60
        await self.deliver()  # Persisted "received" notification precedes processing.
        await asyncio.to_thread(self.app.work)
        await self.deliver()

    async def run(self):
        while True:
            if getattr(self.app, 'backup_dir', None) and time.time() >= self.backup_at:
                try:
                    await asyncio.to_thread(self.app.backup, self.app.backup_dir)
                except Exception:
                    LOG.error('Second Brain private backup pending recovery; live state retained.')
                self.backup_at = time.time()+60
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # SDK exceptions can contain complete payloads/tokens; never print.
                LOG.error('Second Brain Slack transport pending recovery (%s).', type(exc).__name__)
                retry = 60
                response = getattr(exc, 'response', None)
                if response is not None:
                    try:
                        retry = max(60, min(3600, int(response.headers.get('Retry-After', 60))))
                    except (ValueError, TypeError, AttributeError):
                        pass
                await asyncio.sleep(retry)
                continue
            await asyncio.sleep(2)

    def start(self):
        self.task = asyncio.create_task(self.run(), name='second-brain-slack')
        return self.task
