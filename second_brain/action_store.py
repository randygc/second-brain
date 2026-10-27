"""Destination-independent single-action and bounded batch ingestion."""

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


def plan_batch(report: dict) -> list[ActionDraft]:
    """Freeze initial ordinal slots, never derive identity from action wording.

    A destination must reject a changed source snapshot before assigning any new
    slots. This slice imports unchanged snapshots; change reconciliation is #5.
    """
    if not isinstance(report, dict) or report.get("status") != "complete":
        raise StoreError("Only a complete five-day extraction can be imported.")
    try:
        actions = report["actions"]
        if not isinstance(actions, list) or report["action_count"] != len(actions):
            raise StoreError("Extraction action count is inconsistent.")
        if len(report["daily_stats"]) != 5 or sum(d["action_items"] for d in report["daily_stats"]) != len(actions):
            raise StoreError("Five-day extraction statistics are inconsistent.")
        drafts, seen, groups = [], set(), {}
        for action in actions:
            p = {key: action.get(key) for key in ["source_type", "calendar_id", "source_record_id", "source_event_id",
                 "recurring_series_id", "source_created_at", "source_updated_at", "scheduled_date", "scheduled_start", "original_content"]}
            if not all(p[k] for k in ["source_type", "calendar_id", "source_record_id", "source_event_id", "scheduled_date"]):
                raise StoreError("An action is missing source identity or scheduled date.")
            ordinal = action["source_action_ordinal"]
            if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
                raise StoreError("An action has an invalid source ordinal.")
            text, details = action["text"], action["details"]
            if not isinstance(text, str) or not text.strip() or not isinstance(details, str):
                raise StoreError("An action has invalid extracted text/details.")
            title_defined = title_action_text(p["original_content"]["title"])
            group_key = (p["source_type"], p["calendar_id"], p["source_record_id"])
            group = groups.setdefault(group_key, {"original": p["original_content"], "ordinals": []})
            if group["original"] != p["original_content"]:
                raise StoreError("A source record contains inconsistent original snapshots.")
            group["ordinals"].append(ordinal)
            if title_defined:
                if ordinal != 1 or title_defined != text:
                    raise StoreError("A title-defined source must have exactly its one title action.")
                slot = "title"  # Compatible with the identity already created by #3.
            else:
                slot = f"line:{ordinal}"
            identity_parts = ["second-brain", "v1", p["source_type"], p["calendar_id"], p["source_record_id"], slot]
            identity = str(uuid5(NAMESPACE_URL, json.dumps(identity_parts, separators=(",", ":"))))
            if identity in seen:
                raise StoreError("Extraction contains duplicate action slots. No batch writes sent.")
            seen.add(identity)
            flags = action.get("review_flags", [])
            if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
                raise StoreError("An action has invalid review flags.")
            p["source_action_ordinal"] = ordinal
            p["extracted_payload"] = {"text": text, "details": details, "review_flags": flags}
            drafts.append(ActionDraft(identity, text, details, p))
        if any(sorted(g["ordinals"]) != list(range(1, len(g["ordinals"]) + 1)) for g in groups.values()):
            raise StoreError("Source action ordinals are incomplete; regenerate the full preview.")
        return drafts
    except (KeyError, TypeError, AttributeError) as exc:
        raise StoreError("Invalid batch extraction payload; regenerate preview before importing.") from exc


def import_batch(report: dict, store: ActionStore) -> dict:
    drafts = plan_batch(report)  # Validate the whole batch before any writes.
    results = []
    counts = {"created": 0, "already_imported": 0, "reconciled": 0, "failed": 0}
    for draft in drafts:
        row = {"import_identity": draft.import_identity, "source_record_id": draft.provenance["source_record_id"],
               "scheduled_date": draft.provenance["scheduled_date"]}
        try:
            result = store.ensure_action(draft)
            outcome = "already_imported" if result.outcome == "existing" else result.outcome
            if outcome not in {"created", "already_imported", "reconciled"}:
                raise StoreError("Destination returned an unsupported import outcome.")
            counts[outcome] += 1
            row.update(outcome=outcome, destination_id=result.destination_id, identifier=result.identifier, url=result.url)
        except StoreError as exc:
            counts["failed"] += 1
            row.update(outcome="failed", error=str(exc))
        results.append(row)
    return {"status": "partial_failure" if counts["failed"] else "complete", "counts": counts,
            "daily_stats": report["daily_stats"], "matching_events": report["matching_events"],
            "action_count": len(drafts), "results": results}
