# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A FakeHost for the plugin's tests: implements campusonline.host.Host without SlideMage or Qt.

- Registrations are recorded (commands, menu entries, deck settings tabs, sidebar boxes, render priorities).
- run_in_background runs the work at once, on the calling thread, and then calls done.
- Decks are real files in a folder (``root``, normally pytest's tmp_path); edit_deck_text and insert_slides
  refuse with StaleFileError when the file differs from ``deck.text``, like SlideMage's deck_editor.apply.
  The Deck object stays a snapshot: after an edit, make a new one with ``reread(deck)``.
- insert_slides writes ``<root>/slides/<id>-<DE|EN>-<id_suffix>.tex`` (ids T01, T02, … ; the file holds the
  frame as given, without SlideMage's header) and inserts one ``\\slide{<id>-<DE|EN>-<id_suffix>}`` line per
  slide at the position, with its indent and the deck's line ending.
- Widgets are tiny stand-ins: a Page has a ``body`` with ``addWidget``, a caption keeps its text.
- Nothing is opened: open_url and open_deck_settings record their arguments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from campusonline.host import FooterAction, InsertPosition, StaleFileError

SLIDE_CALL_RE = re.compile(r"^([ \t]*)\\slide\{([^}]*)\}[ \t]*\r?\n?", re.MULTILINE)


@dataclass
class FakeDeck:
    name: str
    path: Path
    text: str
    groups: tuple[str, ...] = ("work",)


@dataclass
class Command:
    id: str
    title: str
    run: Callable[[Any], None]
    enabled: Callable[[Any], bool]


@dataclass
class Tab:
    title: str
    build: Callable[[Any], Any]
    footer_action: FooterAction | None


@dataclass
class Box:
    key: str
    title: str
    build: Callable[[Any], Any]
    size: str
    when: Callable[[Any], bool]


class FakeWidget:
    def __init__(self, text: str = "", tone: str = "") -> None:
        self.text, self.tone, self.children = text, tone, []
        self.body = self

    def addWidget(self, widget: Any) -> None:
        self.children.append(widget)

    def setText(self, text: str) -> None:
        self.text = text


class FakeHost:
    def __init__(self, root: Path, legacy_cache: Path | None = None) -> None:
        self.root = root
        self._legacy_cache = legacy_cache
        self.commands: dict[str, Command] = {}
        self.menus: dict[str, list[str]] = {}
        self.tabs: list[Tab] = []
        self.boxes: list[Box] = []
        self.render_priorities: list[Callable[[Any], bool]] = []
        self.opened_urls: list[str] = []
        self.opened_settings: list[tuple[Any, str | None]] = []
        self._ids = 0
        self._active = True

    # -- the test's side ----------------------------------------------------------------------------------------

    def finish_activation(self) -> None:
        """After activate(): the add_* calls refuse from now on, like the real host."""
        self._active = False

    def make_deck(self, name: str, text: str, groups: tuple[str, ...] = ("work",)) -> FakeDeck:
        path = self.root / f"{name}.tex"
        path.write_bytes(text.encode("utf-8"))
        return FakeDeck(name, path, text, groups)

    def reread(self, deck: FakeDeck) -> FakeDeck:
        return FakeDeck(deck.name, deck.path, deck.path.read_bytes().decode("utf-8"), deck.groups)

    def run_command(self, command_id: str, deck: FakeDeck | None) -> None:
        command = self.commands[command_id]
        if not command.enabled(deck):
            raise RuntimeError(f"{command_id} is not enabled")
        command.run(deck)

    def render_soon(self, deck: FakeDeck) -> bool:
        """True if any registered render priority says so."""
        return any(soon(deck) for soon in self.render_priorities)

    # -- Host: what it is given -----------------------------------------------------------------------------------

    def cache_dir(self) -> Path:
        folder = self.root / "cache"
        folder.mkdir(exist_ok=True)
        return folder

    def legacy_cache_dir(self) -> Path | None:
        return self._legacy_cache

    # -- Host: what it registers ---------------------------------------------------------------------------------

    def _check_active(self) -> None:
        if not self._active:
            raise RuntimeError("registrations are only allowed in activate()")

    def add_command(self, id, title, run, enabled=lambda deck: True) -> None:
        self._check_active()
        if id in self.commands:
            raise ValueError(f"command {id!r} is registered twice")
        self.commands[id] = Command(id, title, run, enabled)

    def add_menu_entry(self, menu, command_id) -> None:
        self._check_active()
        if menu != "deck" or command_id not in self.commands:
            raise ValueError(f"unknown menu {menu!r} or command {command_id!r}")
        self.menus.setdefault(menu, []).append(command_id)

    def add_deck_settings_tab(self, title, build, footer_action=None) -> None:
        self._check_active()
        self.tabs.append(Tab(title, build, footer_action))

    def add_sidebar_box(self, key, title, build, size="compact", when=lambda deck: True) -> None:
        self._check_active()
        self.boxes.append(Box(key, title, build, size, when))

    def add_render_priority(self, soon) -> None:
        self._check_active()
        self.render_priorities.append(soon)

    # -- Host: what it calls -------------------------------------------------------------------------------------

    def run_in_background(self, work, done) -> None:
        try:
            result = work()
        except BaseException as exc:  # noqa: BLE001 -- handed to done, like the real host
            done(None, exc)
        else:
            done(result, None)

    def _read(self, deck: FakeDeck) -> str:
        current = deck.path.read_bytes().decode("utf-8")
        if current != deck.text:
            raise StaleFileError(f"{deck.path.name} changed on disk since it was last loaded.")
        return current

    def _write(self, deck: FakeDeck, text: str) -> None:
        deck.path.write_bytes(text.encode("utf-8"))

    def insert_positions(self, deck) -> list[InsertPosition]:
        calls = list(SLIDE_CALL_RE.finditer(deck.text))
        if not calls:
            end = deck.text.rfind("\\end{document}")
            return [InsertPosition("At the end of the deck", len(deck.text) if end < 0 else end, "")]
        return [InsertPosition("At the beginning", calls[0].start(), calls[0].group(1))] + [
            InsertPosition(f"After {number}. {call.group(2)}", call.end(), call.group(1))
            for number, call in enumerate(calls, start=1)
        ]

    def insert_slides(self, deck, position, slides, language) -> list[Path]:
        text = self._read(deck)
        newline = "\r\n" if "\r\n" in text else "\n"
        paths: list[Path] = []
        slugs: list[str] = []
        try:
            for id_suffix, frame in slides:
                self._ids += 1
                slug = f"T{self._ids:02d}-{'EN' if language == 'en' else 'DE'}-{id_suffix}"
                path = self.root / "slides" / f"{slug}.tex"
                path.parent.mkdir(exist_ok=True)
                with path.open("x", encoding="utf-8", newline="") as destination:
                    destination.write(frame)
                paths.append(path)
                slugs.append(slug)
            lines = "".join(f"{position.indent}\\slide{{{slug}}}{newline}" for slug in slugs)
            self._write(deck, text[:position.insert_at] + lines + text[position.insert_at:])
        except Exception:
            for path in paths:
                path.unlink(missing_ok=True)
            raise
        return paths

    def edit_deck_text(self, deck, change) -> str:
        new_text = change(self._read(deck))
        self._write(deck, new_text)
        return new_text

    def deck_language(self, deck) -> str:
        """"en" if the preamble mentions english, else "de"."""
        begin = deck.text.find("\\begin{document}")
        return "en" if "english" in (deck.text if begin < 0 else deck.text[:begin]).lower() else "de"

    def open_url(self, url: str) -> None:
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError(f"not an http(s) URL: {url}")
        self.opened_urls.append(url)

    def open_deck_settings(self, deck, tab=None) -> None:
        self.opened_settings.append((deck, tab))

    # -- Host: widgets ------------------------------------------------------------------------------------------

    def Page(self) -> FakeWidget:
        return FakeWidget()

    def Field(self, label: str, widget: Any) -> FakeWidget:
        field_ = FakeWidget(label)
        field_.addWidget(widget)
        return field_

    def caption(self, text: str, tone: str = "") -> FakeWidget:
        return FakeWidget(text, tone)
