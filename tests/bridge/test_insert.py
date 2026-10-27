# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The admin slides' insertion: new slide files from the planned frames, and their calls in the deck."""
from __future__ import annotations

from dataclasses import replace

import pytest

from bridge import insert
from campusonline import admin_slides
from slidemage import deck_editor, slide_ids
from slidemage.deck_scan import Deck


def make_deck(tmp_path, language="de"):
    path = tmp_path / "course.tex"
    text = (
        "\\documentclass{beamer}\n\\decklanguage[" + language + "]\n"
        "\\begin{document}\n\\end{document}\n"
    )
    path.write_text(text, encoding="utf-8", newline="")
    return Deck(
        name="course", path=path, archived=False, text=text,
        supports_version=False, uses_biblatex=False, preamble_end=0,
        chapters=[], output_folders={}, tags=[], course_url="https://example.invalid/course",
    )


@pytest.fixture
def new_slides(tmp_path, monkeypatch):
    ids = iter(["abc", "def"])
    monkeypatch.setattr(slide_ids, "mint_slide_id", lambda _ctx: next(ids))


def test_schedule_positions_follow_regular_slide_calls(tmp_path):
    deck = make_deck(tmp_path)
    text = (
        "\\begin{document}\n\\section{Intro}\n"
        "\\slide{aaa-EN-First}\n\\slide{bbb-EN-Second}\n"
        "\\end{document}\n"
    )
    deck.path.write_text(text, encoding="utf-8", newline="")
    deck = replace(deck, text=text)
    positions = deck_editor.slide_insert_positions(deck)
    assert [position.label for position in positions] == [
        "At the beginning", "After 1. aaa-EN-First", "After 2. bbb-EN-Second",
    ]
    assert positions[-1].insert_at == text.index("\\end{document}")


@pytest.mark.parametrize("language", ["de", "en"])
def test_insertion_creates_editable_slides_and_deck_calls_in_order(ctx, tmp_path, new_slides, language):
    deck = make_deck(tmp_path, language=language)
    position = deck_editor.slide_insert_positions(deck)[0]
    specs = [
        ("Title-Slide", r"\titleframe{Financial Markets}{Stefan Palan\\Summer term 2026}"),
        ("Course-Sessions", admin_slides.sessions_frame(r"\begin{tabular}{ll}Datum & Zeit \\ \end{tabular}", language)),
    ]

    slide_paths = insert.insert_admin_slides(ctx, deck, position, specs, language)

    tag = language.upper()
    assert [path.name for path in slide_paths] == [
        f"abc-{tag}-Title-Slide-current.tex", f"def-{tag}-Course-Sessions-current.tex",
    ]
    deck_text = deck.path.read_text(encoding="utf-8")
    assert deck_text.index(r"\slide{abc-" + tag + "-Title-Slide}") < deck_text.index(r"\slide{def-" + tag + "-Course-Sessions}")
    assert '"abc"' in (tmp_path / "slide_ids.csv").read_text(encoding="utf-8")
    assert '"def"' in (tmp_path / "slide_ids.csv").read_text(encoding="utf-8")
    title = slide_paths[0].read_bytes().decode("utf-8")
    assert title.startswith(slide_ids.build_new_slide_header())
    assert title.endswith("\\setSlideVersion{1-0-0}\r\n\\titleframe{Financial Markets}{Stefan Palan\\\\Summer term 2026}\r\n")


def test_failure_on_a_later_slide_leaves_deck_untouched(ctx, tmp_path, monkeypatch, new_slides):
    deck = make_deck(tmp_path)
    # Same ID twice: the second slide file already exists, so its open("x") fails.
    monkeypatch.setattr(slide_ids, "mint_slide_id", lambda _ctx: "abc")
    position = deck_editor.slide_insert_positions(deck)[0]
    specs = [("Title-Slide", "A"),
             ("Title-Slide", "B")]

    with pytest.raises(FileExistsError):
        insert.insert_admin_slides(ctx, deck, position, specs)

    assert deck.path.read_text(encoding="utf-8") == deck.text
    assert not list((tmp_path / "slides").glob("*.tex"))


def test_insert_slide_calls_at_end_of_file_without_newline(tmp_path):
    path = tmp_path / "deck.tex"
    text = "\\begin{document}\n\\slide{aaa-EN-First}"
    path.write_text(text, encoding="utf-8", newline="")

    deck_editor.insert_slide_calls(path, text, len(text), "", ["bbb-DE-A", "ccc-DE-B"])

    assert path.read_text(encoding="utf-8") == (
        "\\begin{document}\n\\slide{aaa-EN-First}\n\\slide{bbb-DE-A}\n\\slide{ccc-DE-B}\n"
    )


def test_stale_deck_keeps_external_change_and_removes_new_slide(ctx, tmp_path, new_slides):
    deck = make_deck(tmp_path)
    position = deck_editor.slide_insert_positions(deck)[0]
    deck.path.write_text(deck.text + "% external edit\n", encoding="utf-8", newline="")

    with pytest.raises(deck_editor.StaleFileError):
        insert.insert_admin_slides(
            ctx, deck, position, [("Course-Sessions", admin_slides.sessions_frame("Table"))])

    assert "% external edit" in deck.path.read_text(encoding="utf-8")
    assert not list((tmp_path / "slides").glob("*.tex"))
