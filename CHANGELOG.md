# CampusOnline release history

v1.0.0 (2026-10-29, first release): The CAMPUSonline features that were built into SlideMage up to 8.x, as a plugin, built on SlideMage's plugin API 1: a deck's course link, the admin slides (a title slide and a course-sessions table from the course's public data), and earlier background renders for a deck whose course has a session within 7 days.

v1.0.1 (2026-10-30, SlideMage names): The course-sessions table works with SlideMage's own theme: from the SlideMage release that renamed the table environment, the admin slides use SMTable, and gothamtable with the releases before. The plugin reads the name from SlideMage's plugin API, TABLE_ENVIRONMENT, and uses gothamtable when the API does not have it.
