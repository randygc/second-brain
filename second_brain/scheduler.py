"""Native macOS scheduling; each wake/login check uses the Python due guard."""

import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys

from .local_files import private_write
from .runner import RunnerError, load_config, load_state

LABEL = 'com.randygc.second-brain'


def agent_spec(config_path, python_path, project_root):
    return {'Label': LABEL,
            'ProgramArguments': [str(python_path), '-m', 'second_brain', 'run', '--config', str(config_path), '--scheduled'],
            'WorkingDirectory': str(project_root), 'RunAtLoad': True,
            # Calendar triggers coalesce on wake; interval timers alone miss sleep.
            # All minutes avoids relying on the Mac timezone for the actual due time.
            'StartCalendarInterval': [{'Minute': minute} for minute in range(60)],
            'ProcessType': 'Background', 'Umask': 0o077,
            'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null'}


def _call(args, *, required=True):
    result = subprocess.run(['/bin/launchctl', *args], capture_output=True, timeout=30)
    if required and result.returncode:
        raise RunnerError('macOS scheduler operation failed; inspect launchctl status before retrying.')
    return result


def schedule_status():
    if sys.platform != 'darwin':
        raise RunnerError('Native scheduling requires macOS.')
    result = _call(['print', f'gui/{os.getuid()}/{LABEL}'], required=False)
    info = {'loaded': result.returncode == 0, 'label': LABEL}
    if result.returncode == 0:
        # Return operational facts only, not the complete environment/job dump.
        output = result.stdout.decode(errors='replace')
        for field, pattern in [('last_exit_code', r'last exit code = (\d+)'), ('launch_count', r'\bruns = (\d+)')]:
            match = re.search(pattern, output)
            info[field] = int(match.group(1)) if match else None
    return info


def install(config_path):
    if sys.platform != 'darwin':
        raise RunnerError('Native scheduling requires macOS.')
    config_path = config_path.expanduser().resolve()
    c = load_config(config_path)
    state = load_state(c)
    if state.get('last_result') != 'complete' or not state.get('last_successful_run_at'):
        raise RunnerError('Complete a successful manual consolidated run before enabling the schedule.')
    project = Path(__file__).resolve().parent.parent
    target = Path.home() / 'Library' / 'LaunchAgents' / (LABEL + '.plist')
    if target.is_symlink():
        raise RunnerError('Refusing a symlinked LaunchAgent destination.')
    if target.exists():
        try:
            existing = plistlib.loads(target.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException) as exc:
            raise RunnerError('Existing LaunchAgent is unreadable; inspect before replacing.') from exc
        if existing.get('Label') != LABEL or str(config_path) not in existing.get('ProgramArguments', []):
            raise RunnerError('Existing LaunchAgent uses different configuration; inspect before replacing.')
    if schedule_status()['loaded']:
        _call(['bootout', f'gui/{os.getuid()}/{LABEL}'])
    spec = agent_spec(config_path, Path(sys.executable).absolute(), project)
    private_write(target, plistlib.dumps(spec).decode())
    _call(['bootstrap', f'gui/{os.getuid()}', str(target)])
    if not schedule_status()['loaded']:
        raise RunnerError('LaunchAgent did not remain loaded; inspect before retrying.')
    return {'loaded': True, 'label': LABEL, 'plist': str(target), 'config': str(config_path)}


def uninstall(config_path):
    config_path = config_path.expanduser().resolve()
    target = Path.home() / 'Library' / 'LaunchAgents' / (LABEL + '.plist')
    if target.exists():
        existing = plistlib.loads(target.read_bytes())
        if target.is_symlink() or existing.get('Label') != LABEL or str(config_path) not in existing.get('ProgramArguments', []):
            raise RunnerError('LaunchAgent is not owned by this configuration; no removal performed.')
    if schedule_status()['loaded']:
        _call(['bootout', f'gui/{os.getuid()}/{LABEL}'])
    target.unlink(missing_ok=True)
    return {'loaded': False, 'label': LABEL}
