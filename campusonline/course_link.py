# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A deck's link to its course page: the preamble comment ``%% SlideMage course URL: <url>``.

A comment, so a deck with it compiles the same with or without the plugin. Only the first one in the
preamble counts; one after \\begin{document} is ordinary text. These functions read and change a deck's
text; writing it back is SlideMage's, which refuses when the file changed in the meantime.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

COURSE_URL_RE = re.compile(r"^[ \t]*%% SlideMage course URL:[ \t]*([^\r\n]*)\r?$", re.MULTILINE)
DOCUMENT_BEGIN_LINE_RE = re.compile(r"^[ \t]*\\begin\{document\}", re.MULTILINE)


def parse_course_url(text: str) -> str | None:
    """Read the first course URL marker in the deck preamble."""
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    preamble = text[:begin.start()] if begin else text
    match = COURSE_URL_RE.search(preamble)
    return match.group(1).strip() or None if match else None


def normalize_course_url(url: str) -> str:
    """Accept a browser-safe HTTP(S) URL for a deck's course page."""
    clean = url.strip()
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in clean):
        raise ValueError("Course link must not contain spaces or control characters.")
    try:
        parts = urlsplit(clean)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError("Enter a full http:// or https:// course URL.")
        _ = parts.port  # Reject malformed ports before storing the URL.
    except ValueError as exc:
        raise ValueError(f"Invalid course URL: {exc}") from exc
    return clean


def _line_span(text: str, start: int, end: int) -> tuple[int, int]:
    """The whole line(s) around text[start:end], with the line terminator."""
    line_start = text.rfind("\n", 0, start) + 1  # 0 if not found, i.e. first line of file
    nl_after = text.find("\n", end)
    return line_start, len(text) if nl_after == -1 else nl_after + 1


def course_url_text(text: str, url: str, deck_name: str) -> str:
    """`text` with its course-URL comment set to `url` (removed when empty)."""
    clean = normalize_course_url(url) if url.strip() else ""
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    if begin is None and clean:
        raise ValueError(f"{deck_name} has no \\begin{{document}} to place the course link before.")
    preamble_end = begin.start() if begin else len(text)
    for match in reversed(list(COURSE_URL_RE.finditer(text, 0, preamble_end))):
        line_start, line_end = _line_span(text, match.start(), match.end())
        text = text[:line_start] + text[line_end:]
    if not clean:
        return text
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    return (
        text[:begin.start()]
        + f"%% SlideMage course URL: {clean}{newline}"
        + text[begin.start():]
    )
