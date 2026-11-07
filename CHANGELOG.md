# CampusOnline release history

v1.0.0 (2026-10-29, first release): The CAMPUSonline features that were built into SlideMage up to 8.x, as a plugin, built on SlideMage's plugin API 1: a deck's course link, the admin slides (a title slide and a course-sessions table from the course's public data), and earlier background renders for a deck whose course has a session within 7 days.

v1.0.1 (2026-10-30, SlideMage names): The course-sessions table works with SlideMage's own theme: from the SlideMage release that renamed the table environment, the admin slides use SMTable, and gothamtable with the releases before. The plugin reads the name from SlideMage's plugin API, TABLE_ENVIRONMENT, and uses gothamtable when the API does not have it.

v1.0.2 (2026-11-02, decks in any language): A deck in a language other than German or English (SlideMage from v0.13.31 reports a French deck as fr) gets the English wording everywhere: the sessions table's headings, title and translated sessions, and the course title and semester in English where the course system has them; before, the table fell back to German and kept the German sessions.

v1.0.3 (2026-11-07, SlideMage's spacing, with SlideMage v0.14.36): The lecturer list's gap comes from the theme's spacing steps instead of a fixed number; it looks the same. Requires SlideMage v0.14.36.
