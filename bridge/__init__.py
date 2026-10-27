# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the plugin still needs SlideMage's internals for, until slidemage.plugin_api offers it.

Not part of the plugin: build.py ships only campusonline/. Each piece here becomes a host call (step 2 of
the plan), and then this folder goes:

    insert.insert_admin_slides   making slide files of planned frames and adding them to the deck
    insert.set_course_url        writing a deck's course link (the deck text edit is course_link's)

Its tests (tests/bridge/) run only where SlideMage can be imported.
"""
