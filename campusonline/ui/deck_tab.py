# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Course tab of the Deck settings sheet: the deck's course link, and below it the admin slides -- fetch the
online course the deck links, choose which slides to generate (a title slide naming some of the lecturers, the
sessions table of one group) and where in the deck they go.

The link saves on its own "Save link" button: the sheet's footer button of this tab is "Insert slides", so the
link has no footer button of its own, and a link is something to confirm before the course is read from it.
The deck the host hands out is a snapshot, so after the link is saved the tab asks to be reopened rather than
fetching a course it could not insert into.

The course is fetched once, in the background, when the tab is first shown; its two parts (schedule and course
detail) can fail independently, and a part that is not available leaves its section disabled. The fetching and
the slides' frames are admin_slides', the insertion the host's.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .. import SIDEBAR_BOX_COURSE, admin_slides, course_link, course_schedule
from slidemage.plugin_api import Deck, Host, InsertPosition, StaleFileError, Widget

STALE = "The deck changed on disk; reopen Deck settings."
NO_LINK = "This deck links no course page. Save one above, then open Admin slides again."
SAVED = "Link saved. Reopen Deck settings to load the course."


def build_tab(host: Host, deck: Deck) -> Widget:
    page = host.Page()
    page.controller = CourseTab(host, deck, page)
    return page


class _OnShow(QObject):
    """Calls `callback` when the widget it watches is first shown."""

    def __init__(self, widget: QWidget, callback) -> None:
        super().__init__(widget)
        self._callback = callback
        widget.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Show:
            self._callback()
        return False


class CourseTab:
    """The state and behaviour of one Course tab; `page` (a host Page) holds the widgets."""

    def __init__(self, host: Host, deck: Deck, page: Widget) -> None:
        self.host, self.deck, self.page = host, deck, page
        self.url = course_link.parse_course_url(deck.text) or ""
        self.language = host.deck_language(deck)
        self.slide_specs: list[tuple[str, str]] = []
        self.schedule: course_schedule.CourseSchedule | None = None
        self.detail: course_schedule.CourseDetail | None = None
        self.selected_group: course_schedule.CourseGroup | None = None
        self._lecturer_checks: list[tuple[QCheckBox, course_schedule.Lecturer]] = []
        self._positions: list[InsertPosition] = host.insert_positions(deck)
        self._started = self._gone = self._inserted = False
        self._build()
        _OnShow(page, self.start)
        page.destroyed.connect(self._on_gone)
        self._show_waiting()

    # -- widgets ------------------------------------------------------------------------------------------------

    def _build(self) -> None:
        host, layout = self.host, self.page.body

        self.url_edit = QLineEdit(self.url)
        self.url_edit.setPlaceholderText("https://… (the course page)")
        self.open_button = QPushButton("Open")
        self.open_button.setEnabled(bool(self.url))
        self.save_button = QPushButton("Save link")
        self.save_button.setEnabled(False)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self.url_edit, self.open_button, self.save_button):
            row_layout.addWidget(widget)
        row_layout.setStretch(0, 1)
        layout.addWidget(host.Field("Course link", row))
        self.link_status = host.caption("")
        self.link_error = host.caption("", "error")
        self.link_error.hide()
        layout.addWidget(self.link_status)
        layout.addWidget(self.link_error)
        self.url_edit.textChanged.connect(self._on_link_edited)
        self.url_edit.returnPressed.connect(self.save_link)
        self.save_button.clicked.connect(self.save_link)
        self.open_button.clicked.connect(self.open_link)

        self.status = host.caption("")
        layout.addWidget(self.status)
        self.language_warning = host.caption("", "error")
        self.language_warning.hide()
        layout.addWidget(self.language_warning)

        self.title_section = host.Page()
        self.title_check = QCheckBox("Title slide")
        self.title_status = host.caption("")
        self.lecturers = QVBoxLayout()
        self.lecturers.setContentsMargins(0, 0, 0, 0)
        self.lecturers.setSpacing(4)
        for widget in (self.title_check, self.title_status):
            self.title_section.body.addWidget(widget)
        self.title_section.body.addLayout(self.lecturers)
        layout.addWidget(self.title_section)

        self.sessions_section = host.Page()
        self.sessions_check = QCheckBox("Course sessions")
        self.sessions_status = host.caption("")
        self.group_combo = QComboBox()
        self.group_combo.hide()
        for widget in (self.sessions_check, self.sessions_status, self.group_combo):
            self.sessions_section.body.addWidget(widget)
        layout.addWidget(self.sessions_section)
        for section, check in ((self.title_section, self.title_check), (self.sessions_section, self.sessions_check)):
            check.setChecked(True)
            check.toggled.connect(self._update_preview)
            section.setEnabled(False)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)

        self.position_combo = QComboBox()
        for position in self._positions:
            self.position_combo.addItem(position.label)
        self.position_combo.setCurrentIndex(len(self._positions) - 1)
        self.position_field = host.Field("Insert", self.position_combo)
        layout.addWidget(self.position_field)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(130)
        self.preview.setPlaceholderText("The generated LaTeX will appear here.")
        layout.addWidget(self.preview)
        layout.addStretch(1)

    @property
    def position(self) -> InsertPosition:
        return self._positions[self.position_combo.currentIndex()]

    # -- the course link ----------------------------------------------------------------------------------------

    def _on_link_edited(self, text: str) -> None:
        self.save_button.setEnabled(text.strip() != self.url)
        self.link_status.setText("")
        self.link_error.hide()

    def open_link(self) -> None:
        try:
            self.host.open_url(course_link.normalize_course_url(self.url_edit.text()))
        except (ValueError, OSError) as exc:
            self._show_link_error(str(exc))

    def save_link(self) -> None:
        text = self.url_edit.text().strip()
        if text == self.url:
            return
        try:
            self.host.edit_deck_text(self.deck, lambda t: course_link.course_url_text(t, text, self.deck.name))
        except StaleFileError:
            self._show_link_error(STALE)
        except ValueError as exc:
            self._show_link_error(str(exc))
        else:
            self.url = text
            self.save_button.setEnabled(False)
            self.open_button.setEnabled(bool(text))
            self._show_link_ok(SAVED)

    def _show_link_error(self, text: str) -> None:
        self.link_error.setText(text)
        self.link_error.setVisible(bool(text))

    def _show_link_ok(self, text: str) -> None:
        self.link_error.hide()
        self.link_status.setText(text)

    # -- the admin slides ---------------------------------------------------------------------------------------

    def _show_waiting(self) -> None:
        """Before the fetch: the hint a deck with no linked course gets, else a waiting note."""
        linked = bool(self.url)
        self.status.setText("Loading the linked course…" if linked else NO_LINK)
        self.title_status.setText("Loading…" if linked else "")
        self.sessions_status.setText("Loading…" if linked else "")
        for widget in (self.title_section, self.sessions_section, self.position_field, self.preview):
            widget.setVisible(linked)

    def start(self) -> None:
        """Fetch the course (once); called when the tab is first shown."""
        if self._started or not self.url:
            return
        self._started = True
        url, language = self.url, self.language
        self.host.run_in_background(lambda: admin_slides.fetch(url, language), self._on_fetched)

    def _on_gone(self, *_: object) -> None:
        self._gone = True

    def _on_fetched(self, result: tuple[object, object] | None, error: BaseException | None) -> None:
        # The worker has already updated the cache, even if the sheet closed while it was fetching.
        if error is None and result is not None and any(
                isinstance(part, (course_schedule.CourseSchedule, course_schedule.CourseDetail)) for part in result):
            refresh = getattr(self.host, "refresh_sidebar_box", None)
            if refresh is not None:  # older hosts have no explicit box invalidation
                refresh(SIDEBAR_BOX_COURSE)
        if self._gone:      # the sheet closed meanwhile
            return
        if error is not None or result is None:
            result = (str(error), str(error))
        self._on_loaded(*result)

    def _on_loaded(self, schedule_result: object, detail_result: object) -> None:
        self.status.setText("")
        self._apply_schedule(schedule_result)
        self._apply_detail(detail_result)
        if isinstance(detail_result, course_schedule.CourseDetail):
            warning = admin_slides.language_warning(self.language, detail_result)
            self.language_warning.setText(warning)
            self.language_warning.setVisible(bool(warning))
        self._update_preview()

    def _apply_schedule(self, result: object) -> None:
        if isinstance(result, course_schedule.CourseSchedule) and result.groups:
            self.schedule = result
            self.selected_group = result.groups[0]
            self.group_combo.addItems(
                [group.name if group.sessions else f"{group.name} (empty)" for group in result.groups])
            self.group_combo.setVisible(len(result.groups) > 1)
            status = f"{len(result.groups)} group(s) found."
            if result.truncated:
                status += " The course system returned only some of this course's groups -- check the course page."
            self.sessions_status.setText(status)
            self.sessions_section.setEnabled(True)
        else:
            self.sessions_status.setText(
                f"Not available: {result if isinstance(result, str) else 'No session groups found.'}")
            self.sessions_check.setChecked(False)

    def _apply_detail(self, result: object) -> None:
        if isinstance(result, course_schedule.CourseDetail) and result.lecturers:
            self.detail = result
            self.title_status.setText(f"{result.title} — {result.semester}")
            for lecturer in result.lecturers:
                check = QCheckBox(f"{lecturer.first_name} {lecturer.last_name} ({lecturer.function})")
                check.setChecked(True)
                check.toggled.connect(self._update_preview)
                self._lecturer_checks.append((check, lecturer))
                self.lecturers.addWidget(check)
            self.title_section.setEnabled(True)
        else:
            self.title_status.setText(
                f"Not available: {result if isinstance(result, str) else 'No lecturers found.'}")
            self.title_check.setChecked(False)

    def _on_group_changed(self, index: int) -> None:
        if self.schedule is not None and 0 <= index < len(self.schedule.groups):
            self.selected_group = self.schedule.groups[index]
            self._update_preview()

    def _update_preview(self) -> None:
        wanted = self.title_check.isChecked(), self.sessions_check.isChecked()
        self.slide_specs = admin_slides.plan_slides(
            self.language,
            detail=self.detail if wanted[0] else None,
            lecturers=tuple(lecturer for check, lecturer in self._lecturer_checks if check.isChecked()),
            group=self.selected_group if wanted[1] and self.schedule is not None else None)
        self.preview.setPlainText("\n\n".join(source for _, source in self.slide_specs))
        self.page.changed.emit()

    # -- the footer button --------------------------------------------------------------------------------------

    def can_insert(self) -> bool:
        return bool(self.slide_specs) and not self._inserted

    def insert(self) -> None:
        """Insert slides: create the planned slides at the chosen place, as one edit."""
        if not self.can_insert():
            return
        try:
            paths = self.host.insert_slides(self.deck, self.position, self.slide_specs, self.language)
        except StaleFileError:
            self.status.setText(STALE)
        except OSError as exc:
            self.status.setText(f"Could not insert the slides: {exc}")
        else:
            # The deck snapshot is out of date now; a second insert would be refused as stale.
            self._inserted = True
            self.status.setText(f"Inserted {len(paths)} slide(s). Reopen Deck settings to insert more.")
            self.page.changed.emit()
