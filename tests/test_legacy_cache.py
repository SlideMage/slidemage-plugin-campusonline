# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from campusonline import course_schedule


LEGACY_TEXT = '{"12345": {"fetched": "2026-10-01T09:00:00", "dates": ["20.10.2026"]}}'


@pytest.fixture
def plugin_folder(tmp_path):
    folder = tmp_path / "plugin-cache"
    course_schedule.use_cache_folder(folder)
    yield folder
    course_schedule.use_cache_folder(None)


@pytest.fixture
def legacy_folder(tmp_path):
    folder = tmp_path / "slidemage-cache"
    folder.mkdir()
    (folder / "course-schedules.json").write_text(LEGACY_TEXT, encoding="utf-8")
    return folder


def test_copies_the_legacy_cache_when_the_plugin_has_none(plugin_folder, legacy_folder):
    assert course_schedule.adopt_legacy_cache(legacy_folder) is True
    assert (plugin_folder / "course-schedules.json").read_bytes() == (legacy_folder / "course-schedules.json").read_bytes()
    assert (legacy_folder / "course-schedules.json").read_text(encoding="utf-8") == LEGACY_TEXT


def test_does_not_overwrite_an_existing_plugin_cache(plugin_folder, legacy_folder):
    plugin_folder.mkdir()
    (plugin_folder / "course-schedules.json").write_text('{"own": {}}', encoding="utf-8")
    assert course_schedule.adopt_legacy_cache(legacy_folder) is False
    assert (plugin_folder / "course-schedules.json").read_text(encoding="utf-8") == '{"own": {}}'


@pytest.mark.parametrize("case", ["none_folder", "missing_legacy_file", "no_cache_folder"])
def test_returns_false_when_there_is_nothing_to_adopt(case, plugin_folder, legacy_folder, tmp_path):
    if case == "none_folder":
        assert course_schedule.adopt_legacy_cache(None) is False
    elif case == "missing_legacy_file":
        empty = tmp_path / "empty"
        empty.mkdir()
        assert course_schedule.adopt_legacy_cache(empty) is False
    else:
        course_schedule.use_cache_folder(None)
        assert course_schedule.adopt_legacy_cache(legacy_folder) is False
    assert not (plugin_folder / "course-schedules.json").exists()


def test_invalid_json_is_not_adopted_and_leaves_no_file(plugin_folder, legacy_folder):
    (legacy_folder / "course-schedules.json").write_text("{not json", encoding="utf-8")
    assert course_schedule.adopt_legacy_cache(legacy_folder) is False
    assert not (plugin_folder / "course-schedules.json").exists()
    assert list(plugin_folder.iterdir()) == []


def test_creates_the_plugin_cache_folder_when_missing(plugin_folder, legacy_folder):
    assert not plugin_folder.exists()
    assert course_schedule.adopt_legacy_cache(legacy_folder) is True
    assert (plugin_folder / "course-schedules.json").is_file()
