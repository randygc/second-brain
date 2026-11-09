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
