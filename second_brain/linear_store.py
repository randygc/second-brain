"""Linear adapter: field mapping, read budgets and durable single-create recovery."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request
from uuid import uuid4

from .action_store import ActionDraft, ImportResult, SourceReview, StoreError
from .provenance import source_key, revision, fingerprint
from .source_review import REVIEW_FORMAT, review_comments, comment_matches


ENDPOINT = "https://api.linear.app/graphql"
ISSUE_FIELDS = "id identifier url title description team { id } state { id name type }"
LOOKUP = "query ImportedIssue($id: ID!) { issues(first: 2, includeArchived: true, filter: {id: {eq: $id}}) { nodes { " + ISSUE_FIELDS + " } } }"
CREATE = "mutation ImportAction($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { " + ISSUE_FIELDS + " } } }"


class LinearClient:
    """No automatic request retries, redirects, or credential-bearing error logs."""

    def __init__(self, api_key_file: Path, request_budget=30):
        try:
            self._key = api_key_file.read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeError) as exc:
            raise StoreError("Cannot read Linear API key file. Supply its local path, not the key itself.") from exc
        if not self._key or not self._key.isascii() or any(c.isspace() for c in self._key):
            raise StoreError("The Linear API key file must contain only the plain ASCII key, without quotes or extra text.")
        self.remaining = request_budget

    def query(self, document: str, variables: dict) -> dict:
        if self.remaining <= 0:
            raise StoreError("Linear request budget exhausted. No further requests sent.")
        self.remaining -= 1
        body = json.dumps({"query": document, "variables": variables}).encode()
        request = Request(ENDPOINT, body, headers={"Authorization": self._key, "Content-Type": "application/json"}, method="POST")
        try:
            # Reject redirects: the Authorization header must never follow them.
            from urllib.request import HTTPRedirectHandler, HTTPSHandler, build_opener
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            context = ssl.create_default_context()
            try:
                import certifi
            except ImportError:
                pass  # Use the platform trust store when certifi is unavailable.
            else:
                # Supplement, rather than replace, configured enterprise/system CAs.
                context.load_verify_locations(cafile=certifi.where())
            with build_opener(NoRedirect, HTTPSHandler(context=context)).open(request, timeout=30) as response:
                data = json.load(response)
                for header in ["X-RateLimit-Requests-Remaining", "X-RateLimit-Complexity-Remaining"]:
                    value = response.headers.get(header)
                    if value is not None and float(value) <= 0:
                        self.remaining = 0
        except HTTPError as exc:
            raise StoreError(f"Linear request failed (HTTP {exc.code}). No automatic retry was sent.") from None
        except (OSError, URLError, ValueError) as exc:
            raise StoreError("Linear connection/response failed. No complete result received; for imports, rerun only to reconcile the recorded identity.") from None
        if not isinstance(data, dict) or data.get("errors") or not isinstance(data.get("data"), dict):
            raise StoreError("Linear returned GraphQL errors or incomplete data. No automatic retry was sent.")
        return data["data"]


def destinations(client) -> dict:
    """Read-only discovery of the connected workspace and all accessible teams."""
    teams, cursor = [], None
    seen = set()
    while True:
        data = client.query("query Destinations($after: String) { organization { id name } teams(first: 50, after: $after) { nodes { id name key } pageInfo { hasNextPage endCursor } } }", {"after": cursor})
        try:
            organization = data["organization"]
            page = data["teams"]
            teams.extend(page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                return {"workspace": organization, "teams": teams}
            cursor = page["pageInfo"]["endCursor"]
            if not cursor or cursor in seen:
                raise StoreError("Incomplete Linear team pagination.")
            seen.add(cursor)
        except (KeyError, TypeError) as exc:
            raise StoreError("Linear returned incomplete destination information.") from exc


def _fence(text: str, language="") -> str:
    """Keep arbitrary source content from closing its own provenance code fence."""
    import re
    length = max([len(m.group()) for m in re.finditer(r"`+", text)] + [2]) + 1
    marker = "`" * length
    return f"{marker}{language}\n{text}\n{marker}"


def issue_description(draft: ActionDraft) -> str:
    p = draft.provenance
    flags = p.get("extracted_payload", {}).get("review_flags", [])
    review = "\n- Review flags (unresolved): " + ", ".join(flags) if flags else ""
    return (display_details(draft) + "\n\n---\n## Import provenance\n\n"
            f"- Source: {p['source_type']}\n- Scheduled calendar date: {p['scheduled_date']}\n"
            f"- Original source creation: {p.get('source_created_at') or 'Unavailable (not substituted)'}\n"
            f"- Source modification: {p.get('source_updated_at') or 'Unavailable'}\n"
            f"- Import identity: {draft.import_identity}{review}\n\n"
            "Original source content and portable metadata:\n\n" + _fence(json.dumps(p, ensure_ascii=False, indent=2), "json"))


def display_title(draft: ActionDraft) -> str:
    # Full text is preserved in the description and portable extraction payload.
    title = draft.title.strip()
    return title if len(title) <= 255 else title[:252] + "..."


def display_details(draft: ActionDraft) -> str:
    return ("## Full action text\n\n" + draft.title + "\n\n" + draft.details
            if len(draft.title) > 255 else draft.details)


def description_matches(description: str, draft: ActionDraft) -> bool:
    """Linear canonicalizes Markdown (blank lines and list markers).

    Compare actual action details and portable JSON, not the Markdown serializer's
    choice of bullets or spacing in the generated provenance presentation.
    """
    import re
    try:
        separators = list(re.finditer(r"(?m)^---\n", description))
        if not separators:
            return False
        divider = separators[-1]
        details, metadata = description[:divider.start()], description[divider.end():]
        match = re.search(r"(?ms)^(`{3,})json\n(.*?)\n\1\s*$", metadata)
        def canonical(value):
            value = "\n".join(line.rstrip() for line in value.splitlines() if line.strip())
            value = re.sub(r"\]\(<([^>\n]+)>\)", r"](\1)", value)
            value = re.sub(r"(?m)^( *)\\--", r"\1--", value)
            return re.sub(r"(?m)^( *)[*+-] ", r"\1- ", value)
        return (canonical(details) == canonical(display_details(draft))
                and draft.import_identity in metadata
                and match is not None
                and json.loads(match.group(2)) == draft.provenance)
    except (ValueError, TypeError, AttributeError):
        return False


class LinearActionStore:
    """Exactly one ensure operation at the destination seam.

    An owner-only SQLite journal records a random UUID v4 BEFORE any mutation.
    Later runs lookup that same UUID, including archived issues, and never create
    a replacement for an absent pending/confirmed issue. This trades automatic
    retries for safety across timeouts, crashes, deletion, and concurrent runs.
    """

    def __init__(self, client, workspace_id: str, team_id: str, journal_path: Path, backlog_state_id: str | None = None):
        self.client, self.workspace_id, self.team_id = client, workspace_id, team_id
        self.journal_path, self.backlog_state_id = journal_path, backlog_state_id
        self._destination_checked = False
        self._backlog_id = None

    def _destination(self):
        if self._destination_checked:
            return
        data = self.client.query("query ImportDestination($team: String!) { organization { id name } team(id: $team) { id name } }", {"team": self.team_id})
        if (data.get("organization") or {}).get("id") != self.workspace_id or (data.get("team") or {}).get("id") != self.team_id:
            raise StoreError("Linear workspace/team does not match the explicit destination. No write sent.")
        self._destination_checked = True

    def _backlog(self) -> str:
        if self._backlog_id:
            return self._backlog_id
        states, cursor, seen = [], None, set()
        while True:
            data = self.client.query("query ImportBacklog($team: String!, $after: String) { team(id: $team) { states(first: 50, after: $after) { nodes { id name type } pageInfo { hasNextPage endCursor } } } }", {"team": self.team_id, "after": cursor})
            try:
                page = data["team"]["states"]
                states.extend(s for s in page["nodes"] if s["type"] == "backlog")
                if not page["pageInfo"]["hasNextPage"]:
                    break
                cursor = page["pageInfo"]["endCursor"]
                if not cursor or cursor in seen:
                    raise StoreError("Incomplete Linear workflow pagination.")
                seen.add(cursor)
            except (KeyError, TypeError) as exc:
                raise StoreError("Cannot resolve the team's Backlog status.") from exc
        if self.backlog_state_id:
            states = [s for s in states if s["id"] == self.backlog_state_id]
        else:
            named = [s for s in states if s["name"].casefold() == "backlog"]
            states = named or states
        if len(states) != 1:
            raise StoreError("Select one explicit Backlog-category status for this team. No write sent.")
        self._backlog_id = states[0]["id"]
        return self._backlog_id

    def _lookup(self, issue_id):
        data = self.client.query(LOOKUP, {"id": issue_id})
        try:
            nodes = data["issues"]["nodes"]
            if len(nodes) > 1:
                raise StoreError("Linear returned conflicting destination identities.")
            if not nodes:
                return None
            issue = nodes[0]
            if issue["id"] != issue_id or issue["team"]["id"] != self.team_id:
                raise StoreError("The imported issue identity/team has changed; review it manually.")
            return issue
        except (KeyError, TypeError) as exc:
            raise StoreError("Linear lookup returned incomplete data; no write sent.") from exc

    def _journal(self):
        self.journal_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.journal_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.journal_path, 0o600)
        db = sqlite3.connect(self.journal_path, timeout=30)
        db.execute("CREATE TABLE IF NOT EXISTS imports (destination TEXT NOT NULL, import_identity TEXT NOT NULL, issue_id TEXT NOT NULL, snapshot TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0, attempted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(destination, import_identity))")
        if "attempted" not in {row[1] for row in db.execute("PRAGMA table_info(imports)")}:
            db.execute("ALTER TABLE imports ADD COLUMN attempted INTEGER NOT NULL DEFAULT 0")
            db.execute("UPDATE imports SET attempted=1")  # Old reservations may already have been sent.
            db.commit()
        db.execute("CREATE TABLE IF NOT EXISTS source_reviews (destination TEXT, source_key TEXT, revision TEXT, issue_id TEXT, comment_id TEXT, body TEXT, attempted INTEGER DEFAULT 0, confirmed INTEGER DEFAULT 0, PRIMARY KEY(destination, source_key, revision, issue_id))")
        db.commit()
        return db

    def review_source(self, observation: dict) -> SourceReview:
        """Append evidence without changing the destination's editable fields."""
        destination = json.dumps(["linear", self.workspace_id, self.team_id])
        key, version = source_key(observation), revision(observation)
        db = self._journal()
        try:
            prior = [(issue_id, json.loads(snapshot)) for issue_id, snapshot in
                     db.execute("SELECT issue_id,snapshot FROM imports WHERE destination=?", (destination,))]
            affected = [(i, p) for i, p in prior if source_key(p["provenance"]) == key]
            if not affected:
                return SourceReview("unseen")
            if all(revision(p["provenance"]) == version for _, p in affected):
                return SourceReview("unchanged")
            self._destination()
            bodies = review_comments([draft for _, draft in affected], observation)
            review_version = fingerprint([version, REVIEW_FORMAT])
            for (issue_id, baseline), body in zip(affected, bodies):
                if body is None:
                    continue
                if not self._lookup(issue_id):
                    raise StoreError("Changed source has no accessible destination. Review remains unresolved; no replacement created.")
                db.execute("INSERT OR IGNORE INTO source_reviews(destination,source_key,revision,issue_id,comment_id,body) VALUES (?,?,?,?,?,?)",
                           (destination, key, review_version, issue_id, str(uuid4()), body))
                db.commit()
                row = db.execute("SELECT comment_id,body FROM source_reviews WHERE destination=? AND source_key=? AND revision=? AND issue_id=?",
                                 (destination, key, review_version, issue_id)).fetchone()
                comment_id, saved_body = row
                def lookup():
                    data = self.client.query("query ImportReview($issue: String!, $id: ID!) { issue(id: $issue) { comments(first: 2, filter: {id: {eq: $id}}) { nodes { id body } } } }", {"issue": issue_id, "id": comment_id})
                    try:
                        nodes = data["issue"]["comments"]["nodes"]
                        if len(nodes) > 1:
                            raise StoreError("Conflicting review comment identities.")
                        return nodes[0] if nodes else None
                    except (KeyError, TypeError):
                        raise StoreError("Incomplete review lookup; no blind comment retry sent.") from None
                existing = lookup()
                if existing is None:
                    if getattr(self.client, "remaining", 2) < 2:
                        raise StoreError("Insufficient request budget for review comment and verification.")
                    claim = db.execute("UPDATE source_reviews SET attempted=1 WHERE comment_id=? AND attempted=0", (comment_id,))
                    db.commit()
                    if not claim.rowcount:
                        raise StoreError("Review comment outcome is uncertain or comment absent. No duplicate was created; inspect manually.")
                    try:
                        data = self.client.query("mutation ImportReviewComment($input: CommentCreateInput!) { commentCreate(input: $input) { success comment { id body } } }",
                                                 {"input": {"id": comment_id, "issueId": issue_id, "body": saved_body}})
                        if not (data.get("commentCreate") or {}).get("success"):
                            raise StoreError("Review comment response incomplete.")
                    except StoreError:
                        existing = lookup()
                        if existing is None:
                            raise StoreError("Review comment outcome uncertain. Reservation retained; no second write sent.") from None
                    else:
                        existing = lookup()
                    if not comment_matches((existing or {}).get("body", ""), saved_body):
                        raise StoreError("Review read-back did not preserve evidence; inspect the reserved comment.")
                db.execute("UPDATE source_reviews SET confirmed=1 WHERE comment_id=?", (comment_id,))
                db.commit()
            return SourceReview("changed", sum(body is not None for body in bodies), version)
        except sqlite3.Error as exc:
            raise StoreError("Cannot update source review journal; preserve it for recovery.") from exc
        finally:
            db.close()

    def ensure_action(self, draft: ActionDraft) -> ImportResult:
        self._destination()
        destination = json.dumps(["linear", self.workspace_id, self.team_id])
        db = self._journal()
        try:
            # Persist before network I/O; competing processes cannot both reserve.
            db.execute("BEGIN IMMEDIATE")
            for prior, in db.execute("SELECT snapshot FROM imports WHERE destination=?", (destination,)):
                p = json.loads(prior)["provenance"]
                current = draft.provenance
                keys = ["source_type", "calendar_id", "source_record_id"]
                if all(p.get(k) == current.get(k) for k in keys) and p.get("original_content") != current.get("original_content"):
                    raise StoreError("Source content changed since its initial import. No new slots or replacements were created; run batch source review before importing changed content.")
            row = db.execute("SELECT issue_id, snapshot FROM imports WHERE destination=? AND import_identity=?", (destination, draft.import_identity)).fetchone()
            first_attempt = row is None
            if first_attempt:
                issue_id = str(uuid4())
                snapshot = json.dumps(asdict(draft), ensure_ascii=False)
                db.execute("INSERT INTO imports(destination,import_identity,issue_id,snapshot) VALUES (?,?,?,?)", (destination, draft.import_identity, issue_id, snapshot))
            else:
                issue_id, snapshot = row
            db.commit()
            existing = self._lookup(issue_id)
            outcome = "existing"
            if existing is None:
                state = self._backlog()
                saved = ActionDraft(**json.loads(snapshot))
                if getattr(self.client, "remaining", 2) < 2:
                    raise StoreError("Insufficient Linear request budget for create and verification. No create sent; this reservation can resume on the next run.")
                claim = db.execute("UPDATE imports SET attempted=1 WHERE destination=? AND import_identity=? AND attempted=0", (destination, draft.import_identity))
                db.commit()
                if not claim.rowcount:
                    raise StoreError("Recorded import has no visible destination issue. Its write may be pending, the issue may be deleted, or access may have changed. No replacement was created; inspect the journal and Linear before resolving manually.")
                try:
                    data = self.client.query(CREATE, {"input": {"id": issue_id, "teamId": self.team_id,
                        "stateId": state, "title": display_title(saved), "description": issue_description(saved)}})
                    payload = data.get("issueCreate") or {}
                    created = payload.get("issue")
                    if not payload.get("success") or not created or created.get("id") != issue_id:
                        raise StoreError("Linear create result was incomplete; reconciling the reserved issue identity.")
                    outcome = "created"
                except StoreError:
                    # One read-only recovery, never a second mutation.
                    recovered = self._lookup(issue_id)
                    if recovered is None:
                        raise StoreError("Linear create outcome is uncertain. The reserved issue ID was retained; no second create was sent. Rerun to reconcile or inspect manually.") from None
                    existing = recovered
                    outcome = "reconciled"
                if outcome == "created":
                    # Validate outside the uncertain-write recovery handler:
                    # a mismatched read-back is an error, not a successful retry.
                    existing = self._lookup(issue_id)
                    if not existing or existing["state"]["id"] != state or existing["title"] != display_title(saved) or not description_matches(existing["description"], saved):
                        raise StoreError("Linear read-back did not match the requested import; inspect the reserved issue before retrying.")
            db.execute("UPDATE imports SET confirmed=1 WHERE destination=? AND import_identity=?", (destination, draft.import_identity))
            db.commit()
            return ImportResult(outcome, existing["id"], existing["identifier"], existing["url"])
        except sqlite3.Error as exc:
            raise StoreError("Cannot update the local import journal. Preserve it; do not switch journals or retry creation blindly.") from exc
        finally:
            db.close()
