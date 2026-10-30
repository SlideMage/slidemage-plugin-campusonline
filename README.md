# CampusOnline

Connects a SlideMage deck to its course on CAMPUSonline, the course management system many universities use. It
was built for the University of Graz (UGO) and works with any CAMPUSonline server whose course pages are public.

- **Course link.** Give a deck the address of its course page in the deck's settings, on the Course tab, and open
  the page from there or from the Deck menu. The link is kept in the deck's preamble as a comment
  (`%% SlideMage course URL: …`); without the plugin the deck compiles the same.
- **Admin slides.** Generate a title slide (course title, semester, lecturers) and a table of the course's
  sessions (date, time, room) from the course's public data, in the deck's language, and insert them into the
  deck.
- **Courses that are on soon.** SlideMage renders the previews of a deck in the background; a deck whose course
  has a session within the next 7 days goes first.

**Privacy.** The plugin contacts only the CAMPUSonline server of a deck's course link, and only its public,
anonymous REST interface: no login, nothing about you or your decks is sent. It fetches a course only when you open
its Course tab or Admin slides, and keeps the session dates it got then in a file in SlideMage's cache folder; the
background renders read that file and never contact the server.

## Development

The plugin follows the [SlideMage plugin template](https://github.com/stpalan/slidemage-plugin-template) and the
[plugin conventions](https://slidemage.org/plugins/submit/).

`python build.py --check` checks the plugin against the catalogue's conventions: `plugin.toml`, the package and
its `activate(host)`, the imports, no compiled files, and a `CHANGELOG.md` entry for the version. The **Check**
workflow runs it on every push.

`python build.py` checks and then builds `dist/campusonline-<version>.smplugin` (a zip of `plugin.toml`,
`LICENSE` and the package) and its `.sha256`.

`python -m pytest` runs the tests; the Check workflow runs them too. The plugin package itself needs nothing
but the standard library (and `slidemage.plugin_api` and PySide6 once SlideMage runs it), so the pure tests run
anywhere. The tests that use `slidemage.plugin_api` (the FakeHost ones) are skipped where SlideMage is not
importable; run them with SlideMage's `src` on the path, for example
`PYTHONPATH=../SlideMage/src ../SlideMage/.venv/bin/python -m pytest`.

`docs/UGO_api.md` describes the CAMPUSonline endpoints the plugin uses and how they were found.

### Releasing a version

1. Raise `version` in `plugin.toml` and add a line to the end of `CHANGELOG.md`:
   `v1.2.0 (2026-11-02, reason): What changed.`
2. Commit, then tag and push: `git tag v1.2.0 && git push origin v1.2.0`.
3. The **Release** workflow checks that the tag matches the version, builds the asset and publishes the GitHub
   release with it.

A published version never changes: never replace or delete its asset; a fix is a new version.

## Licence

GPL-3.0-or-later, see `LICENSE`. The plugin comes with no warranty: to the extent permitted by applicable law, it is
provided "as is", without warranty of any kind, and the copyright holders are not liable for any damage arising from
its use (GPL-3.0 sections 15 and 16).
