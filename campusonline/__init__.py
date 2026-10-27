# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""CampusOnline: a deck's link to its CAMPUSonline course page, admin slides generated from the course's public
data, and earlier background renders for a deck whose course has a session soon.

SlideMage imports this package and calls activate() once at start."""
from __future__ import annotations

from . import course_link, course_schedule
from .host import COURSE_GROUP, Deck, FooterAction, Host, Widget

COMMAND_ADMIN_SLIDES = "campusonline.admin_slides"
COMMAND_OPEN_COURSE_PAGE = "campusonline.open_course_page"
TAB_TITLE = "Course"


def deck_course_url(deck: Deck | None) -> str | None:
    """The deck's course link, or None (also for no deck)."""
    return course_link.parse_course_url(deck.text) if deck is not None else None


def has_course_link(deck: Deck | None) -> bool:
    return deck_course_url(deck) is not None


def in_course_group(deck: Deck | None) -> bool:
    return deck is not None and COURSE_GROUP in deck.groups


def course_commands_possible(deck: Deck | None) -> bool:
    """Admin slides and Open course page: a Course deck that links its course."""
    return in_course_group(deck) and has_course_link(deck)


def activate(host: Host) -> None:
    """Register the plugin's contributions with SlideMage through host (see campusonline.host).

    Runs at start: it registers and sets a folder, and does no network or slow work."""
    course_schedule.use_cache_folder(host.cache_dir())
    course_schedule.adopt_legacy_cache(host.legacy_cache_dir())     # once: SlideMage kept the dates before the plugin

    def admin_slides(deck: Deck) -> None:
        host.open_deck_settings(deck, TAB_TITLE)

    def open_course_page(deck: Deck) -> None:
        url = deck_course_url(deck)
        if url:
            host.open_url(url)

    host.add_command(COMMAND_ADMIN_SLIDES, "Admin slides…", admin_slides, enabled=course_commands_possible)
    host.add_command(COMMAND_OPEN_COURSE_PAGE, "Open course page", open_course_page, enabled=course_commands_possible)
    host.add_menu_entry("deck", COMMAND_ADMIN_SLIDES)
    host.add_menu_entry("deck", COMMAND_OPEN_COURSE_PAGE)

    # The widgets import PySide6, so they are imported when SlideMage builds one, not at start.
    def build_tab(deck: Deck) -> Widget:
        from .ui import deck_tab
        return deck_tab.build_tab(host, deck)

    def build_box(deck: Deck) -> Widget:
        from .ui import box
        return box.build_box(host, deck)

    host.add_deck_settings_tab(
        TAB_TITLE, build_tab,
        footer_action=FooterAction(
            "Insert slides", run=lambda page: page.controller.insert(),
            enabled=lambda page: page.controller.can_insert()))
    host.add_sidebar_box("course", "Course", build_box, size="compact", when=has_course_link)

    # Called on a worker thread: reads the cache, never fetches.
    host.add_render_priority(lambda deck: course_schedule.session_soon(deck_course_url(deck)))

