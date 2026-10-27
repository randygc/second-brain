import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

from second_brain.cli import main


@unittest.skipUnless(importlib.util.find_spec("google_auth_oauthlib"), "Optional Google support is not installed")
class AuthInputTests(unittest.TestCase):
    def test_invalid_client_json_is_reported_before_browser_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = Path(tmp) / "client.json"
            token = Path(tmp) / "token.json"
            client.write_text("not a JSON document")
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                result = main(["auth", "--client-secrets", str(client), "--token-file", str(token)])
            self.assertEqual(result, 1)
            self.assertIn("not valid JSON", errors.getvalue())
            self.assertNotIn("not a JSON document", errors.getvalue())
            self.assertNotIn("report", errors.getvalue())
            self.assertFalse(token.exists())
