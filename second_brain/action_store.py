"""Small destination-independent interface for one explicitly selected action."""

from dataclasses import dataclass
import json
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from .extraction import title_action_text


class StoreError(Exception):
    """Safe-to-display destination error, without credentials or response bodies."""


@dataclass(frozen=True)
class ActionDraft:
    import_identity: str
    title: str
    details: str
    provenance: dict


@dataclass(frozen=True)
class ImportResult:
    outcome: str
    destination_id: str
    identifier: str
    url: str


class ActionStore(Protocol):
    def ensure_action(self, draft: ActionDraft) -> ImportResult:
        """Create once or return an existing action, preserving user edits.

        Errors may indicate an uncertain write; callers must never blindly retry
        creation. The adapter owns destination identity, persistence and recovery.
        """
        ...


def select_title_action(report: dict, source_record_id: str) -> ActionDraft:
    if not isinstance(report, dict) or report.get("status") != "complete":
        raise StoreError("Only a complete five-day extraction can be imported.")
    if not isinstance(report.get("actions"), list) or any(not isinstance(a, dict) for a in report["actions"]):
        raise StoreError("Invalid extraction actions; regenerate the preview before importing.")
    selected = [a for a in report.get("actions", []) if a.get("source_record_id") == source_record_id]
    if len(selected) != 1:
        raise StoreError("Select exactly one title-defined source record; full-set import is not available in this slice.")
    action = selected[0]
    try:
        original = action["original_content"]
        if title_action_text(original["title"]) != action["text"]:
            raise StoreError("The selected record is not a title-defined action. Regenerate the preview if it was edited.")
        # The title slot is stable across source title edits and recurrence windows.
        # Multiple-action slots are deliberately deferred to the next slice.
        identity_parts = ["second-brain", "v1", action["source_type"], action["calendar_id"], source_record_id, "title"]
        identity = str(uuid5(NAMESPACE_URL, json.dumps(identity_parts, separators=(",", ":"))))
        keys = ["source_type", "calendar_id", "source_record_id", "source_event_id",
                "recurring_series_id", "source_created_at", "source_updated_at",
                "scheduled_date", "scheduled_start", "original_content"]
        provenance = {key: action.get(key) for key in keys}
        if not all(provenance[k] for k in ["source_type", "calendar_id", "source_record_id", "source_event_id", "scheduled_date"]):
            raise StoreError("The selected action is missing source identity or scheduled date.")
        return ActionDraft(identity, action["text"], action["details"], provenance)
    except (KeyError, TypeError) as exc:
        raise StoreError("Invalid extraction payload; regenerate the preview before importing.") from exc


def import_one(report: dict, source_record_id: str, store: ActionStore) -> ImportResult:
    return store.ensure_action(select_title_action(report, source_record_id))
