"""Offline compatibility probe, not a production plugin.

Run with --hermes-source pointing to an untouched checkout of HERMES_COMMIT.
Uses real Bolt dispatch and the AST-extracted Hermes registration method;
does NOT import/start the full Hermes gateway or validate Socket Mode delivery.
All Slack authorization/delivery is synthetic; no credentials are needed/read.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from importlib.metadata import version

HERMES_COMMIT = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"


def registration_context(root):
    actual = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != HERMES_COMMIT:
        raise RuntimeError(f"Expected Hermes {HERMES_COMMIT}; got {actual}")
    paths = ["hermes_cli/plugins.py", "plugins/platforms/slack/adapter.py"]
    # Reject tracked modifications to the source whose contract is being tested.
    if subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--", *paths], text=True
    ).strip():
        raise RuntimeError("Probe source files must be unmodified")
    tree = ast.parse((root / paths[0]).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PluginContext")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "register_platform_handler")
    if method.decorator_list:
        raise RuntimeError("Unexpected registration decorators; re-review source")
    # Compile ONLY the upstream method, not any Hermes module startup/import code.
    isolated = ast.Module(body=[ast.ClassDef(name="RegistrationContext", bases=[], keywords=[], body=[method], decorator_list=[])], type_ignores=[])
    namespace = {"Callable": object, "logger": logging.getLogger("probe")}
    exec(compile(ast.fix_missing_locations(isolated), str(root / paths[0]), "exec"), namespace)
    ctx = namespace["RegistrationContext"]()
    ctx._manager = SimpleNamespace(_platform_handler_factories={})
    ctx.manifest = SimpleNamespace(name="second-brain-probe")
    ctx._refuse = lambda message: ValueError(message)
    adapter_tree = ast.parse((root / paths[1]).read_text())
    adapter_cls = next(n for n in adapter_tree.body if isinstance(n, ast.ClassDef) and n.name == "SlackAdapter")
    registration = next(n for n in adapter_cls.body if isinstance(n, ast.FunctionDef) and n.name == "_register_bolt_handlers")
    calls = [n for n in ast.walk(registration) if isinstance(n, ast.Call)]
    wire = next(n.lineno for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == "_wire_plugin_handlers")
    listeners = [n.lineno for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == "event"]
    assert listeners and wire > max(listeners), "Pinned listener ordering changed"
    return ctx


async def probe(root):
    from slack_bolt.async_app import AsyncApp, AsyncBoltRequest
    from slack_bolt.authorization import AuthorizeResult
    from slack_bolt.response import BoltResponse
    from slack_sdk.web.async_client import AsyncWebClient

    for package, expected in [("slack-bolt", "1.30.0"), ("slack-sdk", "3.44.1"), ("aiohttp", "3.14.5")]:
        assert version(package) == expected, (package, version(package), expected)
    ctx = registration_context(root)
    core_calls, accepted, interpreted = [], [], []
    delivered = AsyncMock()

    async def authorize(enterprise_id, team_id, user_id):
        return AuthorizeResult(enterprise_id=enterprise_id, team_id=team_id,
                               bot_token="xoxb-synthetic", bot_id="B_TEST", bot_user_id="U_BOT")

    app = AsyncApp(authorize=authorize, signing_secret="synthetic-only", process_before_response=True,
                   request_verification_enabled=False)

    # Match stable Hermes order: core listeners are present BEFORE plugin wiring.
    @app.event("message")
    async def core_message(event):
        core_calls.append(event["text"])
        raise RuntimeError("SIMULATED_CORE_QUOTA_OUTAGE")

    @app.command("/model")
    async def core_command(ack):
        core_calls.append("/model")
        await ack()

    def factory(native, adapter):
        async def deterministic_boundary(body, next):
            event = body.get("event", {})
            user = event.get("user", body.get("user_id"))
            channel = event.get("channel", body.get("channel_id"))
            # This is an independent policy check, not Hermes authorization.
            if (body.get("team_id"), channel, user) != ("T_OWNER", "C_PRIVATE", "U_OWNER"):
                return BoltResponse(status=200, body="denied")
            text = event.get("text", "")
            if "command" in body:
                return BoltResponse(status=200, body="unsupported-command")
            if event.get("subtype") or event.get("bot_id"):
                return BoltResponse(status=200, body="ignored-event")
            if text == "add uncaught":
                raise RuntimeError("synthetic uncaught middleware failure")
            if text.startswith(("add ", "search ")):
                try:
                    if text == "add fail":
                        raise OSError("synthetic storage failure")
                    accepted.append(text)
                    await delivered(channel=channel, thread_ts=event.get("thread_ts") or event["ts"])
                    return BoltResponse(status=200, body="handled")
                except Exception:
                    # Fail closed: never call next() after deterministic failure.
                    return BoltResponse(status=503, body="deterministic-failure")
            if text.startswith("interpret "):
                interpreted.append(text)
                return BoltResponse(status=200, body="model-unavailable")
            await next()

        native.use(deterministic_boundary)

    # Execute the actual upstream PluginContext.register_platform_handler method.
    ctx.register_platform_handler("slack", factory)
    for registered_factory, _name in ctx._manager._platform_handler_factories["slack"]:
        registered_factory(app, SimpleNamespace())

    async def dispatch(text, *, user="U_OWNER", channel="C_PRIVATE", team="T_OWNER", thread=None, subtype=None):
        event = {"type": "message", "user": user, "channel": channel, "text": text, "ts": "1800000000.000001"}
        if thread:
            event["thread_ts"] = thread
        if subtype:
            event["subtype"] = subtype
        body = {"type": "event_callback", "team_id": team, "event_id": "Ev_synthetic", "event": event}
        return await app.async_dispatch(AsyncBoltRequest(body=body, mode="socket_mode"))

    # Guard all actual Web API calls and outbound network, including accidental SDK usage.
    with patch.object(AsyncWebClient, "api_call", AsyncMock(side_effect=AssertionError("NETWORK_API_FORBIDDEN"))), \
         patch.object(socket.socket, "connect", side_effect=AssertionError("NETWORK_FORBIDDEN")), \
         patch.object(socket.socket, "connect_ex", side_effect=AssertionError("NETWORK_FORBIDDEN")):
        for command in ["add example", "search example"]:
            assert (await dispatch(command)).body == "handled"
        assert not core_calls
        assert (await dispatch("add fail")).status == 503
        assert not core_calls
        assert (await dispatch("add uncaught")).status == 500
        assert not core_calls
        for kwargs in [{"user": "U_OTHER"}, {"channel": "C_OTHER"}, {"channel": "D_DM"}, {"team": "T_OTHER"}]:
            assert (await dispatch("add denied", **kwargs)).body == "denied"
        assert (await dispatch("add edited", subtype="message_changed")).body == "ignored-event"
        assert (await dispatch("interpret something")).body == "model-unavailable"
        assert (await dispatch("search after outage")).body == "handled"
        assert not core_calls
        await dispatch("unhandled core canary")
        assert core_calls == ["unhandled core canary"], "Canary must prove listeners actually dispatch"
        assert (await dispatch("add after core failure", thread="1799999999.000001")).body == "handled"
        assert delivered.call_args.kwargs["thread_ts"] == "1799999999.000001"
        slash = {"team_id": "T_OWNER", "channel_id": "C_PRIVATE", "user_id": "U_OWNER", "command": "/model", "text": ""}
        assert (await app.async_dispatch(AsyncBoltRequest(body=slash, mode="socket_mode"))).body == "unsupported-command"
        assert core_calls == ["unhandled core canary"]
    return {"result": "PASS", "hermes_commit": HERMES_COMMIT, "accepted_commands": len(accepted),
            "scope": "real Bolt dispatch; extracted Hermes registration method; synthetic auth/delivery",
            "not_proven": ["full Hermes startup/import", "provider quota classification", "Socket Mode ack/delivery", "durable receipts", "Slack history catchup", "Linear writes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-source", type=Path, required=True)
    args = parser.parse_args()
    # Do not inherit Slack configuration/credentials into the probe's SDK initialization.
    with patch.dict(os.environ, {}, clear=True):
        print(json.dumps(asyncio.run(probe(args.hermes_source.resolve())), indent=2))


if __name__ == "__main__":
    main()
