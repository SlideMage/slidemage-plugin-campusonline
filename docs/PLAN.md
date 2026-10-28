# CampusOnline plugin: plan

Turning SlideMage's built-in CAMPUSonline features into the plugin `campusonline`, released through the
SlideMage plugin catalogue. Started from Stefan's handover (his `docs/PLUGINS_PLAN.md` and
`docs/Handover_2026-10-26-CampusOnline-Plugin.md`, which are not in any repository yet). Where things stand
now: [Handover_2026-10-27.md](Handover_2026-10-27.md).

The plugin is everything that talks to CAMPUSonline:

- a deck's **course link**, the preamble comment `%% SlideMage course URL: …`;
- the **admin slides**: a title slide and a course-sessions table from the course's public REST API;
- **"a session is soon"**: background renders give a deck priority when its course has a session within 7 days.

The deck group "Course deck" stays in SlideMage; the plugin only reads it.

Each step is one commit (or a few); work pauses after each one for review.

## Steps

| | Step | Status |
|---|---|---|
| 0a | History: the 13 paths of the feature (today's and earlier file names) filtered out of `stpalan/SlideMage` `develop` with git-filter-repo | done, `c9d719a` and before |
| 0b | Files moved into the plugin layout | done, `d1ef509` |
| 0c | The [plugin template](https://github.com/stpalan/slidemage-plugin-template) adopted: `plugin.toml`, `build.py`, Check and Release workflows, README, CHANGELOG | done, `14b57ec` |
| 1 | The package needs only the standard library; what needs SlideMage's internals is in `bridge/`; Check runs the tests | done, `b7c891e` |
| 2 | The host interface, drafted | done, `9d5a6b9` |
| 3 | The Course tab and the box | done, `df91066`; the box's title and sessions cached since `6922913` |
| 4 | Moving over the old schedule cache | done, `3d22a40` (`adopt_legacy_cache`, called in `activate()` with `host.legacy_cache_dir()`) |
| 5 | The real `slidemage.plugin_api` | waits for SlideMage |
| 6 | The public repository and 1.0.0 | waits for 5 |

### 2. The host interface, drafted

The plugin API doesn't exist yet: the template and `stpalan/slidemage-plugin-hello` have only an empty
`activate(host)`. This step writes down exactly what CampusOnline needs, so Stefan can build `plugin_api` to it.

- `campusonline/host.py`: a `typing.Protocol` `Host` with the calls below. It is documentation and a type
  for the tests, not an import of SlideMage, so the package stays pure.
- `tests/fake_host.py`: a `FakeHost` that records what is registered and does deck edits on files in a
  temporary folder.
- `activate(host)` registers everything and does no network or slow work (it runs at start).
- Tests of `activate()` against `FakeHost`: what is registered, the render priority, the menu entries'
  enabled checks.

The calls, mapped to what SlideMage `develop` already has, so the host can be thin:

| Call | What CampusOnline uses it for | Built on in SlideMage today |
|---|---|---|
| `cache_dir() -> Path` | `course_schedule.use_cache_folder()` | `project.cache_dir()` |
| `add_command(id, title, run, enabled=…)` | Admin slides…, Open course page | `ui/commands.py` `CommandRegistry`, `Command` |
| `add_menu_entry(menu, command_id)` | both in the Deck menu | `ui/workspace/menus.py` |
| `add_deck_settings_tab(title, build, footer_action=…)` | the Course tab with Insert slides | the tabs of `ui/dialogs/deck_settings.py` |
| `add_sidebar_box(key, title, build, size="compact", when=…)` | the box in the right column | `ui/workspace/panels/` `SidePanel`, `PANELS` |
| `add_render_priority(soon: Callable[[deck], bool])` | `session_soon(course URL)` | `BackgroundRenders(soon=…)` |
| `run_in_background(work, done)` | fetching a course off the UI thread | `ui/background.start_detached` |
| `insert_slides(deck, position, [(id_suffix, frame)], language)` | the admin slides | `bridge/insert.py` today |
| `insert_positions(deck)` | the Insert at choice | `deck_editor.slide_insert_positions` |
| `edit_deck_text(deck, change: Callable[[str], str])` | writing the course link (`course_link.course_url_text`) | `deck_editor.apply`, which refuses if the file changed meanwhile |
| `deck_language(deck) -> "de" \| "en"` | the slides' language | `transcript.deck_language_of` |
| `open_url(url)` | Open course page | `open_path.open_in_default_app` |
| a deck: `name`, `path`, `text`, `groups` | the course link, whether it is a Course deck | `deck_scan.Deck` |
| widgets: `Page`, `Field`, `caption` | the tab and the box look like SlideMage | `ui/kit/widgets.py` |

Deviations from the table, as built in `campusonline/host.py`:

- `legacy_cache_dir() -> Path | None` added (step 4).
- `open_deck_settings(deck, tab=None)` added: "Admin slides…" has to open the Deck settings sheet on the Course
  tab, as SlideMage's own `on_admin_slides` does.
- `add_deck_settings_tab`'s `footer_action` is a `FooterAction(label, run, enabled)`; `Page`, `Field` and
  `caption` are methods of the host (the widgets need SlideMage's Qt kit); `run`/`enabled`/`when` take the
  current `Deck` (`enabled` gets None when no deck is open).
- `run_in_background(work, done)`: `done(result, error)` on the UI thread. `add_render_priority`'s `soon` is
  documented as called on a worker thread, so it must be thread-safe and read only the cache.
- `edit_deck_text` returns the new text and raises `StaleFileError`; `insert_positions` returns
  `InsertPosition(label, insert_at, indent)`; the course group is the tag `"course"` in `Deck.groups`.

The handover's `add_deck_marker("course URL")` is replaced by `edit_deck_text` plus the plugin's own
`course_link`: a general text edit is smaller than a marker API and covers this case.

### 3. The Course tab and the box

- `campusonline/ui/deck_tab.py`: today's `bridge/deck_tab.py` (now deleted) plus the course link field with Open
  (now in SlideMage's General tab), built only from the host's widgets and calls. The sheet's footer button of
  the tab is "Insert slides", so the link has its own **"Save link" button** (also Return in the field); it
  writes through `edit_deck_text`. The deck is a snapshot, so after saving the tab says to reopen Deck settings
  instead of fetching a course it could not insert into (as today: save on General, then open Admin slides).
  The course is fetched with `run_in_background` when the tab is first shown; the footer action is
  `FooterAction("Insert slides", run=page.controller.insert, enabled=page.controller.can_insert)`, and the tab
  emits `changed` whenever the planned slides change.
- `campusonline/ui/box.py`: a compact box shown for a deck with a course link: course title, the next session,
  Open course page, Admin slides…. It shows the cached schedule and never fetches. What it says is worked out
  by `campusonline/course_box.py` (pure, tested without Qt). **The cache holds only the session dates**
  (`{course number: {fetched, dates}}`), so today the box shows "Course <number> at <host>" for the title and
  "Next session: Mon 12.10.2026" without time and room; with nothing cached it says to open the Course tab.
  `course_box` already shows `title` and `sessions` (`date`, `start`, `end`, `location`) if the cache entry has
  them: `course_schedule.remember_schedule` would have to store them (also the title from the course detail).
  The Course tab's fetch (`fetch_schedule`) already fills the cache.
  The box's weekday follows the deck's language (decision 2026-10-28: "Mo" for a German deck, "Mon" for English; the other words stay English). The group of the next session is not shown, because a course's groups usually have decks of their own.
- No change to `Host`. `course_box.cached_entry` uses `course_schedule`'s private `_cache_file` and
  `_course_number`; a public reader there would be cleaner.
- `tests/fake_host.py`: `Page`, `Field` and `caption` return real PySide6 widgets when PySide6 is installed.

### 4. Moving over the old schedule cache

SlideMage keeps the session dates in `course-schedules.json` in `project.cache_dir()`; the plugin gets its own
folder from `host.cache_dir()`. On activation, if the plugin's file is missing and the old one exists, copy it
once (cheap, local, allowed in `activate()`). Needs to know where SlideMage's folder is: ask Stefan for it in
the host (for example `host.legacy_cache_dir()`), or have SlideMage hand the file over itself.

### 5. The real `slidemage.plugin_api`

When SlideMage has the plugin host (Stefan's phases 0 and 1):

- replace `campusonline/host.py`'s Protocol with imports from `slidemage.plugin_api`;
- move what `bridge/` does onto host calls and delete `bridge/` and `tests/bridge/`;
- Check: tests against the oldest and newest SlideMage allowed by `requires_slidemage`;
- set `requires_slidemage` to the first SlideMage with the host.

### 6. The public repository and 1.0.0

The catalogue lists only a public repository registered in `stpalan/slidemage-website`
`registry/plugins.toml`, named `slidemage-plugin-<id>` by convention. So:

- create `JuergenFleiss/slidemage-plugin-campusonline` (public, issues open) and push this branch to its `main`;
- replace `website/icon.svg` (still the template's), add screenshots in `website/screenshots/`;
- date the 1.0.0 entry in `CHANGELOG.md`, tag `v1.0.0`; the Release workflow publishes the asset;
- a pull request to `registry/plugins.toml` (`releases = ["1.0.0"]`);
- release together with the first SlideMage without the built-in feature: the catalogue must list 1.0.0
  before that SlideMage ships, and that SlideMage removes the code (Stefan's side) and offers the plugin to
  projects whose decks have a course link.

Until then the feature stays in SlideMage. Changes to it go to SlideMage `develop` **and** here, so the two
copies don't drift.

## Open questions

For Jürgen (from Stefan's handover):

- Repository name and owner: `JuergenFleiss/slidemage-plugin-campusonline`?
- A Settings tab: anything to put there (a default CAMPUSonline instance, a cache time)? Today there is nothing
  that needs one.
- The box: anything else worth showing at a glance (lecturers, the group of the next session, the course
  number)?

For Stefan:

- The host calls of step 2: does the list fit his plan for `plugin_api`?
- `build.py --check` checks only absolute imports. A relative import out of the package
  (`from ..deck_editor import …`) passes the check and fails at load time; the check should refuse it.
- The PyInstaller build contains only the standard-library modules SlideMage itself imports. A plugin
  using another one fails only in the installed app. Either the build bundles a stated set, or `plugin_api`
  offers what plugins need (for example an HTTP GET helper, which could also handle proxies and certificates).
- Where the old schedule cache is (step 4).
- The handover's clone URL `github.com/JuergenFleiss/slidemage.git` doesn't exist; the repository is
  `stpalan/SlideMage`.
