# Changelog

All notable changes to this project will be documented in this file.

---

## [Unreleased]

### Fixed
- `-tools` no longer gzips a save that is already compressed. `prepare_save_payload`
  recognised zip archives and passed them through, but everything else was
  gzipped unconditionally — so a `.gz` upload went to pdx.tools as a gzip stream
  that unpacks into another gzip stream, sent as `Content-Type: application/gzip`.
  It now checks for the gzip magic bytes as well.

### Changed
- One ✅/❌ vote per user per result message. `Feedback` gained a `message_id`
  column and a unique index on `(message_id, user_id)`, and `record_feedback`
  upserts: toggling a reaction off and on no longer writes a row per toggle, and
  changing ✅ to ❌ replaces the earlier vote instead of recording both. Anyone
  could previously inflate `/admin feedback` — and any measurement of search
  quality built on that table — from a single message.
  - `storage.connect()` takes an optional `migrate` callable for exactly this:
    `CREATE TABLE IF NOT EXISTS` does nothing to a database that already has the
    table, so a column added after the file first shipped has to be applied
    explicitly. Rows written before the column existed keep `message_id` NULL,
    which SQLite treats as distinct in a unique index — they stay
    un-deduplicated rather than colliding.
  - `recent_feedback` orders by `timestamp` before `id`, so a changed vote
    surfaces as recent rather than staying in its original position.
- Layered the package so dependencies point one way. `bot.py` was 444 lines
  holding three unrelated concerns; it is now 159 and contains one class.
  - `ui/views.py` + `ui/text.py` — presentation. Imports config and games,
    never the bot. `pluralize_results` moved here from `feedback.py`, where a
    Ukrainian string helper had no business living.
  - `search_flow.py` — the search use-case (`perform_search`, `log_request`),
    previously free functions in `bot.py` that took the bot as an argument.
  - `search_context.py` — the in-memory message→query correlation the ✅/❌
    handler needs, split from `feedback.py`. Two different lifetimes were
    sharing a module: one survives restarts, one does not.
  - `feedback.py` — vote persistence only.
- Broke the `bot.py` ↔ `cogs/admin.py` import cycle. `admin.py` imported
  `ParadoxBot` for a type hint while `bot.py` registers that cog, and the loop
  was only survivable because `bot.py` imported its cogs *inside*
  `setup_hook()`. `admin.py` now types against a `BotStatus` Protocol naming
  the three members it actually reads, so `bot.py` imports its cogs at module
  level like any other module.
- Stopped importing private names across module boundaries: `bot.py` was
  pulling `_pluralize_results`, `_search_context` and `_remember_search_context`
  out of `feedback.py`. The replacements are public API on the modules that own
  them.

Coverage 80% → 81%, and the split makes the untested surface honest: the
Discord-coupled parts are now visibly `search_flow.py` (21%) and `bot.py`
(47%) instead of being averaged into one large file.

### Added
- Tests for `search_flow.py`, 21% → 99%. Every branch of `perform_search` and
  `log_request` is reachable without a gateway connection — results found and
  not found, fuzzy suggestions, an over-long query, a failing search, stats
  write, suggestion lookup, reaction and log-channel send — and none of it was
  covered. Coverage 81% → 91%, gate 78% → 88%.

## [0.2.1] - 2026-08-21

Test coverage for the command layer, a gate to keep it, and an end to the
deploy-failure emails.

### Added
- Tests for every cog — 41 new cases, coverage of `paradox_bot/cogs/` from 0%
  to 94–100% and the suite overall from 53% to 80%. The command layer was the
  least-tested and highest-risk part of the bot: `-tools` alone branches into
  timeout, oversized file, unreadable attachment, API rejection, duplicate
  save (with and without a recorded link), an unexpected error, and a
  bookkeeping failure that must *not* hide a successful upload. Each branch is
  now asserted on what the user actually sees.
- `fail_under = 78` in the coverage config, so an accidental drop fails CI.
  Just under the 80% reached today; the remaining gap is `bot.py`'s event
  handlers and direct Discord calls, which stay untested on purpose.
- Fakes in `tests/conftest.py` (`FakeContext`, `FakeSendable`,
  `FakeInteraction`) that record what would have been sent. `FakeSendable`
  subclasses `discord.abc.Messageable` — a plain mixin, not an ABC — so the
  daily-fact loop's isinstance guard admits it. No mocking of the Discord
  client, gateway or HTTP layer.

### Fixed
- The Deploy workflow no longer fails on every push. With no server
  configured it died at the scp step (`can't connect without a private SSH
  key or password`) and GitHub mailed a failure notice each time, for a
  workflow that could not have worked. It now skips unless
  `DEPLOY_ENABLED=true` is set as a repository variable — a variable rather
  than a secret because job-level `if:` only sees `github`/`needs`/`vars`/
  `inputs`. README documents the three secrets and the variable together.
- The cog tests no longer depend on the developer's `.env`. `ExtrasCog`
  starts its task loop when `DAILY_FACT_CHANNEL_ID` is set, which needs a
  running event loop — so a machine with that variable configured failed
  tests that passed in CI.

### Changed
- Dependabot targets a long-lived `deps` branch instead of main, matching the
  other repositories here. Routine churn collects there and reaches main as
  one deliberate merge. Two costs are documented in `dependabot.yml`: `deps`
  drifts from main and needs a merge after any release touching a manifest,
  and `target-branch` applies to version updates only — security updates
  still go straight to the default branch, which is the behaviour you want.

## [0.2.0] - 2026-08-20

The bot now runs correctly as a container: it survives restarts, reports its
health honestly, and no longer loses data when it is stopped.

### Added
- Graceful shutdown. `docker stop` sends SIGTERM and kills the process nine
  seconds later, and deploys restart the container on every merge. `main.py`
  now installs SIGINT/SIGTERM handlers that close the bot, so `start()`
  returns and cleanup runs instead of the process dying where it stands —
  possibly mid-write to SQLite. Verified by signalling a running instance:
  the gateway closes, the health port is released, and the double `close()`
  (signal handler plus `async with`) is absorbed idempotently.
- `paradox_bot/storage.py`: one connection helper for the three writable
  databases, enabling `journal_mode=WAL` with `synchronous=NORMAL`. WAL is
  what makes an abrupt SIGKILL recoverable; the previous rollback journal was
  not. It also applies each schema once per file per process rather than
  running `CREATE TABLE IF NOT EXISTS` on every single write.
- `interaction_check` on the results view: only whoever ran the search can page
  through it. Anyone in the channel could previously advance someone else's
  results and change the message under them.
- `on_timeout` on the results view: the navigation buttons are disabled and the
  message edited once the view expires. Discord does not retire components on
  its own, so they used to keep rendering as clickable and answer "interaction
  failed". Link buttons are left alone — they carry a url and were never
  interactive.
- `view_timeout_seconds` in settings, replacing a literal 300.
- Docker: `deploy/Dockerfile` (multi-stage, non-root, security-updated base),
  `docker-compose.yml` with a health check, and `.dockerignore`. Matches the
  containerisation used in the other repositories here.
- `.github/workflows/deploy.yml`: SSH deploy triggered by a successful CI run
  on main. Deploys by `sha-<commit>` rather than `:latest`, refuses to continue
  when the image pull fails, and verifies the running container matches the
  pulled digest afterwards.
- CI gained a `pip-audit` gate, `scripts/check_env_example.py`,
  `scripts/check_version_sync.py`, and an image build scanned by Trivy.
  Pull requests build and scan without publishing; only main pushes to GHCR.
- `SECURITY.md` and `.gitattributes`.
- `.github/dependabot.yml` covering pip, github-actions and pre-commit, with
  minor and patch updates grouped into one PR.
- `DATA_DIR` controls where the runtime SQLite files live, so a container can
  mount one volume and keep uploads, feedback and stats across a redeploy.
  Previously those paths were fixed relative to the working directory, which
  would have silently wiped them on every deploy.

### Changed
- The keep-alive endpoint moved from Flask in a background thread to aiohttp in
  the bot's own event loop. The Docker health check polls this endpoint, and a
  separate thread kept answering 200 while the event loop was wedged — healthy
  for a bot that had stopped responding to Discord. Sharing the loop makes an
  unanswered request mean what the health check assumes it means.
- Flask dropped from the dependencies. It pulled in six transitive packages
  (werkzeug, jinja2, click, itsdangerous, markupsafe, blinker) to serve one
  route returning a fixed string, and `aiohttp` was already a dependency for
  the pdx.tools upload.
- Python 3.13 in CI and in the image, up from 3.11. Verified: ruff, mypy and
  all 79 tests pass on 3.13.
- `ruff` and `mypy` are pinned exactly in `requirements-dev.txt`. They are also
  pinned by rev in `.pre-commit-config.yaml`, and the two had already drifted —
  pre-commit ran mypy 1.14.1 while CI resolved 1.20.2, so a hook could pass
  locally and fail in CI.
- `BOT_PREFIX` and `DATA_DIR` documented in `.env.example`; the new gate fails
  the build if that drifts again.

### Removed
- `.replit`. The bot deploys to a VPS by container now; a request-driven
  platform cannot host a process that holds a gateway connection and never
  receives inbound HTTP. An intermediate step had corrected its stale
  `replit.nix` reference and documented the Reserved VM requirement; moving to
  containers made the whole file redundant.
- `scripts/add_search_indexes.py`. Its expression indexes were never used:
  the search filters with `LIKE '%query%'`, whose leading wildcard no B-tree
  can serve. Query plans with and without them are identical (`SCAN Pages`),
  timings match, and they added ~217 KB to `eu4.db`. See ROADMAP.md for the
  stored-column approach that would make indexing work.
- `write_pid()` and the `WIKI.pid` file it wrote. Nothing read it — a leftover
  from the earlier Replit setup.
- `IMPLEMENTATION_PROMPT.md`, superseded by this changelog and ROADMAP.md.

### Fixed
- Commands now resolve regardless of case. `-EU4` raised `CommandNotFound`,
  which the handler swallows by design, so anything but lowercase looked like
  a dead bot.
- Rate limiting actually exists. `on_command_error` had a `CommandOnCooldown`
  branch but no command carried a cooldown, so the branch was unreachable and
  one user could stream 25 MB uploads back to back. Per-game commands,
  `-random` and `-trending` allow 4 uses / 10 s; `-tools` allows 1 / 60 s and
  carries `max_concurrency` so a single user cannot hold several `wait_for`
  sessions open at once.
- Result links can no longer overflow Discord's 1024-character embed field
  and fail the message with 400. Unreachable with today's data (the worst
  real query renders 737 characters) but the theoretical worst case is 1131
  for stl and 1076 for hoi4.

## [0.1.0] - 2026-08-19

### Added
- `paradox_bot/` package: the bot split out of one `main.py` into
  `config.py` (typed `Settings` dataclass), `games.py` (`GameInfo` registry,
  single source of truth for game key → wiki subdomain, replacing two
  drifting dicts), `search.py`, `pdx_tools.py`, `feedback.py`, `stats.py`,
  `bot.py`, `web.py`, and `cogs/` (`tools`, `help`, `admin`, `extras`).
  `main.py` is now a thin entrypoint.
- `Redirects` table is searched alongside `Pages` (was collected but never
  read). Results ranked exact → prefix → contains, ties broken by title
  length.
- Fuzzy "did you mean" suggestions (`difflib`) when a search finds nothing.
- Result pagination: ◀/▶ buttons once a search has more than one page of
  results (was hard-capped at 7 with no way to see the rest).
- `-random <гра>`, `-trending <гра>`.
- ✅/❌ reactions on search results now persist votes (`Feedback` table) and
  are queryable — previously added but with no handler at all.
- `/admin status`, `/admin feedback` — Discord-native admin-gated
  (`default_permissions(administrator=True)`) slash commands. First use of
  `app_commands` in the project; regular commands stay prefix-based
  (`message_content` intent kept on purpose — see Known limitations).
- Optional daily "fact of the day" auto-post (`DAILY_FACT_CHANNEL_ID`,
  `discord.ext.tasks`, 12:00 UTC).
- Europa Universalis 5 support, plus `scripts/import_wiki.py`: populates a
  game's database from the paradoxwikis.com MediaWiki Action API (no key
  needed). Reusable for any future game in `GAMES`.
- Test suite (65 tests, pytest) covering every pure function; `-tools`
  upload tested against a real local `aiohttp` server (auth, headers, byte-
  for-byte body). GitHub Actions CI runs ruff + mypy + pytest.
- mypy (gradual/pragmatic config) and pre-commit (ruff, mypy,
  `detect-private-key`, `check-added-large-files` — the class of mistake
  that put a 12 MB save file in git once already, see 0.0.2).
- `LICENSE` (MIT) — the project had none before.

### Fixed
- pdx.tools upload: save URL was missing the `/eu4/` game segment
  (`/saves/{id}` → `/eu4/saves/{id}`, confirmed against
  `https://pdx.tools/docs/api/` — the docs only document EU4), and
  `Content-Type` was always `application/octet-stream` instead of
  `application/zip` for zip payloads.
- Duplicate `-tools` uploads ("save already exists") now resolve to the
  previously-recorded link instead of surfacing pdx.tools' raw JSON error.

### Changed
- Search result field no longer repeats the top result a second time (it's
  already the embed title); footer shows the result count.

## [0.0.2] - date not recorded

### Fixed
- Command argument injection: the game key was accepted from chat and could
  reach the database file path. Now bound by closure in
  `register_game_commands()`, never user input.

### Added
- Real pdx.tools upload (previously a fabricated URL).
- Repo hygiene: removed a 12 MB save file, `pdx_tools.db`, and `WIKI.pid`
  from git; added `.env.example` and this project's first README.

## [0.0.1] - date not recorded

Initial working version: SQLite-backed wiki search, one command per game.

[0.1.0]: https://github.com/Ingwalde/Paradox-Discord-Bot/compare/v0.0.2...v0.1.0
[0.0.2]: https://github.com/Ingwalde/Paradox-Discord-Bot/compare/v0.0.1...v0.0.2
