# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the compact Course box says, worked out from the cached schedule alone (no Qt, no network).

The cache (``course_schedule.remember_schedule`` and ``remember_title``) holds, per installation and course, the title and
the sessions (``{date, start, end, location}``) of the course. Where a title is not cached the box shows the
course page's host and number instead, and where the sessions are not cached only the session dates it has.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import parse_qs, urlsplit

from . import course_schedule

# Weekday names by the deck's language, Monday first. Not strftime: that follows the locale.
WEEKDAYS = {
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "de": ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"),
}
NOTHING_CACHED = "No session dates cached yet — open the Course tab to load them."


@dataclass(frozen=True)
class BoxLines:
    title: str
    """The course title, or the course page's host and number when the title is not cached."""
    next_session: str
    """``"Next session: Mon 05.10.2026, 09:00–10:00, SR 15.25"`` (as much as is cached), or ``""``."""
    note: str
    """Why there is no next session (nothing cached, only past ones), or ``""``."""


def cached_entry(course_url: str) -> dict:
    """The cache's entry for the course, ``{}`` when there is none or the cache cannot be read."""
    return course_schedule.cached_entry(course_url)


def course_label(course_url: str) -> str:
    """``"Course 1002516 at online.uni-graz.at"``: what names the course when no title is cached."""
    parts = urlsplit(course_url)
    number = parse_qs(parts.query).get("pStpSpNr", [""])[0]
    host = parts.hostname or course_url
    return f"Course {number} at {host}" if number else host


def _sessions(entry: dict) -> list[tuple[date, dict]]:
    """The cached sessions with a readable date, earliest first. Plain dates become sessions with no time."""
    found = []
    raw = entry.get("sessions")
    items = raw if isinstance(raw, list) else [{"date": text} for text in entry.get("dates", [])]
    for item in items:
        try:
            found.append((datetime.strptime(item["date"], "%d.%m.%Y").date(), item))
        except (TypeError, KeyError, ValueError):
            continue
    return sorted(found, key=lambda pair: pair[0])


def _describe(day: date, item: dict, language: str) -> str:
    parts = [f"{WEEKDAYS[language][day.weekday()]} {day:%d.%m.%Y}"]
    if item.get("start"):
        parts.append(f"{item['start']}–{item['end']}" if item.get("end") else str(item["start"]))
    if item.get("location"):
        parts.append(str(item["location"]))
    return ", ".join(parts)


def box_lines(course_url: str, entry: dict, today: date | None = None, language: str = "en") -> BoxLines:
    """The box's lines for the course at `course_url` from its cache `entry`. The weekday names follow
    `language` ("de" or "en"; anything else is English). The other words stay English."""
    today = today or date.today()
    language = language if language in WEEKDAYS else "en"
    title = entry.get("title") if isinstance(entry.get("title"), str) and entry.get("title") else ""
    title = title or course_label(course_url)
    sessions = _sessions(entry)
    if not sessions:
        return BoxLines(title, "", NOTHING_CACHED)
    upcoming = [(day, item) for day, item in sessions if day >= today]
    if upcoming:
        return BoxLines(title, "Next session: " + _describe(*upcoming[0], language), "")
    last = _describe(*sessions[-1], language)
    return BoxLines(title, "", f"No upcoming session; the last was {last}.")
