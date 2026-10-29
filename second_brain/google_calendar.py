"""Google Calendar adapter. Only raw JSON reads; no Markdown conversion."""

from datetime import date
import json
from pathlib import Path
from urllib.parse import quote

from .preview import CalendarWindow, SourceError, window_bounds
from .local_files import private_write


EVENT_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned.readonly"
SHARED_EVENT_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
METADATA_SCOPE = "https://www.googleapis.com/auth/calendar.calendars.readonly"
SCOPES = [EVENT_SCOPE, METADATA_SCOPE]
BASE_URL = "https://www.googleapis.com/calendar/v3/calendars/"


def authorize(client_secrets: Path, token_file: Path, include_shared: bool = False) -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise SourceError("Install Google support: python -m pip install -e '.[google]'") from exc
    try:
        config = json.loads(client_secrets.read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict) or not isinstance(config.get("installed"), dict):
            raise SourceError("Use a Google OAuth Desktop app client JSON file.")
        # Use Google's maintained OAuth library, including state and PKCE.
        scopes = [SHARED_EVENT_SCOPE if include_shared else EVENT_SCOPE, METADATA_SCOPE]
        flow = InstalledAppFlow.from_client_config(config, scopes=scopes, autogenerate_code_verifier=True)
        credentials = flow.run_local_server(
            host="127.0.0.1", port=0, timeout_seconds=300,
            authorization_prompt_message="Open this Google authorization URL in your browser:\n{url}",
            success_message="Read-only Calendar authorization complete. You can close this tab.",
            access_type="offline", prompt="consent",
        )
        private_write(token_file, credentials.to_json())
    except SourceError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SourceError("The client credentials file is not valid JSON. Download the original Desktop OAuth client JSON from Google Cloud; do not copy it through a document editor.") from exc
    except FileNotFoundError as exc:
        raise SourceError("The client credentials file was not found. Check --client-secrets.") from exc
    except PermissionError as exc:
        raise SourceError("Cannot read the credentials or save the token. Check local file permissions.") from exc
    except Exception as exc:
        # OAuth exceptions can contain codes or tokens; never echo the details.
        raise SourceError("Google authorization failed. Check your Desktop client, consent setup and account; retry auth.") from exc


def authorized_session(token_file: Path):
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import AuthorizedSession
    except ImportError as exc:
        raise SourceError("Install Google support: python -m pip install -e '.[google]'") from exc
    try:
        credentials = Credentials.from_authorized_user_file(str(token_file))
        return AuthorizedSession(credentials)
    except Exception as exc:
        raise SourceError("Cannot load local Google credentials. Run the auth command first.") from exc


class GoogleCalendarSource:
    """A raw REST adapter; injected session supports contract tests without credentials."""

    def __init__(self, session):
        self.session = session
        self._lifecycle_calendars = set()

    def _get(self, url, params=None, *, deleted_id=None):
        try:
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code == 410 and deleted_id is not None:
                error = response.json().get("error", {})
                reasons = [item.get("reason") for item in error.get("errors", [])]
                if reasons == ["deleted"]:
                    return {"id": deleted_id, "status": "cancelled", "deletion_evidence": "http410_deleted"}
            if response.status_code != 200:
                raise SourceError(f"Google Calendar read failed (HTTP {response.status_code}); no complete report produced.")
            result = response.json()
            if not isinstance(result, dict) or "error" in result:
                raise SourceError("Google Calendar returned an invalid response.")
            return result
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError("Google Calendar connection or authorization failed; no complete report produced.") from exc

    def calendar_timezone(self, calendar_id: str) -> str:
        endpoint = BASE_URL + quote(calendar_id, safe="")
        metadata = self._get(endpoint, {"fields": "id,timeZone"})
        if metadata.get("id") != calendar_id or not isinstance(metadata.get("timeZone"), str):
            raise SourceError("Calendar identity/timezone could not be verified.")
        return metadata["timeZone"]

    def read_lifecycle(self, calendar_id: str, source_record_id: str) -> dict:
        """GET the saved event/series identity; never infer deletion from absence."""
        endpoint = BASE_URL + quote(calendar_id, safe="")
        if calendar_id not in self._lifecycle_calendars:
            metadata = self._get(endpoint, {"fields": "id"})
            if metadata.get("id") != calendar_id:
                raise SourceError("Calendar identity/access could not be verified; no deletion inferred.")
            self._lifecycle_calendars.add(calendar_id)
        event = self._get(endpoint + "/events/" + quote(source_record_id, safe=""),
                          {"fields": "id,status,updated,recurringEventId"}, deleted_id=source_record_id)
        if event.get("id") != source_record_id:
            raise SourceError("Calendar lifecycle response has the wrong event identity.")
        # The journal stores series IDs. A returned exception is not whole-series evidence.
        if event.get("recurringEventId"):
            raise SourceError("Received a recurring occurrence instead of the recorded source; no series deletion inferred.")
        status = event.get("status")
        if status not in {"confirmed", "tentative", "cancelled"}:
            raise SourceError("Calendar lifecycle response has no recognized status.")
        return {"source_type": "google_calendar", "calendar_id": calendar_id,
                "source_record_id": source_record_id, "source_status": status,
                "source_updated_at": event.get("updated"),
                "deletion_evidence": (event.get("deletion_evidence", "calendar_cancelled")
                                      if status == "cancelled" else None)}

    def read_window(self, calendar_id: str, start: date, days: int) -> CalendarWindow:
        endpoint = BASE_URL + quote(calendar_id, safe="")
        metadata = self._get(endpoint, {"fields": "id,summary,timeZone"})
        timezone = metadata.get("timeZone")
        if not timezone:
            raise SourceError("Calendar timezone is missing; refusing to guess date boundaries.")
        lower, upper = window_bounds(start, days, timezone)
        params = {
            "timeMin": lower.isoformat(), "timeMax": upper.isoformat(),
            "timeZone": timezone, "singleEvents": "true", "orderBy": "startTime",
            "showDeleted": "false", "maxResults": 2500,
            "fields": "nextPageToken,items(id,status,summary,description,created,updated,start,recurringEventId)",
        }
        events = []
        seen_tokens = set()
        while True:
            page = self._get(endpoint + "/events", params.copy())
            if not isinstance(page.get("items", []), list):
                raise SourceError("Calendar returned an invalid event page.")
            events.extend(page.get("items", []))
            token = page.get("nextPageToken")
            if not token:
                break
            if token in seen_tokens:
                raise SourceError("Calendar pagination repeated a token; retrieval is incomplete.")
            seen_tokens.add(token)
            params["pageToken"] = token
        return CalendarWindow(metadata.get("id", calendar_id), metadata.get("summary", calendar_id), timezone, events)


class JSONCalendarSource:
    """Replay a complete raw Calendar response for offline extraction/reporting.

    Input is explicitly raw API data, not chat-connector Markdown or an automatic
    newline reconstruction. Reject pagination markers rather than misreport totals.
    """

    def __init__(self, path: Path):
        self.path = path

    def read_window(self, calendar_id: str, start: date, days: int) -> CalendarWindow:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("nextPageToken"):
                raise SourceError("Input contains an incomplete paginated response.")
            if not isinstance(data["items"], list):
                raise SourceError("Input items must be a list.")
            if data.get("calendarId", calendar_id) != calendar_id:
                raise SourceError("Input calendar identity differs from the requested calendar.")
            return CalendarWindow(calendar_id, data.get("summary", calendar_id), data["timeZone"], data["items"])
        except SourceError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SourceError("Cannot read complete raw Calendar JSON (requires timeZone and items).") from exc
