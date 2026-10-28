"""Portable, conservative correspondence and readable source-change reviews."""

import re

from .extraction import extract_actions, matches_title, title_action_text


REVIEW_FORMAT = "readable-v2"


def _name(text):
    return " ".join(text.split()).casefold()


def _payload(action):
    return action.text + ("\n\n" + action.details if action.details else "")


def review_comments(originals: list[dict], observation: dict) -> list[str | None]:
    """Return a review or None for each original action, without ordinal shifts.

    Match unique names, then unique prefix edits. A title-defined record with
    one original and one current action retains its title slot across renames.
    Ambiguous correspondence is presented for review, never asserted as removal.
    """
    if observation.get("source_status") in {"cancelled", "deleted"}:
        timestamp = observation.get("source_updated_at") or "Unavailable in source"
        scope = "recurring series" if any(d["provenance"].get("recurring_series_id") for d in originals) else "event"
        return [("## Calendar source deleted or cancelled — unresolved\n\n"
                 f"Calendar source updated: {timestamp}\n\n"
                 f"Google Calendar explicitly reports that the source {scope} was deleted or cancelled.\n\n"
                 + d["title"] + ("\n\n" + d["details"] if d["details"] else "")
                 + "\n\nReview whether this Linear issue is still needed. Its content, provenance and workflow status have been retained. No automatic deletion or resolution was performed.")
                for d in originals]
    raw = observation.get("original_content")
    available = raw is not None and matches_title(raw.get("title", ""))
    current = extract_actions(raw["title"], raw.get("description", "")) if available else []
    old_names = [_name(d["title"]) for d in originals]
    new_names = [_name(a.text) for a in current]
    mapping, remaining_old, remaining_new = {}, set(range(len(originals))), set(range(len(current)))
    for relation in [lambda a, b: a == b,
                     lambda a, b: len(a) >= 20 and len(b) >= 20 and (a.startswith(b) or b.startswith(a))]:
        candidates = {i: [j for j in remaining_new if relation(old_names[i], new_names[j])] for i in remaining_old}
        pairs = [(i, js[0]) for i, js in candidates.items() if len(js) == 1
                 and sum(js[0] in others for others in candidates.values()) == 1]
        for i, j in pairs:
            mapping[i] = j
            remaining_old.remove(i)
            remaining_new.remove(j)
    if (len(originals) == len(current) == 1 and available
            and title_action_text(originals[0]["provenance"]["original_content"]["title"])
            and title_action_text(raw["title"])):
        mapping[0] = 0
        remaining_old.clear()
        remaining_new.clear()
    timestamp = observation.get("source_updated_at") or "Unavailable in source"
    header = f"## Source changed — unresolved\n\nCalendar source updated: {timestamp}\n\n"
    bodies = []
    for i, original in enumerate(originals):
        if i in mapping:
            action = current[mapping[i]]
            baseline = original["provenance"]
            schedule_changed = (not baseline.get("recurring_series_id") and
                                any(baseline.get(k) != observation.get(k)
                                    for k in ["scheduled_date", "scheduled_start"]))
            flags = baseline.get("extracted_payload", {}).get("review_flags", [])
            if (comment_matches(original["title"], action.text)
                    and comment_matches(original["details"], action.details)
                    and flags == action.review_flags and not schedule_changed):
                bodies.append(None)
                continue
            body = header + _payload(action)
            if schedule_changed:
                body += ("\n\nScheduled Calendar date changed: "
                         + str(baseline.get("scheduled_date")) + " → " + str(observation.get("scheduled_date")))
        else:
            in_details = any(old_names[i] in _name(a.details) for a in current)
            if available and (in_details or not remaining_new):
                body = (header + "This action no longer appears as a separate action in the Calendar event. "
                        "It may have been removed from the Calendar event or added as a bullet to another action.\n\n"
                        "Suggested action: delete this Linear issue after reviewing the updated Calendar content.")
                if in_details:
                    parents = [a for a in current if old_names[i] in _name(a.details)]
                    body += "\n\nUpdated action containing this text:\n\n" + "\n\n".join(_payload(a) for a in parents)
            else:
                body = header + "A corresponding updated action could not be identified confidently. Review before editing or deleting this issue."
                if current:
                    body += "\n\nUpdated Calendar actions:\n\n" + "\n\n---\n\n".join(_payload(a) for a in current)
                elif not available:
                    body += " The event no longer has an action title, or its full updated content is unavailable."
        bodies.append(body)
    return bodies


def comment_matches(actual: str, expected: str) -> bool:
    """Allow Linear's display-only Markdown canonicalization on read-back."""
    def canonical(text):
        text = re.sub(r"\]\(<([^>\n]+)>\)", r"](\1)", text)
        text = re.sub(r"(?m)^( *)\\--", r"\1--", text)
        text = re.sub(r"(?m)^( *)[*+-] ", r"\1- ", text)
        return "\n".join(line.rstrip().replace("\u00a0", " ") for line in text.splitlines() if line.strip())
    return canonical(actual) == canonical(expected)
