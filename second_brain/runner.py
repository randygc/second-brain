"""Deterministic, locked ingestion with a durable successful-date checkpoint."""

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4
from zoneinfo import ZoneInfo

from .action_store import StoreError, import_batch
from .google_calendar import GoogleCalendarSource, authorized_session
from .linear_store import LinearActionStore, LinearClient
from .local_files import private_write
from .preview import SourceError, preview
from .provenance import fingerprint
from .report import write_report
from .source_lifecycle import review_deleted_sources

UTC = timezone.utc


class RunnerError(Exception):
    """Configuration/state errors without secret values."""


def utc_now():
    return datetime.now(UTC)


def save_json(path, data):
    private_write(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def load_config(path: Path) -> dict:
    path = path.expanduser().absolute()
    try:
        if path.stat().st_mode & 0o077:
            raise RunnerError('Runner configuration must be owner-only (chmod 600).')
        c = json.loads(path.read_text())
        required = {'calendar_id', 'workspace_id', 'team_id', 'token_file', 'api_key_file',
                    'journal', 'state_file', 'runs_dir', 'initial_checkpoint', 'schedule'}
        optional = {'backlog_state_id', 'overlap_days', 'retention_days', 'max_source_records', 'request_budget'}
        if not isinstance(c, dict) or not required <= c.keys() or c.keys() - required - optional:
            raise RunnerError('Runner configuration has missing or unknown fields.')
        for key in ['calendar_id', 'workspace_id', 'team_id']:
            if not isinstance(c[key], str) or not c[key].strip():
                raise RunnerError('Runner source and destination IDs must be nonempty strings.')
        for key in ['token_file', 'api_key_file', 'journal', 'state_file', 'runs_dir']:
            if not isinstance(c[key], str) or not c[key]:
                raise RunnerError('Runner file paths must be nonempty strings.')
            p = Path(c[key]).expanduser()
            c[key] = (path.parent / p).resolve() if not p.is_absolute() else p.resolve()
        c['initial_checkpoint'] = date.fromisoformat(c['initial_checkpoint'])
        for key, default, lower, upper in [('overlap_days', 5, 0, 365), ('retention_days', 30, 1, 3650),
                                            ('max_source_records', 100, 1, 10000), ('request_budget', 1000, 10, 1000)]:
            c.setdefault(key, default)
            if type(c[key]) is not int or not lower <= c[key] <= upper:
                raise RunnerError('Runner numeric configuration is invalid.')
        s = c['schedule']
        if not isinstance(s, dict):
            raise RunnerError('Runner schedule must be an object.')
        if s.get('mode') == 'daily' and set(s) == {'mode', 'time', 'timezone'}:
            if not isinstance(s['time'], str) or not re.fullmatch(r'\d{2}:\d{2}', s['time']):
                raise RunnerError('Daily time must be HH:MM.')
            time.fromisoformat(s['time'])
            ZoneInfo(s['timezone'])
        elif s.get('mode') == 'interval' and set(s) == {'mode', 'seconds'}:
            if type(s['seconds']) is not int or not 60 <= s['seconds'] <= 31536000:
                raise RunnerError('Interval must be 60–31,536,000 seconds.')
        else:
            raise RunnerError('Use a daily time/timezone or interval seconds schedule.')
        protected = [path.resolve()] + [c[k] for k in ['token_file', 'api_key_file', 'journal', 'state_file']]
        if len(set(protected)) != len(protected) or any(p.is_relative_to(c['runs_dir']) for p in protected):
            raise RunnerError('Credentials, journal, checkpoint and configuration must be distinct and outside the disposable runs directory.')
        c['_scope'] = fingerprint([c['calendar_id'], c['workspace_id'], c['team_id'], str(c['journal'])])
        c['_lock'] = c['journal'].with_name(c['journal'].name + '.run.lock')
        if c['_lock'] in protected or c['_lock'].is_relative_to(c['runs_dir']):
            raise RunnerError('Runner lock must be outside disposable artifacts.')
        return c
    except RunnerError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RunnerError('Cannot read valid private runner configuration; check file paths, dates and timezone.') from exc


def schedule_slot(schedule, now):
    """Most recent scheduled slot, independent of host timezone or wake time."""
    now = now.astimezone(UTC)
    if schedule['mode'] == 'interval':
        seconds = schedule['seconds']
        instant = datetime.fromtimestamp((int(now.timestamp()) // seconds) * seconds, UTC)
    else:
        zone = ZoneInfo(schedule['timezone'])
        local_date = now.astimezone(zone).date()
        instant = datetime.combine(local_date, time.fromisoformat(schedule['time']), zone).astimezone(UTC)
        if instant > now:
            instant = datetime.combine(local_date - timedelta(days=1), time.fromisoformat(schedule['time']), zone).astimezone(UTC)
    return fingerprint(schedule) + ':' + instant.isoformat()


@contextmanager
def run_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(fd)  # Closing releases the lock; never unlink a live lock inode.


def load_state(c):
    if not c['state_file'].exists():
        return {'version': 1, 'scope': c['_scope'], 'last_successful_date': c['initial_checkpoint'].isoformat()}
    try:
        state = json.loads(c['state_file'].read_text())
        if state['version'] != 1 or state['scope'] != c['_scope']:
            raise RunnerError('Checkpoint belongs to a different source/destination/journal. Do not reset it blindly.')
        date.fromisoformat(state['last_successful_date'])
        return state
    except RunnerError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RunnerError('Checkpoint is unreadable; preserve it and resolve before running.') from exc


def notify_failure():
    """Constant notification text: never interpolate source data or secrets."""
    try:
        result = subprocess.run(['/usr/bin/osascript', '-e',
            'display notification "The import did not complete. Check the private run log; authorization, connectivity or capacity may need attention." with title "Second Brain import failed"'],
            capture_output=True, timeout=15)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def cleanup_runs(c, now):
    root = c['runs_dir']
    if not root.exists():
        return
    cutoff = now.astimezone(UTC) - timedelta(days=c['retention_days'])
    for child in root.iterdir():
        if child.is_symlink() or not child.is_dir() or not re.fullmatch(r'run-\d{8}T\d{6}-[0-9a-f]{32}', child.name):
            continue
        if not (child / '.runner-artifact').is_file():
            continue
        try:
            created = datetime.strptime(child.name[4:19], '%Y%m%dT%H%M%S').replace(tzinfo=UTC)
        except ValueError:
            continue
        if created < cutoff:
            shutil.rmtree(child)


def run_pipeline(c, run_dir):
    session = authorized_session(c['token_file'])
    try:
        source = GoogleCalendarSource(session)
        report = preview(source, c['calendar_id'], c['_start'], c['_end'])
        write_report(report, run_dir)
        client = LinearClient(c['api_key_file'], request_budget=c['request_budget'])
        store = LinearActionStore(client, c['workspace_id'], c['team_id'], c['journal'], c.get('backlog_state_id'))
        imported = import_batch(report, store)
        save_json(run_dir / 'import-results.json', imported)
        deleted = review_deleted_sources(source, store, c['calendar_id'], execute=True, limit=c['max_source_records'])
        save_json(run_dir / 'source-review-results.json', deleted)
        return {'status': 'complete' if imported['status'] == deleted['status'] == 'complete' else 'failed',
                'import_counts': imported['counts'], 'source_review_counts': deleted['counts'],
                'action_count': report['action_count'], 'matching_events': report['matching_events'],
                'changed_sources': imported['changed_sources'], 'affected_existing_actions': imported['affected_existing_actions']}
    finally:
        session.close()


def calendar_zone(c):
    session = authorized_session(c['token_file'])
    try:
        return ZoneInfo(GoogleCalendarSource(session).calendar_timezone(c['calendar_id']))
    finally:
        session.close()


def run(c, *, scheduled=False, clock=utc_now, pipeline=run_pipeline, notifier=notify_failure, zone_resolver=calendar_zone):
    """Same execution path for manual and scheduled use; only manual bypasses due check."""
    with run_lock(c['_lock']) as acquired:
        if not acquired:
            return {'status': 'skipped', 'reason': 'already_running'}
        started = clock().astimezone(UTC)
        state = load_state(c)
        slot = schedule_slot(c['schedule'], started)
        prior_slot = state.get('last_attempt_slot', '')
        if scheduled and prior_slot.split(':', 1)[0] == slot.split(':', 1)[0] and prior_slot >= slot:
            return {'status': 'skipped', 'reason': 'not_due'}
        # Attempt persistence prevents every-minute retries after failures or crashes.
        # The success checkpoint is changed only after both operations and logs succeed.
        state.update(last_attempt_slot=slot, last_attempt_started_at=started.isoformat())
        save_json(c['state_file'], state)
        folder = c['runs_dir'] / ('run-' + started.strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex)
        summary = {'status': 'failed', 'started_at': started.isoformat()}
        try:
            folder.mkdir(parents=True, mode=0o700)
            private_write(folder / '.runner-artifact', '1\n')
            zone = zone_resolver(c)
            end = started.astimezone(zone).date()
            checkpoint = date.fromisoformat(state['last_successful_date'])
            if checkpoint > end:
                raise RunnerError('Checkpoint is ahead of the current Calendar date; review configuration/clock.')
            start = checkpoint - timedelta(days=c['overlap_days'])
            summary.update(start_date=start.isoformat(), end_date_inclusive=end.isoformat())
            summary.update(pipeline({**c, '_start': start, '_end': end}, folder))
            if summary['status'] != 'complete':
                summary['error'] = 'Import or source review had failures. Inspect the private per-record result files.'
        except (RunnerError, SourceError, StoreError, OSError) as exc:
            summary.update(status='failed', error=str(exc))
        except Exception as exc:
            summary.update(status='failed', error='Unexpected runner failure (' + type(exc).__name__ + '); checkpoint retained.')
        summary['finished_at'] = clock().astimezone(UTC).isoformat()
        if summary['status'] != 'complete':
            summary['notification_requested'] = notifier()
        save_json(folder / 'summary.json', summary)
        if summary['status'] == 'complete':
            state.update(last_successful_date=summary['end_date_inclusive'], last_successful_run_at=summary['finished_at'])
        state.update(last_result=summary['status'], last_run_dir=str(folder))
        save_json(c['state_file'], state)
        try:
            cleanup_runs(c, clock())
        except OSError:
            summary['cleanup_warning'] = 'Could not remove some expired run artifacts.'
            save_json(folder / 'summary.json', summary)
        return summary


def execute_config(path, *, scheduled=False):
    """Throttle startup/configuration errors too; invalid config must not spam."""
    try:
        return run(load_config(path), scheduled=scheduled)
    except (RunnerError, OSError) as exc:
        marker = path.expanduser().absolute().parent / '.runner-startup-error.json'
        now = utc_now()
        previous = {}
        try:
            previous = json.loads(marker.read_text()) if marker.exists() else {}
        except (OSError, ValueError):
            pass
        last = previous.get('reported_at')
        try:
            report_due = not last or now - datetime.fromisoformat(last) >= timedelta(days=1)
        except (ValueError, TypeError):
            report_due = True
        if report_due:
            # Persist the throttle first. If its directory is unwritable, fail
            # quietly rather than showing a notification every minute.
            try:
                save_json(marker, {'reported_at': now.isoformat(), 'error': str(exc), 'notification_requested': False})
            except OSError:
                return {'status': 'failed', 'error': str(exc)}
            notice = notify_failure()
            save_json(marker, {'reported_at': now.isoformat(), 'error': str(exc), 'notification_requested': notice})
        return {'status': 'failed', 'error': str(exc)}
