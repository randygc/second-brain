"""Read-only live field/pagination contract check. Prints counts, never content."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from second_brain.linear_store import LinearClient, LinearActionStore
from second_brain.linear_store import LinearActionReader
from second_brain.action_store import StoreError
root = Path(__file__).resolve().parents[2]
try:
    config_path = root/'.local/runner.json'
    config = json.loads(config_path.read_text())
    store = LinearActionStore(LinearClient(config_path.parent/config['api_key_file'], request_budget=30),
                              config['workspace_id'], config['team_id'], root/'.local/slack-read-check-unused.sqlite3')
    actions = LinearActionReader(store).list_actions()
    print(json.dumps({'status':'complete', 'team_action_count':len(actions),
                      'closed_or_archived_count':sum(a.status_type in {'completed','canceled'} or a.archived for a in actions),
                      'scope':'read-only current Linear field/pagination contract; no create or journal mutation'}))
except (StoreError, OSError, ValueError, KeyError):
    print('Read contract check failed; no mutation sent.', file=sys.stderr)
    raise SystemExit(1)
