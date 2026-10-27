# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writing a deck's course link: the file gets exactly the edited text, and only when nothing changed it meanwhile."""
from __future__ import annotations

import pytest

from bridge.insert import set_course_url
from campusonline.course_link import parse_course_url
from slidemage import deck_editor
from test_course_link import BAD_URLS, COURSE_URL


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_the_link_is_written_and_removed(tmp_path, newline):
    path = tmp_path / "course.tex"
    initial = newline.join((r"\documentclass{beamer}", r"\begin{document}", r"\end{document}", ""))
    path.write_text(initial, encoding="utf-8", newline="")

    linked = set_course_url(path, initial, COURSE_URL)
    assert path.read_bytes().decode() == linked
    assert parse_course_url(linked) == COURSE_URL

    assert set_course_url(path, linked, "  ") == initial
    assert path.read_bytes().decode() == initial


@pytest.mark.parametrize("bad_url", BAD_URLS)
def test_invalid_course_url_does_not_modify_deck(tmp_path, bad_url):
    path = tmp_path / "course.tex"
    original = "\\documentclass{beamer}\n\\begin{document}\n"
    path.write_text(original, encoding="utf-8", newline="")
    with pytest.raises(ValueError):
        set_course_url(path, original, bad_url)
    assert path.read_text() == original


def test_stale_deck_is_not_overwritten(tmp_path):
    path = tmp_path / "course.tex"
    original = "\\documentclass{beamer}\n\\begin{document}\n"
    path.write_text(original + "% external change\n", encoding="utf-8", newline="")
    with pytest.raises(deck_editor.StaleFileError):
        set_course_url(path, original, COURSE_URL)
    assert path.read_text().endswith("% external change\n")
