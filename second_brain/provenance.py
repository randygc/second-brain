"""Portable source observations; occurrence dates are not recurring revisions."""

import hashlib
import json


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def source_key(record: dict) -> str:
    return json.dumps([record["source_type"], record["calendar_id"], record["source_record_id"]], separators=(",", ":"))


def revision(record: dict) -> str:
    if record.get("source_status") in {"cancelled", "deleted"}:
        # Tombstone timestamps/HTTP representation may vary; one unresolved flag.
        return fingerprint({"source_lifecycle": "deleted_or_cancelled"})
    content = (fingerprint(record["original_content"]) if "original_content" in record
               else record["content_fingerprint"])
    schedule = None if record.get("recurring_series_id") else [record.get("scheduled_date"), record.get("scheduled_start")]
    return fingerprint({"content": content, "schedule": schedule})
