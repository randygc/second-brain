"""No tools/commands registered with the ordinary Hermes agent."""
from pathlib import Path
import asyncio
import sys


def register(ctx):
    # Deployment places the shared Python package under this plugin's lib/.
    sys.path.insert(0, str(Path(__file__).parent / 'lib'))
    def factory(native, adapter):
        from slack_bolt.response import BoltResponse
        transport = None
        async def guarded(body, next):
            if transport is None:
                return BoltResponse(status=503, body='Second Brain not ready')
            return await transport.middleware(body, next)
        # Install deny guard BEFORE loading configuration/application modules.
        # If any later initialization fails, no request reaches Hermes core.
        native.use(guarded)
        from second_brain.slack_runtime import load_app
        from second_brain.slack_transport import SlackTransport
        config = Path(__file__).parent / 'runtime.json'
        transport = SlackTransport(load_app(config), native.client)
        transport.start()
    ctx.register_platform_handler('slack', factory)
