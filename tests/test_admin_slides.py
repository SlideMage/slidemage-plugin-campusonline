# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Admin slides: which slides a choice makes, their frames, the language warning and the fetch."""
from __future__ import annotations

from dataclasses import replace

import pytest

from campusonline import admin_slides, course_schedule
from campusonline.course_schedule import CourseDetail, CourseGroup, CourseSession, Lecturer

DETAIL = CourseDetail(
    number="355.001", title="Bachelorkurs (Management Science)",
    semester="Wintersemester 2026/27",
    lecturers=(
        Lecturer("Erika", "Musterfrau", "Vortragende*r"),
        Lecturer("Jürgen", "Fleiß", "Vortragende*r"),
    ),
)
GROUP = CourseGroup("Standardgruppe", (
    CourseSession("05.10.2026", "09:00", "10:00", "SR 15.25", "Abhaltung", "Vorbesprechung"),
    CourseSession("12.10.2026", "09:00", "10:00", "HS 01", "Prüfung", "Bitte Ausweis mitbringen"),
))


def test_plan_makes_a_slide_for_each_part_asked_for():
    specs = admin_slides.plan_slides("de", detail=DETAIL, lecturers=DETAIL.lecturers[1:], group=GROUP)
    assert [suffix for suffix, _ in specs] == ["Title-Slide", "Course-Sessions"]
    title, sessions = (source for _, source in specs)
    assert "Jürgen Fleiß" in title and "Erika Musterfrau" not in title
    assert r"\textbf{Datum} & \textbf{Zeit}" in sessions and "Abhaltung — Vorbesprechung" in sessions
    assert [suffix for suffix, _ in admin_slides.plan_slides("de", detail=DETAIL, lecturers=DETAIL.lecturers)] == [
        "Title-Slide"]
    assert admin_slides.plan_slides("de") == []


def test_english_deck_gets_a_translated_sessions_table():
    source = admin_slides.plan_slides("en", group=GROUP)[0][1]
    assert r"\begin{standardframe}{Course sessions}" in source
    assert r"\textbf{Date} & \textbf{Time} & \textbf{Location} & \textbf{Session}" in source
    assert r"\textbf{Standard group}" in source
    assert "SR 15.25 & Class — Preliminary meeting" in source
    # A remark with unknown words stays German rather than half-translated.
    assert "HS 01 & Exam — Bitte Ausweis mitbringen" in source
    assert "Zeit" not in source and "Abhaltungstermine" not in source


@pytest.mark.parametrize(("deck_language", "taught", "warned"), [
    ("en", ("de",), True),
    ("de", ("de",), False),
    ("en", ("de", "en"), False),
    ("de", (), False),
])
def test_language_mismatch_is_a_warning_only_when_the_course_is_taught_in_another_language(
        deck_language, taught, warned):
    text = admin_slides.language_warning(deck_language, replace(DETAIL, languages=taught))
    assert bool(text) is warned


def test_the_two_parts_of_a_fetch_fail_independently(monkeypatch):
    def broken_schedule(url):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(course_schedule, "fetch_schedule", broken_schedule)
    monkeypatch.setattr(course_schedule, "fetch_course_detail", lambda url, language: DETAIL)
    assert admin_slides.fetch("https://example.invalid", "de") == ("network unreachable", DETAIL)
