# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The compact Course box of the right column: the course, its next session, and two buttons.

It shows the cached schedule only and never fetches. The Course tab fills the cache and requests a rebuild;
SlideMage also rebuilds when the deck changes and at midnight. Each build uses the current date.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from .. import course_box, course_link
from slidemage.plugin_api import Deck, Host, Widget


def build_box(host: Host, deck: Deck) -> Widget:
    page = host.Page()
    url = course_link.parse_course_url(deck.text) or ""
    lines = course_box.box_lines(url, course_box.cached_entry(url), today=date.today(), language=host.deck_language(deck))
    page.body.addWidget(host.caption(lines.title))
    if lines.next_session:
        page.body.addWidget(host.caption(lines.next_session))
    if lines.note:
        page.body.addWidget(host.caption(lines.note))

    open_page = QPushButton("Open course page")
    open_page.clicked.connect(lambda: host.open_url(url))
    admin = QPushButton("Admin slides…")
    admin.clicked.connect(lambda: host.open_deck_settings(deck, "Course"))
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(open_page)
    layout.addWidget(admin)
    layout.addStretch(1)
    page.body.addWidget(row)
    page.open_button, page.admin_button = open_page, admin    # for the tests
    return page
