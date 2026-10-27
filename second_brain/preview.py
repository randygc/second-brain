"""The application interface: one complete five-day extraction, or an error."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from .extraction import extract_actions, matches_title


class SourceError(Exception):
    """Incomplete or invalid source reads must not look like empty successes."""


@dataclass
class CalendarWindow:
    calendar_id: str
    calendar_name: str
    timezone: str
    events: list[dict]


class CalendarSource(Protocol):
    def read_window(self, calendar_id: str, start: date, days: int) -> CalendarWindow: ...


def window_bounds(start: date, days: int, timezone: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    return (datetime.combine(start, time.min, zone),
            datetime.combine(start + timedelta(days=days), time.min, zone))


def _scheduled(raw: dict, zone: ZoneInfo) -> tuple[date, str]:
    start = raw.get("start", {})
    if "dateTime" in start:
        dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(start.get("timeZone", zone.key)))
        dt = dt.astimezone(zone)
        return dt.date(), dt.isoformat()
    if "date" in start:
        d = date.fromisoformat(start["date"])
        return d, datetime.combine(d, time.min, zone).isoformat()
    raise SourceError("A matching Calendar event has no scheduled start.")


def preview(source: CalendarSource, calendar_id: str, start: date) -> dict:
    """Fetch before producing output; callers never receive a partial report."""
    try:
        window = source.read_window(calendar_id, start, 5)
        zone = ZoneInfo(window.timezone)
        days = {(start + timedelta(days=i)).isoformat(): {
            "date": (start + timedelta(days=i)).isoformat(),
            "matching_events": 0, "action_items": 0,
        } for i in range(5)}
        matching = []
        seen_occurrences = set()
        for event in window.events:
            if not isinstance(event, dict):
                raise SourceError("Calendar returned an invalid event record.")
            if event.get("status") == "cancelled" or not matches_title(event.get("summary", "")):
                continue
            event_date, scheduled = _scheduled(event, zone)
            if event_date.isoformat() not in days:
                continue  # Google's timeMin is an overlap filter, not a start-date filter.
            identity = event.get("id")
            if not identity:
                raise SourceError("A matching Calendar event has no source identity.")
            if identity in seen_occurrences:
                continue
            seen_occurrences.add(identity)
            days[event_date.isoformat()]["matching_events"] += 1
            matching.append((scheduled, identity, event_date, event))
        matching.sort(key=lambda row: (row[0], row[1]))
        seen_records = set()
        items = []
        records = []
        for scheduled, event_id, event_date, event in matching:
            record_id = event.get("recurringEventId") or event_id
            if record_id in seen_records:
                continue
            seen_records.add(record_id)
            raw = event.get("description", "") or ""
            if not isinstance(raw, str):
                raise SourceError("Calendar returned a non-text event description.")
            extracted = extract_actions(event["summary"], raw)
            provenance = {
                "source_type": "google_calendar", "calendar_id": window.calendar_id,
                "source_record_id": record_id, "source_event_id": event_id,
                "recurring_series_id": event.get("recurringEventId"),
                "scheduled_date": event_date.isoformat(), "scheduled_start": scheduled,
                "source_created_at": event.get("created"),
                "source_updated_at": event.get("updated"),
                "original_content": {"title": event["summary"], "description": raw},
            }
            records.append({**provenance, "action_count": len(extracted)})
            for index, action in enumerate(extracted):
                # Ordinal is only a preview locator, not a future persistent identity.
                items.append({**asdict(action), "source_action_ordinal": index + 1, **provenance})
            days[event_date.isoformat()]["action_items"] += len(extracted)
        return {
            "status": "complete", "calendar_id": window.calendar_id,
            "calendar_name": window.calendar_name, "timezone": window.timezone,
            "start_date": start.isoformat(),
            "end_date_inclusive": (start + timedelta(days=4)).isoformat(),
            "daily_stats": list(days.values()), "source_records": records,
            "matching_events": sum(d["matching_events"] for d in days.values()),
            "action_count": len(items), "actions": items,
            "warnings": ["Missing original creation timestamps are recorded as null; no substitute is inferred."]
            if any(r["source_created_at"] is None for r in records) else [],
        }
    except SourceError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise SourceError("Calendar data is invalid; no successful report was generated.") from exc
