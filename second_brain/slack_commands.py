"""Durable Slack command application. No Hermes, Slack SDK or model dependency.

receive() commits an authorized receipt before enqueueing its acknowledgement.
work() resumes saved commands; the action store owns uncertain-write recovery.
Only one work() runs per journal (OS lock); receive() remains available meanwhile.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import tempfile
from uuid import NAMESPACE_URL, uuid5

from .action_store import ActionDraft, StoreError
from .action_search import search_actions, similar_actions

HELP = ("Commands: add <title> (following lines are details); search <words>; "
        "search --all <words> (includes closed/archived); help. "
        "Reply next for another search page, or create anyway / cancel to a possible-match question. "
        "One action item per message. Source edits/deletions do not change Linear. "
        "Deadlines, reminders and workflows are not enabled in slice 1.")


@dataclass(frozen=True)
class SlackPolicy:
    workspace_id: str
    channel_id: str
    owner_id: str
    activation_ts: str

    def __post_init__(self):
        if not all(re.fullmatch(pattern, value) for pattern, value in [
                (r"T[A-Z0-9]+", self.workspace_id), (r"[CG][A-Z0-9]+", self.channel_id),
                (r"[UW][A-Z0-9]+", self.owner_id), (r"\d+\.\d+", self.activation_ts)]):
            raise ValueError("Explicit Slack workspace, channel, owner and activation timestamp required.")


def parse_command(text):
    """Explicit commands only; payload is preserved verbatim after the prefix."""
    if text.strip().casefold() in {"help", "next", "create anyway", "cancel"}:
        return {"op": text.strip().casefold()}
    match = re.match(r"(?is)^(add|search)[ \t]+(.+)$", text)
    if not match:
        return None
    op, value = match.group(1).casefold(), match.group(2)
    if op == "add":
        title, _, details = value.partition("\n")
        if not title.strip():
            return {"op": "help"}
        return {"op": "add", "title": title, "details": details}
    all_items = value.startswith("--all ")
    query = value[6:] if all_items else value
    return {"op": "search", "query": query.strip(), "all": all_items}


def line(action):
    # Slack mrkdwn is disabled by transport; untrusted titles cannot ping people.
    due = f"; due {action.due_date}" if action.due_date else ""
    return f"{action.identifier}: {action.title[:255]} [{action.status}{due}]\n{action.url}"


class SlackCommands:
    def __init__(self, policy, path: Path, store_factory, interpreter=None, clock=time.time):
        self.policy, self.path, self.store_factory = policy, Path(path), store_factory
        self.interpreter, self.clock = interpreter, clock
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY, ts TEXT NOT NULL, thread TEXT NOT NULL, text TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued', command TEXT, decision TEXT,
                retry_at REAL NOT NULL DEFAULT 0, error TEXT);
              CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, receipt TEXT NOT NULL, thread TEXT NOT NULL,
                text TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS searches (
                receipt TEXT PRIMARY KEY, thread TEXT NOT NULL, query TEXT NOT NULL,
                all_items INTEGER NOT NULL, offset INTEGER NOT NULL);
            ''')
            frozen = json.dumps(asdict(policy), sort_keys=True)
            old = db.execute("SELECT value FROM settings WHERE key='policy'").fetchone()
            if old and old[0] != frozen:
                raise ValueError("Slack journal policy changed; preserve it and explicitly migrate before activation.")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('policy',?)", (frozen,))
            db.execute("INSERT OR IGNORE INTO settings VALUES ('history_cursor',?)", (policy.activation_ts,))

    @contextmanager
    def db(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Refusing symlink journal.")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _notice(self, db, receipt, thread, kind, text):
        identity = str(uuid5(NAMESPACE_URL, f"second-brain-slack:{receipt}:{kind}"))
        db.execute("INSERT OR IGNORE INTO outbox(id,receipt,thread,text) VALUES (?,?,?,?)",
                   (identity, receipt, thread, text))

    def receive(self, body):
        event = body.get("event", {})
        p = self.policy
        if (body.get("team_id"), event.get("channel"), event.get("user")) != (p.workspace_id, p.channel_id, p.owner_id):
            return False
        if event.get("type") != "message" or event.get("subtype") or event.get("bot_id") or event.get("hidden"):
            return False
        ts, text = event.get("ts", ""), event.get("text", "")
        if (not re.fullmatch(r"\d+\.\d+", ts) or float(ts) < float(p.activation_ts)
                or not isinstance(text, str) or not text.strip() or len(text) > 16000):
            return False
        thread = event.get("thread_ts") or ts
        if not re.fullmatch(r"\d+\.\d+", thread):
            return False
        # Message timestamp, not event delivery ID: history replay has no event_id.
        identity = f"{p.workspace_id}:{p.channel_id}:{ts}"
        with self.db() as db:
            added = db.execute("INSERT OR IGNORE INTO receipts(id,ts,thread,text) VALUES (?,?,?,?)",
                               (identity, ts, thread, text)).rowcount
            if added:
                self._notice(db, identity, thread, "received", "Received and saved. Processing this request.")
        return bool(added)

    def outbox(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM outbox WHERE delivered=0 ORDER BY rowid LIMIT 30")]

    def delivered(self, identity):
        with self.db() as db:
            db.execute("UPDATE outbox SET delivered=1 WHERE id=?", (identity,))

    def history_cursor(self):
        with self.db() as db:
            return db.execute("SELECT value FROM settings WHERE key='history_cursor'").fetchone()[0]

    def history_complete(self, timestamp):
        with self.db() as db:
            if float(timestamp) > float(self.history_cursor()):
                db.execute("UPDATE settings SET value=? WHERE key='history_cursor'", (timestamp,))

    def recovery_notice(self, text, key="history-recovery"):
        with self.db() as db:
            self._notice(db, key, "", key, text)

    def pending_threads(self):
        with self.db() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT thread FROM receipts WHERE state='choice' ORDER BY thread")]

    def restart_notice(self, boot_id):
        # Fallback when the actual app cannot read retained thread replies.
        with self.db() as db:
            for row in db.execute("SELECT * FROM receipts WHERE state='choice'"):
                self._notice(db, row['id'], row['thread'], "restart:" + boot_id,
                             "Possible-match choice is still pending. If you replied while I was offline, please repeat create anyway or cancel here.")

    def backup(self, directory):
        """Consistent SQLite snapshots, imports first; never reset live state."""
        directory = Path(directory)
        for source in [self.path.parent/'imports.sqlite3', self.path]:
            if not source.exists():
                continue
            with tempfile.TemporaryDirectory(dir=self.path.parent) as scratch:
                temporary = Path(scratch)/source.name
                source_db = sqlite3.connect(source)
                target_db = sqlite3.connect(temporary)
                try:
                    source_db.backup(target_db)
                finally:
                    target_db.close()
                    source_db.close()
                # Closed binary snapshot, owner-only atomic replacement.
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd, name = tempfile.mkstemp(dir=directory, prefix='.'+source.name)
                try:
                    with os.fdopen(fd, 'wb') as output:
                        output.write(temporary.read_bytes())
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(name, directory/source.name)
                finally:
                    if os.path.exists(name):
                        os.unlink(name)

    def work(self, limit=10):
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            with self.db() as db:
                rows = [dict(r) for r in db.execute(
                    "SELECT * FROM receipts WHERE state IN ('queued','retry','model') AND retry_at<=? ORDER BY ts LIMIT ?",
                    (self.clock(), limit))]
            for row in rows:
                try:
                    self._process(row)
                except StoreError as exc:
                    with self.db() as db:
                        db.execute("UPDATE receipts SET state='retry',retry_at=?,error=? WHERE id=?",
                                   (self.clock()+60, str(exc), row['id']))
                        self._notice(db, row['id'], row['thread'], "pending",
                                     "Still pending: " + str(exc) + " The saved request will be reconciled; no blind create retry.")
                except Exception:
                    # Avoid logging exception payloads/credentials. Hold unknown failures.
                    with self.db() as db:
                        db.execute("UPDATE receipts SET state='held',error='Unexpected processing failure' WHERE id=?", (row['id'],))
                        self._notice(db, row['id'], row['thread'], "held", "Request saved but held after an unexpected processing failure. Operator review is required.")

    def _finish(self, row, text):
        with self.db() as db:
            db.execute("UPDATE receipts SET state='done',error=NULL WHERE id=?", (row['id'],))
            self._notice(db, row['id'], row['thread'], "result", text)

    def _process(self, row):
        cmd = json.loads(row['command']) if row['command'] else parse_command(row['text'])
        if cmd is None:
            if row['text'].lstrip().startswith(('>', '```', '/')):
                return self._finish(row, HELP)
            if self.interpreter is None:
                return self._finish(row, "Natural-language interpretation is disabled. " + HELP)
            with self.db() as db:
                outage = db.execute("SELECT value FROM settings WHERE key='model_retry'").fetchone()
                retry = float(outage[0]) if outage else 0
            if retry > self.clock():
                with self.db() as db:
                    db.execute("UPDATE receipts SET state='model',retry_at=? WHERE id=?", (retry, row['id']))
                    self._notice(db, row['id'], row['thread'], 'model-wait', 'Saved; model access is unavailable. Explicit add/search/help commands still work.')
                return
            try:
                cmd = self.interpreter(row['text'])
            except StoreError:
                with self.db() as db:
                    db.execute("INSERT OR REPLACE INTO settings VALUES ('model_retry',?)", (str(self.clock()+900),))
                    db.execute("UPDATE receipts SET state='model',retry_at=? WHERE id=?", (self.clock()+900, row['id']))
                    self._notice(db, row['id'], row['thread'], "model-wait", "Saved; model access is unavailable. I will retry later. Explicit add/search/help commands still work.")
                return
            if outage:
                with self.db() as db:
                    db.execute("DELETE FROM settings WHERE key='model_retry'")
                    self._notice(db, "model-recovery", "", "resume:" + row['id'], "Model interpretation resumed successfully; processing saved requests.")
        # Save interpretation before any destination side effect.
        with self.db() as db:
            db.execute("UPDATE receipts SET command=? WHERE id=?", (json.dumps(cmd), row['id']))
        op = cmd.get('op')
        if op in {'help', 'clarify'}:
            return self._finish(row, HELP)
        if op in {'create anyway', 'cancel'}:
            with self.db() as db:
                pending = [dict(r) for r in db.execute("SELECT * FROM receipts WHERE thread=? AND state='choice'", (row['thread'],))]
                if len(pending) != 1:
                    return self._finish(row, "No single pending choice in this thread. Reply in the original possible-match thread.")
                target = pending[0]
                if float(row['ts']) <= float(target['ts']):
                    return self._finish(row, 'This reply predates the pending addition; repeat your choice after its question.')
                db.execute("UPDATE receipts SET state=?,decision=? WHERE id=?",
                           ('queued' if op == 'create anyway' else 'done', op, target['id']))
            return self._finish(row, "Separate creation authorized; processing the saved item." if op == 'create anyway' else "Cancelled; no action item created.")
        if op == 'next':
            with self.db() as db:
                searches = db.execute("SELECT * FROM searches WHERE thread=? ORDER BY rowid DESC LIMIT 2", (row['thread'],)).fetchall()
                if len(searches) != 1:
                    return self._finish(row, "Reply next in a thread containing one search, or start a new search.")
                search = dict(searches[0])
            # Re-query current state each time. Persist selected offset in command.
            cmd = {'op': 'search', 'query': search['query'], 'all': bool(search['all_items']),
                   'offset': search['offset'], 'search_id': search['receipt']}
            with self.db() as db:
                db.execute("UPDATE receipts SET command=? WHERE id=?", (json.dumps(cmd), row['id']))
            op = 'search'
        if op not in {'search', 'add'}:
            return self._finish(row, HELP)
        store, reader = self.store_factory()
        if op == 'search':
            matches = search_actions(reader.list_actions(), cmd['query'], cmd.get('all', False))
            offset = cmd.get('offset', 0)
            selected = matches[offset:offset+5]
            text = f"Current Linear search: {len(matches)} matches; showing {offset+1 if selected else 0}–{offset+len(selected)}.\n"
            text += '\n\n'.join(line(a) for a in selected) if selected else 'No matches on this page.'
            if offset+5 < len(matches):
                text += "\nReply next for more. Each page refreshes current Linear state; edits can move results between pages."
            with self.db() as db:
                db.execute("INSERT OR REPLACE INTO searches VALUES (?,?,?,?,?)",
                           (cmd.get('search_id', row['id']), row['thread'], cmd['query'], int(cmd.get('all', False)), offset+5))
            return self._finish(row, text)
        if row['decision'] not in {'create anyway', 'creating'}:
            with self.db() as db:
                other = db.execute("SELECT 1 FROM receipts WHERE thread=? AND state='choice' AND id<>? LIMIT 1",
                                   (row['thread'], row['id'])).fetchone()
            if other:
                return self._finish(row, 'This thread already has a pending addition. Resolve it first, or submit this add as a new top-level message.')
            matches = similar_actions(reader.list_actions(), cmd['title'])
            if matches:
                with self.db() as db:
                    db.execute("UPDATE receipts SET state='choice' WHERE id=?", (row['id'],))
                    self._notice(db, row['id'], row['thread'], "choice", "Possible existing action items (including closed):\n\n" +
                                 '\n\n'.join(line(a) for a in matches[:5]) +
                                 f"\n{len(matches)} possible matches. Reply create anyway to create a separate item, or cancel.")
                return
        ts = row['ts']
        p = self.policy
        provenance = {'source_type': 'slack', 'source_scope': f'{p.workspace_id}:{p.channel_id}',
                      'source_record_id': ts, 'source_created_at': datetime.fromtimestamp(float(ts), timezone.utc).isoformat(),
                      'source_updated_at': None, 'original_content': {'text': row['text']},
                      'source_url': f'https://app.slack.com/archives/{p.channel_id}/p{ts.replace(".", "")}',
                      'source_thread_ts': row['thread'], 'source_owner_id': p.owner_id}
        identity = str(uuid5(NAMESPACE_URL, json.dumps(['second-brain', 'slack', p.workspace_id, p.channel_id, ts])))
        with self.db() as db:
            db.execute("UPDATE receipts SET decision='creating' WHERE id=?", (row['id'],))
        result = store.ensure_action(ActionDraft(identity, cmd['title'], cmd.get('details', ''), provenance))
        self._finish(row, f"Confirmed {result.identifier} in Linear: {result.url}")
