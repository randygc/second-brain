import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from second_brain.slack_runtime import SubscriptionInterpreter, load_app
from second_brain.action_store import StoreError


class RuntimeTests(unittest.TestCase):
    def test_bounded_interpretation_has_no_tools_or_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory)/'key'; key.write_text('synthetic-key')
            interpreter = SubscriptionInterpreter({'base_url':'http://localhost:4000/v1', 'model':'cliproxy/gpt-6-luna', 'key_file':str(key)})
            response = Mock()
            response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
            response.read.return_value = json.dumps({'choices':[{'message':{'content':json.dumps({'op':'search','query':'passport','all':False})}}]}).encode()
            opener = Mock(); opener.open.return_value=response
            with patch('second_brain.slack_runtime.build_opener',return_value=opener):
                self.assertEqual(interpreter('Find my passport actions')['op'], 'search')
            request = opener.open.call_args.args[0]
            body = json.loads(request.data)
            self.assertNotIn('tools', body)
            self.assertEqual(body['reasoning_effort'], 'none')
            self.assertEqual(body['max_tokens'], 800)
            self.assertEqual(opener.open.call_count, 1)
            opener.open.side_effect = HTTPError('http://localhost',429,'Quota',{},None)
            with patch('second_brain.slack_runtime.build_opener',return_value=opener):
                with self.assertRaises(StoreError) as caught:
                    interpreter('Find actions')
            self.assertNotIn('synthetic-key', str(caught.exception))
            self.assertEqual(opener.open.call_count, 2)  # No retries/fallback request.

    def test_unreviewed_endpoint_and_model_rejected(self):
        for base,model in [('https://api.openai.com/v1','cliproxy/gpt-6-luna'), ('http://localhost:4000/v1','other-model')]:
            with self.assertRaises(ValueError):
                SubscriptionInterpreter({'base_url':base,'model':model,'key_file':'unused'})

    def test_cli_composition_is_offline_and_policy_is_frozen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {'slack':{'workspace_id':'TTEST','channel_id':'CTEST','owner_id':'UOWNER','activation_ts':'100.000000'},
                      'state_dir':str(root/'state'), 'linear':{'workspace_id':'workspace','team_id':'team','key_file':str(root/'key')}}
            path=root/'config.json'; path.write_text(json.dumps(config))
            app=load_app(path)
            self.assertIsNone(app.interpreter)
            self.assertTrue(app.path.exists())
            config['slack']['owner_id']='UOTHER'; path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                load_app(path)
