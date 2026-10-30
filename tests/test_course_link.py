# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Course URLs persist in deck source without affecting LaTeX."""
from __future__ import annotations

import pytest

from campusonline.course_link import course_url_text, normalize_course_url, parse_course_url


COURSE_URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"
OTHER_URL = "https://online.uni-graz.at/course?q=one%20two&lang=de"
BAD_URLS = [
    "javascript:alert(1)", "file:///tmp/page", "online.uni-graz.at/course",
    "https://", "https://example.org/has space", "https://example.org:bad/path",
]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_course_url_round_trip(newline):
    initial = newline.join((
        r"\documentclass{beamer}",
        r"\input{SlideMage_template_uni-graz}",
        r"% This note mentions \begin{document} before the actual command.",
        r"\begin{document}",
        r"\end{document}",
        "",
    ))

    linked = course_url_text(initial, COURSE_URL, "course.tex")
    assert f"%% SlideMage course URL: {COURSE_URL}{newline}" in linked
    assert linked.index("%% SlideMage course URL:") < linked.index(newline + r"\begin{document}")
    assert parse_course_url(linked) == COURSE_URL

    changed = course_url_text(linked, OTHER_URL, "course.tex")
    assert changed.count("%% SlideMage course URL:") == 1
    assert parse_course_url(changed) == OTHER_URL

    removed = course_url_text(changed, "  ", "course.tex")
    assert "%% SlideMage course URL:" not in removed
    assert parse_course_url(removed) is None
    assert removed == initial


@pytest.mark.parametrize("bad_url", BAD_URLS)
def test_invalid_course_url_is_refused(bad_url):
    with pytest.raises(ValueError):
        normalize_course_url(bad_url)
    with pytest.raises(ValueError):
        course_url_text("\\documentclass{beamer}\n\\begin{document}\n", bad_url, "course.tex")


def test_a_deck_without_begin_document_gets_no_link_but_can_lose_one():
    with pytest.raises(ValueError, match="course.tex has no"):
        course_url_text("\\documentclass{beamer}\n", COURSE_URL, "course.tex")
    assert course_url_text(f"%% SlideMage course URL: {COURSE_URL}\n", "", "course.tex") == ""


def test_marker_in_body_is_ignored():
    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        f"%% SlideMage course URL: {COURSE_URL}\n"
    )
    assert parse_course_url(text) is None
    assert course_url_text(text, "", "course.tex") == text
