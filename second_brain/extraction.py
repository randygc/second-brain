"""Source-independent action extraction with explicit, preserved line boundaries."""

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re


MARKER = re.compile(r"^actions?(?!\w)", re.IGNORECASE)
BULLET = re.compile(r"^(?:--|[-*+•](?:\s|$)|\d+[.)](?:\s|$))")
HTML_TAG = re.compile(r"</?(?:div|p|br|ul|ol|li|a|b|strong|i|em|span|pre|blockquote|h[1-6])(?:\s[^>]*|/?)>", re.I)


@dataclass
class ExtractedAction:
    text: str
    details: str = ""
    review_flags: list[str] = field(default_factory=list)


class _DescriptionHTML(HTMLParser):
    """Translate structural HTML breaks to lines; never text-wrap a paragraph.

    Original HTML is separately retained in provenance. Safe Markdown-like text
    preserves link destinations, emphasis, and list hierarchy for future stores.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.lists = []
        self.links = []
        self.pre = 0
        self.hidden = 0

    def newline(self):
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag in {"div", "p", "blockquote", "pre"} or re.fullmatch(r"h[1-6]", tag):
            self.newline()
        if tag == "br":
            self.parts.append("\n")
        elif tag in {"ul", "ol"}:
            self.newline()
            self.lists.append([tag, 0])
        elif tag == "li":
            self.newline()
            if self.lists:
                self.lists[-1][1] += 1
            marker = f"{self.lists[-1][1]}. " if self.lists and self.lists[-1][0] == "ol" else "* "
            self.parts.append("  " * max(0, len(self.lists) - 1) + marker)
        elif tag == "a":
            self.links.append(attrs.get("href", ""))
            self.parts.append("[")
        elif tag in {"b", "strong"}:
            self.parts.append("**")
        elif tag in {"i", "em"}:
            self.parts.append("_")
        if tag == "pre":
            self.pre += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        if tag == "a" and self.links:
            self.parts.append("](" + self.links.pop() + ")")
        elif tag in {"b", "strong"}:
            self.parts.append("**")
        elif tag in {"i", "em"}:
            self.parts.append("_")
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
        if tag in {"div", "p", "li", "ul", "ol", "pre", "blockquote"} or re.fullmatch(r"h[1-6]", tag):
            self.newline()
        if tag in {"ul", "ol"} and self.lists:
            self.lists.pop()

    def handle_data(self, data):
        if not self.hidden:
            # Keep literal source newlines even with inline HTML. Ignore only
            # whitespace-only layout nodes following an existing structural break.
            if self.pre:
                self.parts.append(data)
            else:
                text = data
                if not self.parts or self.parts[-1].endswith("\n"):
                    if not text.strip():
                        return
                    text = text.lstrip(" \t")
                if text:
                    self.parts.append(text)


def normalized_description(raw: str) -> str:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    if not HTML_TAG.search(raw):
        return raw
    parser = _DescriptionHTML()
    parser.feed(raw)
    parser.close()
    return "".join(parser.parts)


def matches_title(title: str) -> bool:
    # No leading whitespace/text: the marker must actually be the first word.
    return bool(MARKER.match(title))


def title_action_text(title: str) -> str | None:
    marker = MARKER.match(title)
    if not marker:
        return None
    remainder = title[marker.end():].strip()
    remainder = re.sub(r"^(?:(?:--|[:—–-])\s*)+", "", remainder).strip()
    return remainder or None


def extract_actions(title: str, raw_description: str) -> list[ExtractedAction]:
    if not matches_title(title):
        return []
    description = normalized_description(raw_description)
    title_text = title_action_text(title)
    if title_text:
        return [ExtractedAction(title_text, description)]

    actions = []
    for line in description.split("\n"):
        if not line.strip():
            if actions:
                actions[-1].details += "\n"
            continue
        stripped = line.lstrip()
        supporting = bool(BULLET.match(stripped)) or line[0].isspace()
        if supporting:
            if not actions:
                return [ExtractedAction(description, review_flags=["parentless_supporting_content"])]
            actions[-1].details += line + "\n"
        else:
            actions.append(ExtractedAction(line))
    for action in actions:
        action.details = action.details.rstrip("\n")
    return actions
