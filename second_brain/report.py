"""Static, escaped report artifacts. Source HTML is displayed, never executed."""

from html import escape
import json
from pathlib import Path

from .local_files import private_write


def render_html(report: dict) -> str:
    e = lambda value: escape(str(value))
    rows = "".join(
        f'<tr><td>{e(d["date"])}</td><td>{d["matching_events"]}</td><td>{d["action_items"]}</td></tr>'
        for d in report["daily_stats"]
    )
    cards = []
    for action in report["actions"]:
        flags = ", ".join(action["review_flags"])
        cards.append(
            '<article>'
            f'<p class="meta">{e(action["scheduled_date"])} · Google Calendar · {e(action["original_content"]["title"])}</p>'
            f'<h3>{e(action["text"])}</h3>'
            + (f'<p class="flag">Review: {e(flags)}</p>' if flags else '')
            + f'<pre>{e(action["details"])}</pre>'
            f'<p class="meta">Original creation timestamp: {e(action["source_created_at"] or "Unavailable from source")}</p>'
            '<details><summary>Full original source content and identity</summary>'
            f'<pre>{e(json.dumps(action["original_content"], ensure_ascii=False, indent=2))}</pre>'
            f'<pre>{e(action["source_record_id"])}</pre></details></article>'
        )
    # A matching marker-only event may be empty; do not silently lose its evidence.
    empty = "".join(
        f'<article><h3>Empty matching event: {e(r["original_content"]["title"])}</h3>'
        f'<p>{e(r["scheduled_date"])} · No independent actions</p></article>'
        for r in report["source_records"] if not r["action_count"]
    )
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
        '<title>Second Brain — Calendar extraction</title><style>'
        'body{font:16px/1.6 system-ui;background:#f4f5f1;color:#21372b;margin:0}'
        'main{max-width:1000px;margin:36px auto;padding:0 18px}h1{margin-bottom:0}'
        'table{border-collapse:collapse;width:100%;background:white}th,td{padding:10px;text-align:left;border-bottom:1px solid #ddd}'
        'article{background:white;padding:20px;border:1px solid #ddd;border-radius:10px;margin:18px 0}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}h3{overflow-wrap:anywhere}'
        '.meta{color:#516556;font-size:14px}.flag{color:#86430b}summary{cursor:pointer}'
        '</style></head><body><main><h1>Action extraction</h1>'
        f'<p>{e(report["calendar_name"])} · {e(report["start_date"])}–{e(report["end_date_inclusive"])} · {e(report["timezone"])}</p>'
        f'<p>Complete read · {report["matching_events"]} matching occurrences · {report["action_count"]} independent actions</p>'
        '<p>Recurring actions appear once per series, on its earliest matching date in this window. This is a local report with no lifecycle controls.</p>'
        + ''.join(f'<p class="flag">{e(w)}</p>' for w in report["warnings"])
        + '<h2>Daily statistics</h2><table><thead><tr><th>Date</th><th>Matching events</th><th>Action items</th></tr></thead><tbody>'
        + rows + '</tbody></table><h2>Extracted actions and details</h2>'
        + ''.join(cards) + empty
        + ('<p>No matching action events in this window.</p>' if not report["matching_events"] else '')
        + '</main></body></html>')


def write_report(report: dict, output_dir: Path) -> None:
    # Build both in memory before replacing either artifact. Errors propagate;
    # callers print success only when both writes complete.
    html = render_html(report)
    data = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    private_write(output_dir / "report.json", data)
    private_write(output_dir / "report.html", html)
