# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cache transactions keep concurrent updates and expose only complete JSON files."""
from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from campusonline import course_schedule as cs

FIRST = "https://one.example/instance/course?pStpSpNr=123"
SECOND = "https://two.example/instance/course?pStpSpNr=456"


@pytest.fixture
def cache(tmp_path):
    cs.use_cache_folder(tmp_path)
    yield tmp_path / "course-schedules.json"
    cs.use_cache_folder(None)


@pytest.mark.parametrize("same_course", [False, True])
def test_writer_paused_after_read_cannot_overwrite_another_threads_update(cache, monkeypatch, same_course):
    real_read = cs._read_cache
    first_read, release_first, second_attempt, second_read = (threading.Event() for _ in range(4))

    def blocked_read(path):
        data = real_read(path)
        if threading.current_thread().name == "first-fetch":
            first_read.set()
            assert release_first.wait(5)
        else:
            second_read.set()
        return data

    def second_write():
        second_attempt.set()
        if same_course:
            cs.remember_schedule(FIRST, cs.CourseSchedule(()))
        else:
            cs.remember_title(SECOND, "Second")

    monkeypatch.setattr(cs, "_read_cache", blocked_read)
    first = threading.Thread(name="first-fetch", target=cs.remember_title, args=(FIRST, "First"))
    second = threading.Thread(target=second_write)
    first.start()
    try:
        assert first_read.wait(5)
        second.start()
        assert second_attempt.wait(5)
        assert not second_read.wait(0.1)  # the second read must wait for the first transaction
    finally:
        release_first.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert cs.cached_entry(FIRST)["title"] == "First"
    if same_course:
        assert cs.cached_entry(FIRST)["dates"] == []
    else:
        assert cs.cached_entry(SECOND) == {"title": "Second"}


def _process_write(folder, url, title, read, release, attempted):
    """Spawned processes have independent module locks and share only the lock file."""
    cs.use_cache_folder(Path(folder))
    cs._CACHE_LOCK_TIMEOUT = 5
    real_read = cs._read_cache

    def blocked_read(path):
        data = real_read(path)
        read.set()
        if release is not None:
            assert release.wait(10)
        return data

    cs._read_cache = blocked_read
    attempted.set()
    cs.remember_title(url, title)


def test_process_writers_serialize_the_read_modify_write(cache):
    context = multiprocessing.get_context("spawn")
    first_read, release_first, second_read, first_attempt, second_attempt = (context.Event() for _ in range(5))
    first = context.Process(target=_process_write,
                            args=(cache.parent, FIRST, "First", first_read, release_first, first_attempt))
    second = context.Process(target=_process_write,
                             args=(cache.parent, SECOND, "Second", second_read, None, second_attempt))
    first.start()
    try:
        assert first_read.wait(5)
        second.start()
        assert second_attempt.wait(5)
        assert not second_read.wait(0.1)
    finally:
        release_first.set()
        first.join(5)
        if second.pid is not None:
            second.join(5)
        for process in (first, second):
            if process.is_alive():
                process.terminate()
                process.join(5)
    assert first.exitcode == second.exitcode == 0
    assert cs.cached_entry(FIRST) == {"title": "First"}
    assert cs.cached_entry(SECOND) == {"title": "Second"}


@pytest.mark.parametrize("adopt", [False, True])
def test_readers_see_complete_old_or_new_file_during_publication(cache, monkeypatch, adopt):
    if not adopt:
        cs.remember_title(FIRST, "Old")
    old = cache.read_bytes() if cache.exists() else None
    staged, release = threading.Event(), threading.Event()
    real_replace = os.replace
    published = []

    def paused_replace(source, destination):
        if destination == cache:
            published.append(json.loads(Path(source).read_text()))
            assert Path(source).parent == cache.parent
            staged.set()
            assert release.wait(5)
        return real_replace(source, destination)

    monkeypatch.setattr(cs.os, "replace", paused_replace)
    if adopt:
        legacy = cache.parent / "legacy"
        legacy.mkdir()
        (legacy / cache.name).write_text('{"123": {"title": "Adopted"}}')
        writer = threading.Thread(target=cs.adopt_legacy_cache, args=(legacy,))
    else:
        writer = threading.Thread(target=cs.remember_title, args=(FIRST, "New"))
    writer.start()
    try:
        assert staged.wait(5)
        assert cs.cached_entry(FIRST) == ({} if adopt else {"title": "Old"})
        assert (cache.read_bytes() if cache.exists() else None) == old
        assert published  # the staged file already contains valid, complete JSON
    finally:
        release.set()
        writer.join(5)
    assert not writer.is_alive()
    assert cs.cached_entry(FIRST) == {"title": "Adopted" if adopt else "New"}
    assert not list(cache.parent.glob("*.tmp"))


def test_thread_lock_timeout_skips_write_and_releases_locks(cache, monkeypatch):
    cs.remember_title(FIRST, "Old")
    old = cache.read_bytes()
    monkeypatch.setattr(cs, "_CACHE_LOCK_TIMEOUT", 0.05)
    with cs._cache_write_lock(cache):
        cs.remember_title(FIRST, "Skipped")
    assert cache.read_bytes() == old
    cs.remember_title(FIRST, "New")
    assert cs.cached_entry(FIRST) == {"title": "New"}


@pytest.mark.parametrize("adopt", [False, True])
def test_process_lock_timeout_skips_write_and_adoption(cache, adopt):
    cs.remember_title(FIRST, "Old")
    old = cache.read_bytes()
    script = """
from pathlib import Path
import sys
from campusonline import course_schedule as cs
folder = Path(sys.argv[1])
cs.use_cache_folder(folder)
cs._CACHE_LOCK_TIMEOUT = 0.05
reads = []
cs._read_cache = lambda path: reads.append(path) or {}
if sys.argv[3] == 'adopt':
    assert cs.adopt_legacy_cache(Path(sys.argv[4])) is False
    assert not (folder / 'course-schedules.json').exists()
else:
    cs.remember_title(sys.argv[2], 'Skipped')
assert reads == [], 'must acquire the process lock before reading'
"""
    env = {**os.environ, "PYTHONPATH": str(Path(cs.__file__).resolve().parents[1])}
    destination = cache.parent / "adoption" / cache.name if adopt else cache
    with cs._cache_write_lock(destination):
        # A second process must respect the OS lock even though its module lock is free.
        result = subprocess.run([sys.executable, "-c", script, str(destination.parent), FIRST,
                                 "adopt" if adopt else "write", str(cache.parent)],
                                env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert cache.read_bytes() == old
    cs.remember_title(FIRST, "New")
    assert cs.cached_entry(FIRST) == {"title": "New"}


def test_failed_replace_preserves_old_json_cleans_temporary_and_releases_lock(cache, monkeypatch):
    cs.remember_title(FIRST, "Old")
    old = cache.read_bytes()

    def fail(*args):
        raise OSError("Cannot publish cache")

    with monkeypatch.context() as patch:
        patch.setattr(cs.os, "replace", fail)
        cs.remember_title(FIRST, "Skipped")
    assert cache.read_bytes() == old
    assert not list(cache.parent.glob("*.tmp"))
    cs.remember_title(SECOND, "Second")
    assert cs.cached_entry(FIRST) == {"title": "Old"}
    assert cs.cached_entry(SECOND) == {"title": "Second"}
