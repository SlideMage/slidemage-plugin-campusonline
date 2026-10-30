# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch, parse, and render public course data.

The public course detail page is a client-rendered app, so this module
doesn't scrape it directly -- everything here comes from the same two
REST/JSON endpoints that page's own app calls, both keyed by the numeric
``pStpSpNr`` course id. See docs/UGO_api.md for how these were found and
what else they return.
"""
from __future__ import annotations

from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import date, datetime
import errno
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Callable, Optional, Union
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


# The course system is a CAMPUSonline installation: its pages live under https://<host>/<instance>/..., its public
# REST API under https://<host>/<instance>/ee/rest/... Host and instance come from the course URL the deck links.
_COURSE_GROUPS_PATH = "/ee/rest/slc.tm.cp/student/courseGroups/firstGroups"
_COURSE_DATA_PATH = "/ee/rest/slc.tm.cp/student/courses"
_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


@dataclass(frozen=True)
class CourseSession:
    date: str
    start: str
    end: str
    location: str
    event: str
    remark: str


@dataclass(frozen=True)
class CourseGroup:
    name: str
    sessions: tuple[CourseSession, ...]


@dataclass(frozen=True)
class CourseSchedule:
    groups: tuple[CourseGroup, ...]
    # "firstGroups" can stop short of the course's totalCount of groups.
    truncated: bool = False


@dataclass(frozen=True)
class Lecturer:
    first_name: str
    last_name: str
    function: str


@dataclass(frozen=True)
class CourseDetail:
    number: str
    title: str
    semester: str
    lecturers: tuple[Lecturer, ...]
    # Languages of instruction as lower-case keys ("de", "en"), main one first.
    languages: tuple[str, ...] = ()


def _course_parts(course_url: str) -> tuple[str, str, str]:
    """(base URL "https://<host>/<instance>", course number) of a public course URL, or raise ``ValueError``."""
    if not isinstance(course_url, str):
        raise ValueError("course URL must be a string")
    parsed = urlsplit(course_url)
    instance = next((part for part in parsed.path.split("/") if part), "")
    if parsed.scheme != "https" or not parsed.hostname or not re.fullmatch(r"[A-Za-z0-9_.-]+", instance):
        raise ValueError("course URL must be an https:// link to a course page (https://<host>/<instance>/...)")
    values = parse_qs(parsed.query, keep_blank_values=True).get("pStpSpNr", [])
    if len(values) != 1 or not values[0].isdigit():
        raise ValueError("course URL must contain one numeric pStpSpNr parameter")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port = parsed.port
    authority = f"{host}:{port}" if port is not None and port != 443 else host
    return f"https://{authority}/{instance}", values[0], parsed.hostname


def _cache_key(course_url: str) -> str:
    """Canonical installation and course, independent of the course page's path or other query parameters."""
    base, number, _host = _course_parts(course_url)
    return f"{base}?pStpSpNr={number}"


def course_groups_url(course_url: str) -> str:
    """Build the public course-groups REST URL for a public course URL."""
    base, number, _host = _course_parts(course_url)
    return f"{base}{_COURSE_GROUPS_PATH}/{number}"


def course_data_url(course_url: str) -> str:
    """Build the public course-data REST URL for a public course URL.

    This is the same JSON endpoint the course detail page's Angular app
    calls (and, unlike that page, answers without a browser or a session)
    -- it's what supplies title/number/semester/lecturers.
    """
    base, number, _host = _course_parts(course_url)
    return f"{base}{_COURSE_DATA_PATH}/{number}"


def _get_json(url: str, label: str) -> bytes:
    # The server picks each text field's default language from
    # Accept-Language; ask for German, the schedule's source language.
    # _localized() below picks translations explicitly either way.
    request = Request(url, headers={"Accept": "application/json", "Accept-Language": "de"})
    try:
        with urlopen(request, timeout=15) as response:  # nosec B310: URL is validated by the caller
            if urlsplit(response.geturl()).hostname != urlsplit(url).hostname:
                raise RuntimeError(f"The course system's {label} request redirected to another host")
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(f"The course system's {label} request failed (HTTP {exc.code})") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach the course system ({label}): {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"The course system's {label} request timed out") from exc


def fetch_schedule(course_url: str) -> CourseSchedule:
    """Download and parse a public course's session groups."""
    schedule = parse_schedule(_get_json(course_groups_url(course_url), "course groups"))
    remember_schedule(course_url, schedule)
    return schedule


# -- the copy kept for background rendering ------------------------------------------------
# SlideMage's background rendering prepares the decks of courses that meet soon first. It must never go to the
# network by itself, so it reads the session dates of the last schedule this computer fetched (the Course tab
# does), kept in the plugin's cache folder. Until use_cache_folder() names that folder nothing is kept and no
# course is soon.

_CACHE_FILE_NAME = "course-schedules.json"
_cache_folder: Optional[Path] = None
_known_installations: set[str] = set()
_installations_lock = threading.Lock()
_cache_lock = threading.Lock()
_CACHE_LOCK_TIMEOUT = 2.0


def use_cache_folder(folder: Optional[Path]) -> None:
    """Keep the fetched session dates in `folder` from now on (None: keep none)."""
    global _cache_folder
    with _installations_lock:
        _cache_folder = folder
        _known_installations.clear()


def _cache_file() -> Optional[Path]:
    return None if _cache_folder is None else _cache_folder / _CACHE_FILE_NAME


def _read_cache(path: Path) -> dict:
    """The whole cache file as a dict: ``{}`` when it is missing, unreadable or not a JSON object."""
    try:
        known = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return known if isinstance(known, dict) else {}


def _entry_for(known: dict, course_url: str) -> tuple[str, dict, bool]:
    """Resolve an entry and whether it is a legacy entry safe to migrate.

    Legacy files never recorded an origin. Only use a number-only entry when the requested installation is
    the sole one known from URLs seen in this cache folder or full keys already in the file. A full key,
    even an invalid entry, always takes precedence. Merely reading never rewrites the file.
    """
    base, number, _host = _course_parts(course_url)
    key = _cache_key(course_url)
    with _installations_lock:
        _known_installations.add(base)
        for existing_key in known:
            try:
                _known_installations.add(_course_parts(existing_key)[0])
            except ValueError:
                continue
        legacy = key not in known and _known_installations == {base} and isinstance(known.get(number), dict)
    entry = known.get(number) if legacy else known.get(key)
    return key, entry if isinstance(entry, dict) else {}, legacy


@contextmanager
def _cache_write_lock(path: Path):
    """Serialize the entire read/modify/publish across threads and application processes.

    Lock a separate, persistent file: replacing the JSON must not replace the inode being locked. Both
    lock acquisitions share a bounded timeout; callers treat lock failures like any other cache failure.
    Readers need no file lock because publication is atomic.
    """
    deadline = time.monotonic() + _CACHE_LOCK_TIMEOUT
    if not _cache_lock.acquire(timeout=_CACHE_LOCK_TIMEOUT):
        raise TimeoutError("Course cache is busy")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_name(path.name + ".lock").open("a+b") as lock_file:
            if os.name == "nt":
                import msvcrt

                if os.fstat(lock_file.fileno()).st_size == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()

                def lock():
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)

                def unlock():
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                def lock():
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                def unlock():
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

            while True:
                try:
                    lock()
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Course cache is busy") from exc
                    time.sleep(min(0.02, remaining))
            try:
                yield
            finally:
                unlock()
    finally:
        _cache_lock.release()


def _write_cache(path: Path, text: str) -> None:
    """Publish a complete file in one replacement; the caller holds _cache_write_lock()."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _update_entry(course_url: str, change: Callable[[dict], dict]) -> None:
    """Store `change(entry)` as the course's entry in the cache, where `entry` is its current entry (or ``{}``).
    Best-effort: a failure here is not the caller's."""
    try:
        path = _cache_file()
        if path is None:
            return
        with _cache_write_lock(path):
            known = _read_cache(path)
            key, entry, legacy = _entry_for(known, course_url)
            known[key] = change(dict(entry))
            if legacy:
                del known[_course_parts(course_url)[1]]
            _write_cache(path, json.dumps(known))
    except Exception:  # noqa: BLE001
        pass


def _sort_day(text: str) -> date:
    """A session's date for sorting; one the server sent in another format sorts last instead of raising."""
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except (TypeError, ValueError):
        return date.max


def remember_schedule(course_url: str, schedule: CourseSchedule) -> None:
    """Keep the session dates and the sessions of `schedule` for session_soon() and the Course box. A title
    already kept for the course stays. Best-effort: a failure here is not the caller's."""
    dates = sorted({s.date for group in schedule.groups for s in group.sessions})
    found = {(s.date, s.start, s.end, s.location) for group in schedule.groups for s in group.sessions}
    sessions = [
        {"date": day, "start": start, "end": end, "location": location}
        for day, start, end, location in sorted(found, key=lambda item: (_sort_day(item[0]), *item))
    ]
    fetched = datetime.now().isoformat(timespec="seconds")
    _update_entry(course_url, lambda entry: {**entry, "fetched": fetched, "dates": dates, "sessions": sessions})


def remember_title(course_url: str, title: str) -> None:
    """Keep the course's `title` for the Course box, creating the entry if there is none. An empty title is not
    kept. Best-effort, like remember_schedule()."""
    if not isinstance(title, str) or not title.strip():
        return
    _update_entry(course_url, lambda entry: {**entry, "title": title.strip()})


def cached_entry(course_url: str | None) -> dict:
    """The cache's entry for the course: ``{}`` when there is none, no cache folder is set, the cache cannot be
    read or `course_url` is not a course URL. Never raises and never fetches."""
    try:
        path = _cache_file()
        if path is None:
            return {}
        _key, entry, _legacy = _entry_for(_read_cache(path), course_url)
    except Exception:  # noqa: BLE001
        return {}
    return entry if isinstance(entry, dict) else {}


def adopt_legacy_cache(legacy_folder: Path | None) -> bool:
    """Copy the session dates SlideMage kept before the plugin existed (`legacy_folder`) into the plugin's cache
    folder, so a course that meets soon still counts without a refetch. Called once from activate(). Never
    overwrites an existing plugin cache, never moves or deletes the old file, and copies nothing that is not valid
    JSON. Originless entries are kept unresolved: cached_entry() applies the same conservative ownership
    check to adopted entries, and the next write migrates an unambiguous entry to its full key.
    Local files only, and cheap."""
    path = _cache_file()
    if path is None or legacy_folder is None:
        return False
    source = Path(legacy_folder) / _CACHE_FILE_NAME
    if not source.is_file():
        return False
    try:
        text = source.read_text(encoding="utf-8")
        if not isinstance(json.loads(text), dict):
            return False
        with _cache_write_lock(path):
            if path.exists():
                return False
            _write_cache(path, text)
            return True
    except Exception:  # noqa: BLE001 -- adoption is best-effort, like the other cache writes
        return False


def session_soon(course_url: Optional[str], *, days: int = 7, today: Optional[date] = None) -> bool:
    """Whether the cached schedule of the course has a session today or within `days` days. False without a
    cached schedule or for an unknown course: this never fetches anything."""
    path = _cache_file()
    if not course_url or path is None:
        return False
    try:
        dates = cached_entry(course_url).get("dates", [])
        today = today or date.today()
        for text in dates:
            day = datetime.strptime(text, "%d.%m.%Y").date()
            if 0 <= (day - today).days <= days:
                return True
    except Exception:  # noqa: BLE001 -- no cache, a course url that is not one: no boost
        return False
    return False


def fetch_course_detail(course_url: str, language: str = "de") -> CourseDetail:
    """Download and parse a public course's title/number/semester/lecturers,
    with the title and semester in `language` ("de" or "en") where UGO has it."""
    return parse_course_detail(_get_json(course_data_url(course_url), "course data"), language)


def _localized(langdata: dict | None, language: str = "de") -> str:
    """A UGO "langdata" field's text in `language`, else German, else its
    default value -- stripped, since UGO's translations can carry stray
    whitespace."""
    if not langdata:
        return ""
    translations = {
        translation.get("lang"): translation.get("value")
        for translation in (langdata.get("translations") or {}).get("translation") or []
    }
    for lang in (language, "de"):
        if translations.get(lang):
            return translations[lang].strip()
    return (langdata.get("value") or "").strip()


def _parse_appointment(appointment: dict) -> CourseSession:
    start = datetime.fromisoformat(appointment["timestampFrom"]["value"])
    end = datetime.fromisoformat(appointment["timestampTo"]["value"])
    event_type = appointment.get("appointmentEventTypeDto") or {}
    return CourseSession(
        date=start.strftime("%d.%m.%Y"),
        start=start.strftime("%H:%M"),
        end=end.strftime("%H:%M"),
        location=(appointment.get("resourceName") or "").strip(),
        event=_localized(event_type.get("name")),
        remark=(appointment.get("comment") or "").strip(),
    )


# Anything a malformed response can raise while being walked.
_SHAPE_ERRORS = (TypeError, ValueError, KeyError, IndexError, AttributeError)


def parse_schedule(json_source: Union[bytes, str]) -> CourseSchedule:
    """Parse the ``slc.tm.cp`` course-groups REST response without making a
    network request. Raises ``ValueError`` if it isn't that response shape.

    The response repeats the course's shared (standard-group) sessions
    inside every group. They're pulled out into one "Standardgruppe" group,
    listed first, and each other group keeps only its own sessions -- the
    same split as the old appointments page. A group with no sessions of
    its own is kept, with no sessions.
    """
    try:
        payload = json.loads(json_source)
        course_groups = payload["courseGroupDtos"] or []
        shared: dict[object, tuple[str, CourseSession]] = {}
        standard_group_ids: set[object] = set()
        listed: list[tuple[object, CourseGroup]] = []
        for group in course_groups:
            own: list[CourseSession] = []
            for appointment in group.get("appointmentDtos") or []:
                session = _parse_appointment(appointment)
                owner = appointment.get("courseGroupDto") or {}
                if owner.get("standardgroupFlag") == "J":
                    standard_group_ids.add(owner.get("id"))
                    key = appointment.get("id") or session
                    shared.setdefault(key, (appointment["timestampFrom"]["value"], session))
                else:
                    own.append(session)
            name = (group.get("name") or "").strip() or "Standardgruppe"
            listed.append((group.get("id"), CourseGroup(name, tuple(own))))
        # The standard group itself, if listed, is already the "Standardgruppe" below.
        groups = [group for group_id, group in listed
                  if group.sessions or group_id is None or group_id not in standard_group_ids]
        if shared:
            ordered = sorted(shared.values(), key=lambda item: item[0])
            groups.insert(0, CourseGroup("Standardgruppe", tuple(session for _, session in ordered)))
        total = payload.get("totalCount")
    except _SHAPE_ERRORS as exc:
        raise ValueError("course groups response is not the expected shape") from exc
    return CourseSchedule(
        groups=tuple(groups),
        truncated=isinstance(total, int) and total > len(course_groups),
    )


def parse_course_detail(json_source: Union[bytes, str], language: str = "de") -> CourseDetail:
    """Parse the ``slc.tm.cp`` course-data REST response without making a
    network request, with the title and semester in `language` where UGO
    has it. Raises ``ValueError`` if it isn't that response shape."""
    try:
        payload = json.loads(json_source)
        course = payload["resource"][0]["content"]["cpCourseDetailDto"]["cpCourseDto"]
        lecturers = tuple(
            Lecturer(
                first_name=(lectureship["identityLibDto"]["firstName"] or "").strip(),
                last_name=(lectureship["identityLibDto"]["lastName"] or "").strip(),
                function=(lectureship["teachingFunction"]["name"] or "").strip(),
            )
            for lectureship in course.get("lectureships") or []
        )
        course_languages = sorted(
            course.get("courseLanguageDtos") or [],
            key=lambda entry: not entry.get("mainLanguage"),
        )
        languages = tuple(dict.fromkeys(
            key.strip().lower()
            for entry in course_languages
            if (key := (entry.get("languageDto") or {}).get("key"))
        ))
        return CourseDetail(
            number=course["courseNumber"]["courseNumber"],
            title=_localized(course["courseTitle"], language),
            semester=_localized(course["semesterDto"]["semesterDesignation"], language),
            lecturers=lecturers,
            languages=languages,
        )
    except _SHAPE_ERRORS as exc:
        raise ValueError("course data response is not the expected shape") from exc


def _escape_latex(text: str) -> str:
    return "".join(_LATEX_SPECIALS.get(character, character) for character in text)


# The slide's own wording per deck language ("de"/"en", as
# SlideMage's transcript.deck_language_of() reports it). The course system serves the
# schedule in German; an English deck gets its table translated by
# translate_to_english() below (v4.1.0, direct instruction).
LABELS = {
    "de": {
        "title": "Abhaltungstermine",
        "date": "Datum", "time": "Zeit", "location": "Ort", "event": "Termin",
        "no_sessions": "Keine Termine verfügbar.",
    },
    "en": {
        "title": "Course sessions",
        "date": "Date", "time": "Time", "location": "Location", "event": "Session",
        "no_sessions": "No sessions available.",
    },
}

# German terms the course system uses in group names, event types and
# remarks. Whole words only, longest first. Group names and event types
# are translated term by term ("Gruppe Wirtschaftsinformatik" -> "Group
# Wirtschaftsinformatik"); a free-text remark only when every word in it
# is known, since a half-translated sentence reads worse than German.
_GERMAN_TO_ENGLISH = {
    "Standardgruppe": "Standard group",
    "Gruppe": "Group",
    "Abhaltung": "Class",
    "Vorbesprechung": "Preliminary meeting",
    "Nachbesprechung": "Review meeting",
    "Einführung": "Introduction",
    "Vorlesung": "Lecture",
    "Übung": "Exercise",
    "Tutorium": "Tutorial",
    "Präsentation": "Presentation",
    "Präsentationen": "Presentations",
    "Prüfung": "Exam",
    "Klausur": "Exam",
    "Zwischenprüfung": "Midterm exam",
    "Endprüfung": "Final exam",
    "Abschlussprüfung": "Final exam",
    "Nachtermin": "Resit",
    "Wiederholungsprüfung": "Resit exam",
    "Ersatztermin": "Replacement session",
    "Zusatztermin": "Additional session",
    "Blocktermin": "Block session",
    "Exkursion": "Excursion",
    "Sprechstunde": "Office hours",
    "Fragestunde": "Q&A session",
    "Ausfall": "Cancelled",
    "entfällt": "cancelled",
    "abgesagt": "cancelled",
    "verschoben": "postponed",
    "Hörsaal": "Lecture hall",
    "Seminarraum": "Seminar room",
    "und": "and",
    "bis": "to",
    "mit": "with",
    "ohne": "without",
    "Anwesenheitspflicht": "attendance required",
    "Anmeldung": "registration",
}
_GERMAN_WORD_RE = re.compile(
    r"(?<!\w)(" + "|".join(
        re.escape(word) for word in sorted(_GERMAN_TO_ENGLISH, key=len, reverse=True)
    ) + r")(?!\w)"
)


# Letters only: numbers ("Gruppe 2", "Prüfung 1") need no translation.
_WORD_RE = re.compile(r"[^\W\d_]+")


def translate_to_english(text: str, whole_only: bool = False) -> str:
    """Replace the known German schedule terms in `text` with English.
    With `whole_only`, `text` comes back unchanged unless every word in it
    is a known term."""
    translated = _GERMAN_WORD_RE.sub(lambda match: _GERMAN_TO_ENGLISH[match.group(1)], text)
    if whole_only and _WORD_RE.search(_GERMAN_WORD_RE.sub(" ", text)):
        return text
    return translated


def translate_schedule(schedule: CourseSchedule) -> CourseSchedule:
    """The same schedule with group names, event types and (fully known)
    remarks translated from German to English; dates, times and rooms
    unchanged."""
    return CourseSchedule(
        truncated=schedule.truncated,
        groups=tuple(
            CourseGroup(
                name=translate_to_english(group.name),
                sessions=tuple(
                    CourseSession(
                        date=session.date, start=session.start, end=session.end,
                        location=session.location,
                        event=translate_to_english(session.event),
                        remark=translate_to_english(session.remark, whole_only=True),
                    )
                    for session in group.sessions
                ),
            )
            for group in schedule.groups
        ),
    )


def table_environment() -> str:
    """The framework's table environment: SMTable from SlideMage's own theme on (the release that added
    compat_own_theme, which also migrates a project's gothamtable), gothamtable before. Asked of the running
    SlideMage, not its version number, because the version numbers are renumbered later."""
    try:
        import slidemage.compat_own_theme  # noqa: F401  (a plain import also works in the frozen app)
    except ImportError:
        return "gothamtable"
    return "SMTable"


def render_group_table(group: CourseGroup, language: str = "de") -> str:
    """Render one group as safe LaTeX that can be placed inside a frame,
    with the column headings in `language` ("de" or "en"). The cells are
    used as they are -- translate_schedule() first for an English deck."""
    labels = LABELS.get(language, LABELS["de"])
    if not group.sessions:
        return ("\\small \\textbf{" + _escape_latex(group.name) + "}\\par "
                + labels["no_sessions"])

    rows = []
    for session in group.sessions:
        time = "--".join(part for part in (session.start, session.end) if part)
        detail = " — ".join(part for part in (session.event, session.remark) if part)
        rows.append(" & ".join(_escape_latex(value) for value in (
            session.date, time, session.location, detail,
        )) + r" \\")
    heading = " & ".join(
        "\\textbf{" + labels[key] + "}" for key in ("date", "time", "location", "event"))
    table = table_environment()
    return "\n".join((
        r"\scriptsize",
        "\\textbf{" + _escape_latex(group.name) + "}\\par\\vspace{2pt}",
        r"\renewcommand{\arraystretch}{1.08}",
        # the project's table style (yellow rules, flush edges); same column
        # geometry as the former \tabcolsep 2pt + @{} edges
        "\\begin{" + table + r"}[gap=4pt]{p{.13\linewidth}p{.14\linewidth}p{.22\linewidth}p{.42\linewidth}}",
        r"\toprule",
        heading + r" \\",
        r"\midrule",
        *rows,
        r"\bottomrule",
        "\\end{" + table + "}",
    ))


def render_title_slide(detail: CourseDetail, lecturers: tuple[Lecturer, ...]) -> str:
    """Render a ``\\titleframe{title}{names\\\\semester}`` call from fetched
    course data and a caller-selected subset of its lecturers."""
    names = _escape_latex(", ".join(f"{lecturer.first_name} {lecturer.last_name}" for lecturer in lecturers))
    semester = _escape_latex(detail.semester)
    subtitle = r"\\".join(part for part in (names, semester) if part)
    return r"\titleframe{" + _escape_latex(detail.title) + "}{" + subtitle + "}"
