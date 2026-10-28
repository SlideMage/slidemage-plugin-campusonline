# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""activate() against the FakeHost: what it registers, the enabled checks, the render priority."""
from __future__ import annotations

import urllib.request
from unittest import mock

import pytest

pytest.importorskip("slidemage.plugin_api", reason="SlideMage's plugin API is not installed")

import campusonline
from campusonline import course_schedule
from slidemage.plugin_api import Host, StaleFileError
from fake_host import FakeHost

URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"
LINKED = f"\\documentclass{{beamer}}\n%% SlideMage course URL: {URL}\n\\begin{{document}}\n\\slide{{a-DE-x}}\n\\end{{document}}\n"
PLAIN = "\\documentclass{beamer}\n\\begin{document}\n\\slide{a-DE-x}\n\\end{document}\n"


@pytest.fixture
def host(tmp_path):
    fake = FakeHost(tmp_path)
    campusonline.activate(fake)
    fake.finish_activation()
    yield fake
    course_schedule.use_cache_folder(None)


def test_fake_host_is_a_host(tmp_path):
    host: Host = FakeHost(tmp_path)   # a type check target; also that the calls exist
    for name in Host.__dict__:
        if not name.startswith("_"):
            assert hasattr(host, name), name


def test_registers_commands_and_menu(host):
    assert {c.id: c.title for c in host.commands.values()} == {
        "campusonline.admin_slides": "Admin slides…",
        "campusonline.open_course_page": "Open course page",
    }
    assert host.menus == {"deck": ["campusonline.admin_slides", "campusonline.open_course_page"]}


def test_registers_tab_box_and_priority(host):
    (tab,) = host.tabs
    assert tab.title == "Course"
    assert tab.footer_action.label == "Insert slides"
    (box,) = host.boxes
    assert (box.key, box.size) == ("course", "compact")
    assert len(host.render_priorities) == 1


@pytest.mark.parametrize("text, groups, enabled", [
    (LINKED, ("course",), True),
    (LINKED, ("work",), False),
    (PLAIN, ("course",), False),
    (PLAIN, ("work",), False),
    (LINKED, ("work", "course"), True),
])
def test_commands_enabled_for_course_deck_with_link(host, text, groups, enabled):
    deck = host.make_deck("d", text, groups)
    for command in host.commands.values():
        assert command.enabled(deck) is enabled
    assert not any(c.enabled(None) for c in host.commands.values())


def test_box_shown_only_with_link(host):
    (box,) = host.boxes
    assert box.when(host.make_deck("a", LINKED, ("work",)))
    assert not box.when(host.make_deck("b", PLAIN, ("course",)))


def test_commands_run(host):
    deck = host.make_deck("d", LINKED, ("course",))
    host.run_command("campusonline.open_course_page", deck)
    assert host.opened_urls == [URL]
    host.run_command("campusonline.admin_slides", deck)
    assert host.opened_settings == [(deck, "Course")]
    with pytest.raises(RuntimeError):
        host.run_command("campusonline.open_course_page", host.make_deck("e", PLAIN, ("course",)))


def test_render_priority_asks_session_soon_with_the_parsed_link(host):
    with mock.patch.object(course_schedule, "session_soon", return_value=True) as soon:
        assert host.render_soon(host.make_deck("a", LINKED))
        soon.assert_called_once_with(URL)
    with mock.patch.object(course_schedule, "session_soon", return_value=False) as soon:
        assert not host.render_soon(host.make_deck("b", PLAIN))
        soon.assert_called_once_with(None)


def test_sets_the_cache_folder(tmp_path):
    fake = FakeHost(tmp_path)
    with mock.patch.object(course_schedule, "use_cache_folder") as use:
        campusonline.activate(fake)
    use.assert_called_once_with(tmp_path / "cache")


def test_activate_does_no_network(tmp_path):
    fake = FakeHost(tmp_path)
    with mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("network")):
        campusonline.activate(fake)
        fake.finish_activation()
    course_schedule.use_cache_folder(None)


def test_fake_host_edits_refuse_stale_files(tmp_path):
    fake = FakeHost(tmp_path)
    deck = fake.make_deck("d", PLAIN)
    fake.edit_deck_text(deck, lambda text: text + "% x\n")
    with pytest.raises(StaleFileError):
        fake.edit_deck_text(deck, lambda text: text)
    deck = fake.reread(deck)
    (first, *_) = fake.insert_positions(deck)
    paths = fake.insert_slides(deck, first, [("title", "frame")], "de")
    assert paths[0].read_text() == "frame"
    assert "\\slide{T01-DE-title}\n\\slide{a-DE-x}" in deck.path.read_text()
    with pytest.raises(StaleFileError):
        fake.insert_slides(deck, first, [("more", "f")], "de")
    assert not (tmp_path / "slides" / "T02-DE-more.tex").exists()


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_course_link_edit_through_the_host_keeps_line_endings(host, newline):
    from campusonline.course_link import course_url_text, parse_course_url

    initial = newline.join((r"\documentclass{beamer}", r"\begin{document}", r"\end{document}", ""))
    deck = host.make_deck("course", initial)
    linked = host.edit_deck_text(deck, lambda text: course_url_text(text, URL, deck.name))
    assert deck.path.read_bytes().decode() == linked
    assert parse_course_url(linked) == URL
    assert host.edit_deck_text(host.reread(deck), lambda text: course_url_text(text, "  ", deck.name)) == initial
