from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from second_brain.action_store import StoreError
from second_brain.local_files import private_write
from second_brain.runner import (RunnerError, cleanup_runs, execute_config, load_config,
                                 load_state, run, run_lock, schedule_slot)
from second_brain.scheduler import agent_spec, install
from test_import import ControlledLinear
from test_preview import event
from test_source_lifecycle import Response

UTC = timezone.utc
LA = ZoneInfo('America/Los_Angeles')


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'runner.json'
        self.raw = {'calendar_id': 'fixture', 'workspace_id': 'workspace', 'team_id': 'team',
                    'token_file': 'token.json', 'api_key_file': 'key', 'journal': 'imports.sqlite3',
                    'state_file': 'checkpoint.json', 'runs_dir': 'runs', 'initial_checkpoint': '2026-10-28',
                    'schedule': {'mode': 'daily', 'time': '06:00', 'timezone': 'America/Los_Angeles'}}
        self.write_config()
        self.now = datetime(2026, 10, 28, 14, tzinfo=UTC)
        self.calls, self.notifications = [], []

    def write_config(self):
        private_write(self.path, json.dumps(self.raw))
        self.c = load_config(self.path)

    def pipeline(self, c, folder):
        self.calls.append((c['_start'], c['_end']))
        return {'status': 'complete', 'import_counts': {'created': 0}}

    def invoke(self, *, scheduled=False, pipeline=None, at=None):
        return run(self.c, scheduled=scheduled, clock=lambda: at or self.now,
                   pipeline=pipeline or self.pipeline, notifier=lambda: self.notifications.append(True) or True,
                   zone_resolver=lambda c: LA)

    def test_manual_success_sets_checkpoint_and_due_check_is_quiet(self):
        result = self.invoke()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['start_date'], '2026-10-23')
        self.assertEqual(result['end_date_inclusive'], '2026-10-28')
        self.assertEqual(load_state(self.c)['last_successful_date'], '2026-10-28')
        self.assertEqual(self.invoke(scheduled=True)['reason'], 'not_due')
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.notifications)
        self.assertEqual(self.c['state_file'].stat().st_mode & 0o777, 0o600)

    def test_missed_days_catch_up_from_same_successful_date_in_one_run(self):
        self.invoke()
        result = self.invoke(scheduled=True, at=self.now + timedelta(days=7))
        self.assertEqual((result['start_date'], result['end_date_inclusive']), ('2026-10-23', '2026-11-04'))
        self.assertEqual(len(self.calls), 2)

    def test_failure_does_not_advance_checkpoint_or_retry_each_wake_check(self):
        self.invoke()
        def failed(c, folder):
            return {'status': 'failed', 'import_counts': {'created': 2, 'failed': 1}}
        result = self.invoke(scheduled=True, pipeline=failed, at=self.now + timedelta(days=1))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(load_state(self.c)['last_successful_date'], '2026-10-28')
        self.assertEqual(self.invoke(scheduled=True, at=self.now + timedelta(days=1, minutes=2))['reason'], 'not_due')
        self.assertEqual(len(self.notifications), 1)
        result = self.invoke(scheduled=True, at=self.now + timedelta(days=3))
        self.assertEqual(result['start_date'], '2026-10-23')
        self.assertEqual(result['end_date_inclusive'], '2026-10-31')

    def test_unexpected_errors_are_redacted_and_checkpoint_retained(self):
        def failed(c, folder):
            raise RuntimeError('sensitive source content')
        result = self.invoke(pipeline=failed)
        self.assertNotIn('sensitive', json.dumps(result))
        self.assertEqual(load_state(self.c)['last_successful_date'], '2026-10-28')
        self.assertEqual(len(self.notifications), 1)

    def test_overlapping_manual_and_scheduled_run_skip_under_shared_lock(self):
        with run_lock(self.c['_lock']) as acquired:
            self.assertTrue(acquired)
            self.assertEqual(self.invoke()['reason'], 'already_running')
            self.assertEqual(self.invoke(scheduled=True)['reason'], 'already_running')
        self.assertFalse(self.calls)
        self.assertFalse(self.c['state_file'].exists())

    def test_schedule_changes_preserve_checkpoint(self):
        self.invoke()
        self.raw['schedule'] = {'mode': 'interval', 'seconds': 3600}
        self.write_config()
        result = self.invoke(scheduled=True, at=self.now + timedelta(days=2))
        self.assertEqual(result['start_date'], '2026-10-23')
        self.assertEqual(load_state(self.c)['last_successful_date'], '2026-10-30')

    def test_config_scope_changes_cannot_reuse_checkpoint_silently(self):
        self.invoke()
        self.raw['calendar_id'] = 'different'
        self.write_config()
        with self.assertRaises(RunnerError):
            load_state(self.c)

    def test_timezone_and_dst_schedule_uses_la_not_host(self):
        s = self.raw['schedule']
        before = datetime(2026, 10, 28, 12, 59, tzinfo=UTC)
        at = datetime(2026, 10, 28, 13, tzinfo=UTC)
        self.assertNotEqual(schedule_slot(s, before), schedule_slot(s, at))
        # After DST ends, 06:00 LA is 14:00 UTC.
        before_dst = datetime(2026, 11, 2, 13, 59, tzinfo=UTC)
        at_dst = datetime(2026, 11, 2, 14, tzinfo=UTC)
        self.assertNotEqual(schedule_slot(s, before_dst), schedule_slot(s, at_dst))
        self.assertEqual(schedule_slot(s, at), schedule_slot(s, at.astimezone(ZoneInfo('Asia/Tokyo'))))

    def test_interval_is_elapsed_time_and_skips_old_clock_slots(self):
        self.raw['schedule'] = {'mode': 'interval', 'seconds': 3600}
        self.write_config()
        self.invoke()
        self.assertEqual(self.invoke(scheduled=True, at=self.now + timedelta(minutes=59))['reason'], 'not_due')
        self.assertEqual(self.invoke(scheduled=True, at=self.now - timedelta(hours=1))['reason'], 'not_due')
        self.assertEqual(self.invoke(scheduled=True, at=self.now + timedelta(hours=1))['status'], 'complete')

    def test_retention_removes_only_marked_expired_run_artifacts(self):
        def artifact(stamp, marked=True):
            p = self.c['runs_dir'] / ('run-' + stamp + '-' + 'a' * 32)
            p.mkdir(parents=True)
            if marked:
                (p / '.runner-artifact').write_text('1')
            return p
        old = artifact('20260901T000000')
        current = artifact('20261028T000000')
        unknown = artifact('20260801T000000', marked=False)
        invalid = artifact('99999999T999999')
        outside = self.root / 'private-backup'
        outside.mkdir()
        symlink = self.c['runs_dir'] / ('run-20260801T000000-' + 'b' * 32)
        symlink.symlink_to(outside, target_is_directory=True)
        cleanup_runs(self.c, self.now)
        self.assertFalse(old.exists())
        self.assertTrue(all(p.exists() for p in [current, unknown, invalid, outside, symlink]))

    def test_validation_protects_state_and_secrets_from_retention(self):
        self.raw['runs_dir'] = '.'
        private_write(self.path, json.dumps(self.raw))
        with self.assertRaises(RunnerError):
            load_config(self.path)
        self.write_config_file_for_permission_check()

    def write_config_file_for_permission_check(self):
        self.raw['runs_dir'] = 'runs'
        private_write(self.path, json.dumps(self.raw))
        self.path.chmod(0o644)
        with self.assertRaises(RunnerError):
            load_config(self.path)

    def test_launch_agent_checks_every_minute_and_at_login_without_secrets(self):
        spec = agent_spec(self.path, Path('/python'), self.root)
        self.assertTrue(spec['RunAtLoad'])
        self.assertEqual([s['Minute'] for s in spec['StartCalendarInterval']], list(range(60)))
        self.assertIn('--scheduled', spec['ProgramArguments'])
        self.assertNotIn('key', json.dumps(spec))
        with patch('second_brain.scheduler.sys.platform', 'darwin'):
            with self.assertRaisesRegex(RunnerError, 'manual'):
                install(self.path)

    def test_bad_config_notification_is_throttled_and_private(self):
        self.path.write_text('{}')
        with patch('second_brain.runner.notify_failure', return_value=True) as notify:
            self.assertEqual(execute_config(self.path, scheduled=True)['status'], 'failed')
            self.assertEqual(execute_config(self.path, scheduled=True)['status'], 'failed')
        self.assertEqual(notify.call_count, 1)
        marker = self.path.parent / '.runner-startup-error.json'
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)

    def test_real_pipeline_reuses_fresh_report_and_preserves_actions_on_repeat(self):
        class Session:
            def get(self, url, params=None, timeout=None):
                if '/events/' in url:
                    return Response(200, {'id': 'example', 'status': 'confirmed'})
                if url.endswith('/events'):
                    return Response(200, {'items': [event('example', description='One action\nSecond action', start='2026-10-28T12:00:00-07:00')]})
                return Response(200, {'id': 'fixture', 'timeZone': 'America/Los_Angeles'})
            def close(self):
                pass
        client = ControlledLinear()
        with patch('second_brain.runner.authorized_session', side_effect=lambda p: Session()), patch('second_brain.runner.LinearClient', return_value=client):
            first = run(self.c, clock=lambda: self.now, notifier=lambda: False)
            second = run(self.c, clock=lambda: self.now, notifier=lambda: False)
        self.assertEqual(first['status'], 'complete')
        self.assertEqual(first['import_counts']['created'], 2)
        self.assertEqual(second['import_counts']['already_imported'], 2)
        self.assertEqual(client.attempted_creates, 2)
        self.assertEqual(load_state(self.c)['last_result'], 'complete')

    def test_real_pipeline_failed_preview_never_imports_a_stale_report(self):
        class Session:
            def get(self, url, params=None, timeout=None):
                if url.endswith('/events'):
                    return Response(503, {})
                return Response(200, {'id': 'fixture', 'timeZone': 'America/Los_Angeles'})
            def close(self):
                pass
        private_write(self.root / 'old-report.json', '{"status":"complete","actions":[]}')
        client = ControlledLinear()
        with patch('second_brain.runner.authorized_session', side_effect=lambda p: Session()), patch('second_brain.runner.LinearClient', return_value=client):
            result = run(self.c, clock=lambda: self.now + timedelta(days=1), notifier=lambda: True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(client.attempted_creates, 0)
        self.assertEqual(load_state(self.c)['last_successful_date'], '2026-10-28')

    def test_real_pipeline_deletion_failure_holds_checkpoint_after_partial_writes(self):
        class Session:
            lifecycle_fails = True
            def get(self, url, params=None, timeout=None):
                if '/events/' in url:
                    return Response(404, {}) if self.lifecycle_fails else Response(200, {'id': 'example', 'status': 'confirmed'})
                if url.endswith('/events'):
                    return Response(200, {'items': [event('example', description='One action', start='2026-10-28T12:00:00-07:00')]})
                return Response(200, {'id': 'fixture', 'timeZone': 'America/Los_Angeles'})
            def close(self):
                pass
        client = ControlledLinear()
        with patch('second_brain.runner.authorized_session', side_effect=lambda p: Session()), patch('second_brain.runner.LinearClient', return_value=client):
            first = run(self.c, clock=lambda: self.now + timedelta(days=1), notifier=lambda: True)
            self.assertEqual(first['status'], 'failed')
            self.assertEqual(first['import_counts']['created'], 1)
            self.assertEqual(load_state(self.c)['last_successful_date'], '2026-10-28')
            Session.lifecycle_fails = False
            second = run(self.c, clock=lambda: self.now + timedelta(days=1), notifier=lambda: False)
        self.assertEqual(second['status'], 'complete')
        self.assertEqual(second['import_counts']['already_imported'], 1)
        self.assertEqual(client.attempted_creates, 1)
        self.assertEqual(load_state(self.c)['last_successful_date'], '2026-10-29')

    def test_unwritable_startup_throttle_does_not_spam_notifications(self):
        self.path.write_text('{}')
        with patch('second_brain.runner.private_write', side_effect=PermissionError()), patch('second_brain.runner.notify_failure') as notify:
            self.assertEqual(execute_config(self.path, scheduled=True)['status'], 'failed')
        notify.assert_not_called()
