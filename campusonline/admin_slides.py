# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Admin slides: a title slide and/or a course-sessions table generated from the online course
a deck links (the Course tab of Deck settings).

The slides follow the deck's own \\decklanguage: an English deck gets English table headings, its
German schedule terms translated (course_schedule.translate_schedule()), UGO's English course
title and semester on the title slide, and EN instead of DE in the new slides' id-slugs.

This module plans the slides as LaTeX frames; making slide files of them and adding them to the deck
is SlideMage's.
"""
from __future__ import annotations

from . import course_schedule

LANGUAGE_NAMES = {"de": "German", "en": "English"}
TITLE_SLIDE, SESSIONS_SLIDE = "Title-Slide", "Course-Sessions"


def fetch(url: str, language: str) -> tuple[object, object]:
    """(schedule, detail) of the course at `url`, each independently: a CourseSchedule /
    CourseDetail, or the error text when that part failed (a course with no public session list
    still offers its title slide)."""
    try:
        schedule: object = course_schedule.fetch_schedule(url)
    except Exception as exc:  # noqa: BLE001 -- shown to the user as the reason it is unavailable
        schedule = str(exc)
    try:
        detail: object = course_schedule.fetch_course_detail(url, language)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
    return schedule, detail


def language_warning(language: str, detail: course_schedule.CourseDetail) -> str:
    """Why the deck's language doesn't fit the course ("" when it does or the course names none) --
    most often a deck with no \\decklanguage, which counts as English."""
    if not detail.languages or language in detail.languages:
        return ""
    taught = " and ".join(LANGUAGE_NAMES.get(key, key.upper()) for key in detail.languages)
    deck = LANGUAGE_NAMES.get(language, language)
    return (f"Warning: this course is taught in {taught}, but the deck is {deck} -- "
            f"the slides will be {deck}. Check the deck's \\decklanguage if that's unintended.")


def sessions_frame(table: str, language: str = "de") -> str:
    """The frame around a sessions table, titled in `language`."""
    title = course_schedule.LABELS.get(language, course_schedule.LABELS["de"])["title"]
    return "\n".join((r"\begin{standardframe}{" + title + "}", table.strip(), r"\end{standardframe}"))


def plan_slides(
    language: str, *, detail: course_schedule.CourseDetail | None = None,
    lecturers: tuple[course_schedule.Lecturer, ...] = (),
    group: course_schedule.CourseGroup | None = None,
) -> list[tuple[str, str]]:
    """The ``(id_suffix, frame)`` of every slide wanted: a title slide when `detail` is given
    (naming `lecturers`), a sessions table when `group` is."""
    specs: list[tuple[str, str]] = []
    if detail is not None:
        specs.append((TITLE_SLIDE, course_schedule.render_title_slide(detail, lecturers)))
    if group is not None:
        if language == "en":
            group = course_schedule.translate_schedule(course_schedule.CourseSchedule((group,))).groups[0]
        table = course_schedule.render_group_table(group, language)
        specs.append((SESSIONS_SLIDE, sessions_frame(table, language)))
    return specs
