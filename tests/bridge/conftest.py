# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The bridge's tests need SlideMage itself: without it (the Check workflow) they are skipped."""
import os

import pytest

pytest.importorskip("slidemage", reason="SlideMage is not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from slidemage.project import ProjectContext  # noqa: E402 -- only once SlideMage is known to be there


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(tmp_path):
    """The project that tests build their files in directly under tmp_path."""
    return ProjectContext.at(tmp_path)
