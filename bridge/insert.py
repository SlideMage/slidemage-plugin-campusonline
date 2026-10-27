# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The deck edits of the plugin, through SlideMage's internals: new slide files from planned frames, and
the course link."""
from __future__ import annotations

from pathlib import Path

from slidemage import deck_editor, slide_ids, slide_language
from slidemage.deck_scan import Deck
from slidemage.project import ProjectContext

from campusonline import course_link


def build_slide_source(frame: str) -> str:
    """Wrap a generated LaTeX frame in the normal editable slide format."""
    frame = frame.strip().replace("\r\n", "\n").replace("\r", "\n")
    lines = [r"\setSlideVersion{1-0-0}", frame, ""]
    return slide_ids.build_new_slide_header() + "\r\n".join(lines)


def insert_admin_slides(
    ctx: ProjectContext, deck: Deck, position: deck_editor.InsertPosition, slide_specs: list[tuple[str, str]],
    language: str = "de",
) -> list[Path]:
    """Create one new slide per ``(id_suffix, frame)`` spec, then add
    all their calls to the deck in one edit, in order, at the insert
    position. If anything fails, the new slide files are removed and the
    deck is left untouched."""
    slide_paths: list[Path] = []
    id_slugs: list[str] = []
    try:
        for id_suffix, frame in slide_specs:
            slide_id = slide_ids.mint_slide_id(ctx)
            id_slug = f"{slide_id}-{'EN' if language == 'en' else 'DE'}-{id_suffix}"
            slide_path = ctx.slides_dir / slide_language.current_name(id_slug)
            slide_path.parent.mkdir(parents=True, exist_ok=True)
            # Reserve the ID before editing the deck, like the ordinary Add slide path.
            slide_ids.append_slide_id(ctx, slide_id)
            with slide_path.open("x", encoding="utf-8", newline="") as destination:
                destination.write(build_slide_source(frame))
            slide_paths.append(slide_path)
            id_slugs.append(id_slug)
        deck_editor.insert_slide_calls(
            deck.path, deck.text, position.insert_at, position.indent, id_slugs,
        )
    except Exception:
        for slide_path in slide_paths:
            slide_path.unlink(missing_ok=True)
        raise
    return slide_paths


def set_course_url(deck_path: Path, expected_text: str, url: str) -> str:
    """Store or remove a course URL as a comment in the deck preamble."""
    if url.strip():
        course_link.normalize_course_url(url)  # a bad URL is refused before anything is read

    return deck_editor.apply(deck_path, expected_text,
                             lambda text: course_link.course_url_text(text, url, deck_path.name))
