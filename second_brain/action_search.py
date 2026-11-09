"""Current-state action reads, independent of source and presentation."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from .action_store import StoreError


@dataclass(frozen=True)
class ActionSummary:
    id: str
    identifier: str
    title: str
    details: str
    status: str
    status_type: str
    url: str
    due_date: str | None = None
    archived: bool = False


def words(value):
    return re.findall(r"\w+", value.casefold())


def search_actions(actions, query, include_closed=False):
    terms = words(query)
    if not terms:
        raise StoreError("Supply search words.")
    return sorted((a for a in actions if (include_closed or (a.status_type not in {"completed", "canceled"} and not a.archived))
                   and all(t in (a.title + "\n" + a.details).casefold() for t in terms)), key=lambda a: a.identifier)


def similar_actions(actions, title):
    """Conservative deterministic warning; never merges or decides identity."""
    normalized = " ".join(words(title))
    if not normalized:
        return []
    tokens = set(words(title))
    matches = []
    for a in actions:
        other = " ".join(words(a.title))
        shared = tokens & set(words(a.title))
        if (normalized == other or SequenceMatcher(None, normalized, other).ratio() >= .80
                or (len(shared) >= 2 and len(shared) / max(1, min(len(tokens), len(set(words(a.title))))) >= .8)):
            matches.append(a)
    return sorted(matches, key=lambda a: a.identifier)


class LinearActionReader:
    """Fetch every team page or fail; never present partial data as complete."""
    def __init__(self, store):
        self.store = store

    def list_actions(self):
        self.store._destination()
        result, cursor, seen, identities = [], None, set(), set()
        document = '''query SlackActions($team: ID!, $after: String) {
          issues(first: 50, after: $after, includeArchived: true, filter: {team: {id: {eq: $team}}}) {
            nodes { id identifier title description url dueDate archivedAt team { id } state { name type } }
            pageInfo { hasNextPage endCursor }
          }
        }'''
        while True:
            data = self.store.client.query(document, {"team": self.store.team_id, "after": cursor})
            try:
                page = data["issues"]
                for node in page["nodes"]:
                    if node["team"]["id"] != self.store.team_id or node["id"] in identities:
                        raise StoreError("Conflicting Linear search identities; retry the complete search.")
                    identities.add(node["id"])
                    details = (node["description"] or "").rsplit("\n\n---\n## Import provenance\n", 1)[0]
                    result.append(ActionSummary(node["id"], node["identifier"], node["title"], details,
                                                node["state"]["name"], node["state"]["type"], node["url"],
                                                node["dueDate"], bool(node["archivedAt"])))
                info = page["pageInfo"]
                if not info["hasNextPage"]:
                    return result
                cursor = info["endCursor"]
                if not cursor or cursor in seen:
                    raise StoreError("Incomplete Linear search pagination; no partial results returned.")
                seen.add(cursor)
            except (KeyError, TypeError, AttributeError):
                raise StoreError("Incomplete Linear search response; no partial results returned.") from None
