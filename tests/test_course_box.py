# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Course box: its lines from the cache (pure), and the built box."""
from __future__ import annotations

import json
from datetime import date

import pytest

pytest.importorskip("slidemage.plugin_api", reason="SlideMage's plugin API is not installed")

from campusonline import course_box, course_schedule
from fake_host import FakeHost

URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"
DECK = f"\\documentclass{{beamer}}\n%% SlideMage course URL: {URL}\n\\begin{{document}}\n\\end{{document}}\n"
TODAY = date(2026, 10, 10)


def test_label_names_course_and_host_when_there_is_no_title():
    assert course_box.course_label(URL) == "Course 1002516 at online.uni-graz.at"
    assert course_box.course_label("https://x.example/a") == "x.example"


def test_next_session_is_the_first_one_not_past():
    lines = course_box.box_lines(URL, {"dates": ["12.10.2026", "05.10.2026", "19.10.2026"]}, TODAY)
    assert lines.title == "Course 1002516 at online.uni-graz.at"
    assert lines.next_session == "Next session: Mon 12.10.2026" and lines.note == ""


@pytest.mark.parametrize("language, weekday", [("de", "Di"), ("en", "Tue"), ("fr", "Tue"), (None, "Tue")])
def test_weekday_follows_the_deck_language_and_unknown_means_english(language, weekday):
    lines = course_box.box_lines(URL, {"dates": ["31.12.2999"]}, TODAY, language=language)
    assert lines.next_session == f"Next session: {weekday} 31.12.2999"


def test_german_weekdays_for_past_sessions_too():
    lines = course_box.box_lines(URL, {"dates": ["06.10.2026"]}, TODAY, language="de")
    assert lines.note == "No upcoming session; the last was Di 06.10.2026."


def test_today_counts_as_upcoming():
    assert "10.10.2026" in course_box.box_lines(URL, {"dates": ["10.10.2026"]}, TODAY).next_session


def test_default_today_is_evaluated_on_every_call(monkeypatch):
    class Clock:
        day = TODAY

        @classmethod
        def today(cls):
            return cls.day

    monkeypatch.setattr(course_box, "date", Clock)
    entry = {"dates": ["10.10.2026", "11.10.2026"]}
    assert "10.10.2026" in course_box.box_lines(URL, entry).next_session
    Clock.day = date(2026, 10, 11)
    assert "11.10.2026" in course_box.box_lines(URL, entry).next_session


def test_title_time_and_room_when_cached():
    entry = {"title": "Management Science", "sessions": [
        {"date": "05.10.2026", "start": "09:00", "end": "10:00", "location": "SR 1"},
        {"date": "12.10.2026", "start": "09:00", "end": "10:30", "location": "HS 01"}]}
    lines = course_box.box_lines(URL, entry, TODAY)
    assert lines.title == "Management Science"
    assert lines.next_session == "Next session: Mon 12.10.2026, 09:00–10:30, HS 01"


@pytest.mark.parametrize("entry", [{}, {"dates": []}, {"dates": ["garbage"]}, {"sessions": "x"}])
def test_nothing_cached(entry):
    lines = course_box.box_lines(URL, entry, TODAY)
    assert (lines.next_session, lines.note) == ("", course_box.NOTHING_CACHED)


def test_past_sessions_only():
    lines = course_box.box_lines(URL, {"dates": ["05.10.2026", "06.10.2026"]}, TODAY)
    assert lines.next_session == ""
    assert lines.note == "No upcoming session; the last was Tue 06.10.2026."


def test_cached_entry_reads_the_plugin_cache(tmp_path):
    course_schedule.use_cache_folder(tmp_path)
    try:
        assert course_box.cached_entry(URL) == {}
        (tmp_path / "course-schedules.json").write_text(json.dumps({"1002516": {"dates": ["05.10.2026"]}}))
        assert course_box.cached_entry(URL) == {"dates": ["05.10.2026"]}
        assert course_box.cached_entry("not a course url") == {}
        (tmp_path / "course-schedules.json").write_text("{broken")
        assert course_box.cached_entry(URL) == {}
    finally:
        course_schedule.use_cache_folder(None)


def test_box_shows_the_title_and_sessions_the_plugin_stored(tmp_path):
    course_schedule.use_cache_folder(tmp_path)
    try:
        course_schedule.remember_title(URL, "Management Science")
        sessions = (course_schedule.CourseSession("12.10.2026", "09:00", "10:30", "HS 01", "Abhaltung", ""),)
        course_schedule.remember_schedule(URL, course_schedule.CourseSchedule((course_schedule.CourseGroup("G", sessions),)))
        lines = course_box.box_lines(URL, course_box.cached_entry(URL), TODAY)
        assert lines.title == "Management Science"
        assert lines.next_session == "Next session: Mon 12.10.2026, 09:00–10:30, HS 01"
    finally:
        course_schedule.use_cache_folder(None)


def labels(page):
    pytest.importorskip("PySide6")
    return [w.text() for w in page.findChildren(_qlabel())]


def test_built_box_shows_cached_data_and_its_buttons_work(tmp_path, qapp):
    from campusonline.ui import box

    host = FakeHost(tmp_path)
    course_schedule.use_cache_folder(tmp_path)
    (tmp_path / "course-schedules.json").write_text(json.dumps({"1002516": {"dates": ["31.12.2999"]}}))
    try:
        deck = host.make_deck("d", DECK, ("course",))
        page = box.build_box(host, deck)
        assert labels(page) == ["Course 1002516 at online.uni-graz.at", "Next session: Di 31.12.2999"]
        page.open_button.click()
        assert host.opened_urls == [URL]
        page.admin_button.click()
        assert host.opened_settings == [(deck, "Course")]
    finally:
        course_schedule.use_cache_folder(None)


def test_built_box_uses_english_weekdays_for_an_english_deck(tmp_path, qapp):
    from campusonline.ui import box

    host = FakeHost(tmp_path)
    course_schedule.use_cache_folder(tmp_path)
    (tmp_path / "course-schedules.json").write_text(json.dumps({"1002516": {"dates": ["31.12.2999"]}}))
    try:
        english = DECK.replace("\\begin{document}", "\\decklanguage{english}\n\\begin{document}")
        page = box.build_box(host, host.make_deck("e", english, ("course",)))
        assert "Next session: Tue 31.12.2999" in labels(page)
    finally:
        course_schedule.use_cache_folder(None)


def test_built_box_never_fetches(tmp_path, qapp, monkeypatch):
    from campusonline.ui import box

    def refuse(*args, **kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(course_schedule, "fetch_schedule", refuse)
    monkeypatch.setattr(course_schedule, "fetch_course_detail", refuse)
    host = FakeHost(tmp_path)
    page = box.build_box(host, host.make_deck("d", DECK, ("course",)))   # no cache folder: nothing cached
    assert course_box.NOTHING_CACHED in labels(page)


def test_box_rebuilt_after_midnight_uses_the_new_date(tmp_path, qapp, monkeypatch):
    from campusonline.ui import box

    class Clock:
        day = TODAY

        @classmethod
        def today(cls):
            return cls.day

    monkeypatch.setattr(box, "date", Clock)
    host = FakeHost(tmp_path)
    course_schedule.use_cache_folder(tmp_path)
    try:
        sessions = tuple(course_schedule.CourseSession(day, "09:00", "10:00", "SR 1", "", "")
                         for day in ("10.10.2026", "11.10.2026"))
        course_schedule.remember_schedule(URL, course_schedule.CourseSchedule((course_schedule.CourseGroup("G", sessions),)))
        deck = host.make_deck("d", DECK, ("course",))
        before = box.build_box(host, deck)
        assert "Next session: Sa 10.10.2026, 09:00–10:00, SR 1" in labels(before)
        Clock.day = date(2026, 10, 11)
        after = box.build_box(host, deck)
        assert "Next session: So 11.10.2026, 09:00–10:00, SR 1" in labels(after)
    finally:
        course_schedule.use_cache_folder(None)


def _qlabel():
    from PySide6.QtWidgets import QLabel

    return QLabel
