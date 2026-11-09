"""Operator interface to exactly the same durable application as Hermes."""
import argparse
import json
import sys
from .slack_runtime import load_app
from .action_store import StoreError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('operation', choices=['check', 'receive', 'work', 'status'])
    args = parser.parse_args(argv)
    try:
        app = load_app(args.config)
        if args.operation == 'receive':
            print(json.dumps({'saved':app.receive(json.load(sys.stdin))}))
        elif args.operation == 'work':
            app.work()
            print('Saved commands processed; run Hermes for Slack delivery.')
        elif args.operation == 'status':
            with app.db() as db:
                print(json.dumps({'receipts':dict(db.execute('SELECT state,count(*) FROM receipts GROUP BY state').fetchall()),
                                  'undelivered':db.execute('SELECT count(*) FROM outbox WHERE delivered=0').fetchone()[0]}))
        else:
            print('Configuration and private journal verified. No Slack/Linear request sent.')
        return 0
    except (ValueError, OSError, StoreError, TypeError, KeyError):
        print('Slack operation failed. Check private configuration and preserve journals.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
