# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""CampusOnline: a deck's link to its CAMPUSonline course page, admin slides generated from the course's public
data, and earlier background renders for a deck whose course has a session soon.

SlideMage imports this package and calls activate() once at start."""


def activate(host) -> None:
    """Register the plugin's contributions with SlideMage through host (see slidemage.plugin_api)."""
