"""Review confirmed source deletion without inferring it from window absence."""

from typing import Protocol

from .action_store import ActionStore, StoreError
from .preview import SourceError
from .provenance import source_key


class LifecycleSource(Protocol):
    def read_lifecycle(self, calendar_id: str, source_record_id: str) -> dict:
        """Return explicit status evidence for this record, or raise SourceError."""
        ...


def review_deleted_sources(source: LifecycleSource, store: ActionStore, calendar_id: str, *, execute=False, limit=100) -> dict:
    """Check known identities independently of dates; default to a read-only plan.

    Read errors remain errors, including 404/access/expired-sync responses. Only
    explicit deletion evidence may cross the action-store review interface.
    """
    records = store.imported_sources(calendar_id)
    if len(records) > limit:
        raise StoreError("Source review exceeds the bounded record limit. Increase --max-records explicitly; no checks or comments sent.")
    results = []
    counts = {"active": 0, "planned": 0, "flagged": 0, "failed": 0}
    affected = 0
    for record in records:
        row = {"source_record_id": record["source_record_id"]}
        try:
            evidence = source.read_lifecycle(calendar_id, record["source_record_id"])
            if source_key(evidence) != source_key(record):
                raise SourceError("Source lifecycle response does not match the recorded identity.")
            status = evidence.get("source_status")
            if status in {"confirmed", "tentative"}:
                outcome = "active"
            elif status in {"cancelled", "deleted"} and evidence.get("deletion_evidence") in {"calendar_cancelled", "http410_deleted"}:
                if execute:
                    review = store.review_source({**record, **evidence})
                    if review.outcome != "changed":
                        raise StoreError("Destination did not confirm deletion review.")
                    row["affected_actions"] = review.affected_actions
                    affected += review.affected_actions
                    outcome = "flagged"
                else:
                    outcome = "planned"
                row["source_status"] = status
                row["evidence"] = evidence["deletion_evidence"]
            else:
                raise SourceError("Source did not return reliable lifecycle evidence; no deletion inferred.")
            counts[outcome] += 1
            row["outcome"] = outcome
        except (SourceError, StoreError) as exc:
            counts["failed"] += 1
            row.update(outcome="failed", error=str(exc))
        results.append(row)
    return {"status": "partial_failure" if counts["failed"] else "complete", "mode": "execute" if execute else "plan_only",
            "checked_sources": len(records), "counts": counts, "affected_existing_actions": affected, "results": results}
