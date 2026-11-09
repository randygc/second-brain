"""Network-free production plugin dispatch check in the pinned Hermes/Bolt env.

Unlike the exploratory probe, this loads the production plugin and real durable
command application. Slack authorization/delivery and Linear are synthetic.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import sys

PLUGIN = Path('/opt/hermes-runtime/second-brain-slack/staged')
sys.path.insert(0, str(PLUGIN/'lib'))
from second_brain.action_store import ImportResult, StoreError
from second_brain.slack_commands import SlackCommands, SlackPolicy
from second_brain.slack_transport import SlackTransport


async def run():
    from slack_bolt.async_app import AsyncApp, AsyncBoltRequest
    from slack_bolt.authorization import AuthorizeResult
    from slack_sdk.web.async_client import AsyncWebClient
    async def authorize(enterprise_id, team_id, user_id):
        return AuthorizeResult(enterprise_id=enterprise_id, team_id=team_id, bot_token='xoxb-synthetic', bot_id='BTEST', bot_user_id='UBOT')
    core = []
    def native():
        app = AsyncApp(authorize=authorize, signing_secret='synthetic', process_before_response=True, request_verification_enabled=False)
        @app.event('message')
        async def unsafe_core(event):
            core.append(event['text'])
        @app.command('/model')
        async def unsafe_slash(ack):
            core.append('/model'); await ack()
        return app
    spec = importlib.util.spec_from_file_location('production_slack_plugin', PLUGIN/'__init__.py')
    plugin = importlib.util.module_from_spec(spec); spec.loader.exec_module(plugin)
    factories = []
    plugin.register(SimpleNamespace(register_platform_handler=lambda platform,factory: factories.append(factory)))
    assert len(factories)==1
    with tempfile.TemporaryDirectory() as folder:
        created = []
        store = Mock()
        def create(draft):
            created.append(draft)
            return ImportResult('created','1','SB-1','https://linear.app/example/1')
        store.ensure_action.side_effect=create
        reader = Mock(); reader.list_actions.return_value=[]
        interpreter = Mock(side_effect=StoreError('synthetic subscription quota rejection'))
        application = SlackCommands(SlackPolicy('TTEST','CTEST','UOWNER','100.000000'),Path(folder)/'slack.sqlite',lambda:(store,reader),interpreter)
        app = native()
        with patch('second_brain.slack_runtime.load_app', return_value=application), patch.object(SlackTransport,'start'):
            factories[0](app, SimpleNamespace())
        n = 0
        async def dispatch(text, **updates):
            nonlocal n
            n+=1
            team=updates.pop('team','TTEST')
            event={'type':'message','user':'UOWNER','channel':'CTEST','text':text,'ts':f'101.{n:06d}'}
            event.update(updates)
            return await app.async_dispatch(AsyncBoltRequest(body={'type':'event_callback','team_id':team,'event_id':f'Ev{n}','event':event},mode='socket_mode'))
        with patch.object(AsyncWebClient,'api_call',AsyncMock(side_effect=AssertionError('NETWORK_FORBIDDEN'))), \
             patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')):
            assert (await dispatch('Please find passport actions')).status==200
            await asyncio.to_thread(application.work)
            assert interpreter.call_count==1
            assert (await dispatch('add Renew passport\n- Keep bullets')).status==200
            assert (await dispatch('search passport')).status==200
            await asyncio.to_thread(application.work)
            assert len(created)==1 and created[0].details=='- Keep bullets'
            for kwargs in [{'team':'TOTHER'},{'user':'UOTHER'},{'channel':'COTHER'},{'channel':'DTEST'},{'subtype':'message_changed'}]:
                assert (await dispatch('add forbidden',**kwargs)).status==200
            slash={'team_id':'TTEST','channel_id':'CTEST','user_id':'UOWNER','command':'/model','text':''}
            assert (await app.async_dispatch(AsyncBoltRequest(body=slash,mode='socket_mode'))).status==200
            with patch.object(application,'receive',side_effect=OSError('synthetic disk failure')):
                assert (await dispatch('add storage failure')).status==503
            assert (await dispatch('help')).status==200
            await asyncio.to_thread(application.work)
            assert len(created)==1 and not core
            # Configuration failure AFTER guard installation must also fail closed.
            broken = native()
            with patch('second_brain.slack_runtime.load_app',side_effect=ValueError('invalid configuration')):
                try: factories[0](broken,SimpleNamespace())
                except ValueError: pass
                else: raise AssertionError('Expected configuration failure')
            response=await broken.async_dispatch(AsyncBoltRequest(body={'type':'event_callback','team_id':'TTEST','event':{'type':'message','user':'UOWNER','channel':'CTEST','text':'add should not run','ts':'105.000001'}},mode='socket_mode'))
            assert response.status==503 and not core
    return {'result':'PASS','scope':'production plugin + durable application + real Bolt dispatch; no network',
            'checks':['owner/workspace/channel enforcement','DM/subtype/slash denial','quota-independent explicit add/search',
                      'receipt storage failure closed','configuration failure closed','zero core listener calls'],
            'not_proven':['live Slack Socket Mode delivery','live Linear creation','Hermes complete gateway startup']}


if __name__=='__main__':
    with patch.dict(os.environ,{},clear=True):
        print(json.dumps(asyncio.run(run()),indent=2))
