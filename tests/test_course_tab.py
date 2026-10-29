# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Course tab of the Deck settings sheet, against the FakeHost: the course link, the fetch, which slides
are planned and where they go. (The slides themselves are tested in test_admin_slides.py.)"""
from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("slidemage.plugin_api", reason="SlideMage's plugin API is not installed")

import campusonline
from campusonline import admin_slides, course_schedule
from campusonline.course_schedule import CourseGroup, CourseSchedule, CourseSession
from fake_host import FakeHost
from test_admin_slides import DETAIL, GROUP

pytest.importorskip("PySide6")

URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"
PREAMBLE = "\\documentclass{beamer}\n"
BODY = "\\begin{document}\n\\slide{a-DE-x}\n\\slide{b-DE-y}\n\\end{document}\n"
LINKED = f"{PREAMBLE}%% SlideMage course URL: {URL}\n{BODY}"
PLAIN = PREAMBLE + BODY


@pytest.fixture
def host(tmp_path):
    fake = FakeHost(tmp_path)
    campusonline.activate(fake)
    fake.finish_activation()
    yield fake
    course_schedule.use_cache_folder(None)


@pytest.fixture
def fetched(monkeypatch):
    """Patch the fetch; the list records (url, language) of each call."""
    class Calls(list):
        result: list

    calls = Calls()
    result = [(CourseSchedule((GROUP,)), DETAIL)]
    monkeypatch.setattr(admin_slides, "fetch", lambda url, lang: calls.append((url, lang)) or result[0])
    calls.result = result
    return calls


def make_tab(host, text=LINKED, groups=("course",)):
    deck = host.make_deck("d", text, groups)
    page = host.tabs[0].build(deck)
    return deck, page, page.controller


def two_groups():
    return CourseSchedule((
        CourseGroup("Standardgruppe", (CourseSession("05.10.2026", "09:00", "10:00", "SR 1", "Abhaltung", ""),)),
        CourseGroup("Gruppe Wirtschaftsinformatik",
                    (CourseSession("06.10.2026", "08:30", "10:00", "HS 1", "Abhaltung", ""),)),
    ))


def enabled(host, page):
    return host.tabs[0].footer_action.enabled(page)


# -- the course link -----------------------------------------------------------------------------------------------

def test_link_field_shows_the_link_and_open_uses_the_host(host, qapp, fetched):
    _, page, tab = make_tab(host)
    assert tab.url_edit.text() == URL and tab.open_button.isEnabled() and not tab.save_button.isEnabled()
    tab.open_button.click()
    assert host.opened_urls == [URL]


def test_save_link_goes_through_edit_deck_text(host, qapp, fetched):
    deck, page, tab = make_tab(host, PLAIN)
    assert not tab.open_button.isEnabled()
    tab.url_edit.setText("  " + URL + " ")
    assert tab.save_button.isEnabled()
    tab.save_button.click()
    assert f"%% SlideMage course URL: {URL}\n\\begin{{document}}" in deck.path.read_text()
    assert tab.link_status.text() == "Link saved. Reopen Deck settings to load the course."
    assert not tab.save_button.isEnabled() and tab.open_button.isEnabled()
    assert fetched == []     # the snapshot is stale; the tab doesn't fetch for it


def test_clearing_the_link_removes_it(host, qapp, fetched):
    deck, _, tab = make_tab(host)
    tab.url_edit.setText("")
    tab.save_button.click()
    assert "SlideMage course URL" not in deck.path.read_text()


def test_a_bad_link_is_an_error_and_writes_nothing(host, qapp, fetched):
    deck, _, tab = make_tab(host, PLAIN)
    tab.url_edit.setText("ftp://nope")
    tab.save_button.click()
    assert not tab.link_error.isHidden() and "http" in tab.link_error.text()
    assert deck.path.read_text() == PLAIN
    tab.url_edit.setText("https://x.example/y")
    assert tab.link_error.isHidden()      # editing clears the error


def test_a_stale_deck_says_to_reopen(host, qapp, fetched):
    deck, _, tab = make_tab(host, PLAIN)
    deck.path.write_text(PLAIN + "% changed\n")
    tab.url_edit.setText(URL)
    tab.save_button.click()
    assert tab.link_error.text() == "The deck changed on disk; reopen Deck settings."
    assert not tab.link_error.isHidden()


def test_return_in_the_field_saves(host, qapp, fetched):
    deck, _, tab = make_tab(host, PLAIN)
    tab.url_edit.setText(URL)
    tab.url_edit.returnPressed.emit()
    assert URL in deck.path.read_text()


# -- the fetch -----------------------------------------------------------------------------------------------------

def test_a_deck_without_a_course_page_says_so_and_fetches_nothing(host, qapp, fetched):
    _, page, tab = make_tab(host, PLAIN)
    page.show()
    assert tab.title_section.isHidden() and tab.preview.isHidden()
    assert "links no course page" in tab.status.text()
    assert fetched == [] and tab.slide_specs == [] and not enabled(host, page)


@pytest.mark.parametrize("language", ["de", "en"])
def test_the_course_is_fetched_once_when_first_shown(host, qapp, fetched, language):
    text = LINKED.replace("beamer}", "beamer}\n\\decklanguage[english]") if language == "en" else LINKED
    _, page, tab = make_tab(host, text)
    assert fetched == []                # building does not fetch
    fetched.result[0] = (CourseSchedule((GROUP,)), "not needed")
    page.show()
    page.hide()
    page.show()
    assert fetched == [(URL, language)]
    assert host.refreshed_sidebar_boxes == [campusonline.SIDEBAR_BOX_COURSE]
    headings = r"\textbf{Date} & \textbf{Time}" if language == "en" else r"\textbf{Datum} & \textbf{Zeit}"
    assert headings in tab.slide_specs[0][1]


def test_a_result_after_the_widget_is_gone_is_ignored(host, qapp, fetched):
    deck = host.make_deck("d", LINKED, ("course",))
    done = []
    host.run_in_background = lambda work, callback: done.append((work, callback))
    page = host.tabs[0].build(deck)
    tab = page.controller
    page.show()
    (work, callback), = done
    tab._on_gone()
    callback(work(), None)
    assert tab.slide_specs == [] and tab.schedule is None
    assert host.refreshed_sidebar_boxes == [campusonline.SIDEBAR_BOX_COURSE]


def test_a_failing_worker_is_shown_as_not_available(host, qapp, fetched):
    fetched.result[0] = None
    _, page, tab = make_tab(host)
    host.run_in_background = lambda work, callback: callback(None, RuntimeError("boom"))
    tab.start()
    assert "boom" in tab.sessions_status.text() and "boom" in tab.title_status.text()
    assert tab.slide_specs == []
    assert host.refreshed_sidebar_boxes == []


@pytest.mark.parametrize("result", [
    (CourseSchedule(()), "detail unavailable"),
    ("schedule unavailable", DETAIL),
    (CourseSchedule(()), DETAIL),
])
def test_a_successful_fetch_requests_box_refresh_after_the_cache_is_updated(host, qapp, monkeypatch, result):
    _, page, tab = make_tab(host)
    # Exercise the real fetch wrapper, with only the network calls replaced.
    def schedule(url):
        if isinstance(result[0], str):
            raise RuntimeError(result[0])
        course_schedule.remember_schedule(url, result[0])
        return result[0]

    def detail(url, language):
        if isinstance(result[1], str):
            raise RuntimeError(result[1])
        return result[1]

    monkeypatch.setattr(course_schedule, "fetch_schedule", schedule)
    monkeypatch.setattr(course_schedule, "fetch_course_detail", detail)
    refreshed_entries = []
    record_refresh = host.refresh_sidebar_box

    def refresh(key):
        refreshed_entries.append(course_schedule.cached_entry(URL))
        record_refresh(key)

    monkeypatch.setattr(host, "refresh_sidebar_box", refresh)
    tab.start()
    assert host.refreshed_sidebar_boxes == [campusonline.SIDEBAR_BOX_COURSE]
    assert len(refreshed_entries) == 1
    if not isinstance(result[0], str):
        assert refreshed_entries[0]["dates"] == []
    if not isinstance(result[1], str):
        assert refreshed_entries[0]["title"] == DETAIL.title


def test_fetch_works_with_an_older_host_without_sidebar_refresh(host, qapp, fetched):
    # Hide the new API while retaining the rest of the fake host contract.
    class OlderHost:
        def __getattr__(self, name):
            if name == "refresh_sidebar_box":
                raise AttributeError(name)
            return getattr(host, name)

    from campusonline.ui.deck_tab import build_tab

    page = build_tab(OlderHost(), host.make_deck("old", LINKED, ("course",)))
    page.controller.start()
    assert page.controller.schedule == fetched.result[0][0]
    assert host.refreshed_sidebar_boxes == []


def test_a_fetch_with_no_new_data_does_not_request_box_refresh(host, qapp, fetched):
    fetched.result[0] = ("schedule unavailable", "detail unavailable")
    _, page, tab = make_tab(host)
    tab.start()
    assert host.refreshed_sidebar_boxes == []


def test_multiple_groups_and_lecturers_build_combined_preview(host, qapp, fetched):
    _, page, tab = make_tab(host)
    changes = []
    page.changed.connect(lambda: changes.append(1))
    groups = two_groups()
    tab._on_loaded(groups, DETAIL)

    assert tab.position.insert_at == tab.deck.text.index(r"\end{document}") or tab.position.label.startswith("After")
    assert not tab.group_combo.isHidden()
    assert [tab.group_combo.itemText(i) for i in range(tab.group_combo.count())] == [g.name for g in groups.groups]
    assert "05.10.2026" in tab.preview.toPlainText()
    assert "Bachelorkurs (Management Science)" in tab.preview.toPlainText()
    assert "Erika Musterfrau, Jürgen Fleiß" in tab.preview.toPlainText()
    assert [suffix for suffix, _ in tab.slide_specs] == ["Title-Slide", "Course-Sessions"]
    assert changes

    tab.group_combo.setCurrentIndex(1)
    assert "06.10.2026" in tab.preview.toPlainText()
    assert "05.10.2026" not in tab.preview.toPlainText()

    checkbox, _ = tab._lecturer_checks[0]
    checkbox.setChecked(False)
    assert "Erika Musterfrau" not in tab.preview.toPlainText()
    assert "Jürgen Fleiß" in tab.preview.toPlainText()

    tab.sessions_check.setChecked(False)
    assert [suffix for suffix, _ in tab.slide_specs] == ["Title-Slide"]
    tab.title_check.setChecked(False)
    assert tab.slide_specs == []


def test_empty_groups_are_labelled_in_the_picker_only(host, qapp, fetched):
    _, _, tab = make_tab(host)
    groups = (CourseGroup("Standardgruppe", GROUP.sessions[:1]), CourseGroup("Gruppe Operations Management", ()))
    tab._on_loaded(CourseSchedule(groups), DETAIL)
    assert [tab.group_combo.itemText(i) for i in range(tab.group_combo.count())] == [
        "Standardgruppe", "Gruppe Operations Management (empty)"]
    tab.group_combo.setCurrentIndex(1)
    assert r"\textbf{Gruppe Operations Management}\par Keine Termine" in tab.preview.toPlainText()


def test_failed_fetch_disables_its_own_section_only(host, qapp, fetched):
    _, _, tab = make_tab(host)
    tab._on_loaded("network unreachable", DETAIL)
    assert not tab.sessions_check.isChecked() and not tab.sessions_section.isEnabled()
    assert "network unreachable" in tab.sessions_status.text()
    assert tab.title_section.isEnabled()
    assert [suffix for suffix, _ in tab.slide_specs] == ["Title-Slide"]


@pytest.mark.parametrize(("taught", "warned"), [(("de",), True), (("en",), False)])
def test_language_mismatch_warns_without_blocking(host, qapp, fetched, taught, warned):
    _, _, tab = make_tab(host, LINKED.replace("beamer}", "beamer}\n\\decklanguage[english]"))
    tab._on_loaded("no sessions", replace(DETAIL, languages=taught))
    assert tab.language_warning.isHidden() is not warned
    assert tab.slide_specs


# -- Insert slides -------------------------------------------------------------------------------------------------

def test_footer_is_enabled_once_something_is_chosen_and_fetched(host, qapp, fetched):
    _, page, tab = make_tab(host)
    assert not enabled(host, page)
    tab._on_loaded(CourseSchedule((GROUP,)), DETAIL)
    assert enabled(host, page)
    tab.title_check.setChecked(False)
    tab.sessions_check.setChecked(False)
    assert not enabled(host, page)


def test_insert_slides_inserts_through_the_host_at_the_chosen_place(host, qapp, fetched):
    deck, page, tab = make_tab(host)
    tab._on_loaded(CourseSchedule((GROUP,)), DETAIL)
    tab.position_combo.setCurrentIndex(1)       # after the first slide
    host.tabs[0].footer_action.run(page)
    text = deck.path.read_text()
    assert "\\slide{a-DE-x}\n\\slide{T01-DE-Title-Slide}\n\\slide{T02-DE-Course-Sessions}\n\\slide{b-DE-y}" in text
    assert (host.root / "slides" / "T02-DE-Course-Sessions.tex").read_text("utf-8") == tab.slide_specs[1][1]
    assert "Inserted 2" in tab.status.text() and not enabled(host, page)     # the snapshot is stale now


def test_insert_slides_in_an_english_deck_uses_EN_suffixes(host, qapp, fetched):
    deck, page, tab = make_tab(host, LINKED.replace("beamer}", "beamer}\n\\decklanguage[english]"))
    tab._on_loaded(CourseSchedule((GROUP,)), DETAIL)
    host.tabs[0].footer_action.run(page)
    assert (host.root / "slides" / "T01-EN-Title-Slide.tex").exists()


def test_insert_into_a_changed_deck_says_to_reopen(host, qapp, fetched):
    deck, page, tab = make_tab(host)
    tab._on_loaded(CourseSchedule((GROUP,)), DETAIL)
    deck.path.write_text(deck.text + "% changed\n")
    host.tabs[0].footer_action.run(page)
    assert tab.status.text() == "The deck changed on disk; reopen Deck settings."
    assert not (host.root / "slides").exists() or not list((host.root / "slides").iterdir())
