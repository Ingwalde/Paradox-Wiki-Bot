# Security policy

A Discord bot that searches local read-only copies of the Paradox wikis. It holds
no user accounts and no passwords, but it does run with a Discord bot token, an
optional pdx.tools API key, and it accepts file uploads from anyone who can type
a command. If you find something wrong, please report it.

## Supported versions

Only the latest release is supported. Fixes land on `main` and ship in the next
version; there are no backports.

## Reporting a vulnerability

Use GitHub's private reporting: **[Security → Report a
vulnerability](https://github.com/Ingwalde/Paradox-Wiki-Bot/security/advisories/new)**.
That opens a private thread visible only to the maintainer, so the issue is not
public while it is being fixed.

Please do not open a public issue for anything exploitable.

Useful in a report, in rough order of usefulness:

- what an attacker gets — read or write files on the host, exfiltrate the bot
  token, act as the bot, deny service to a whole server;
- the smallest set of steps that reproduces it, including the exact command text;
- the version or commit you tested against.

Expect a first reply within a week. This is a solo project, so that is a
realistic estimate rather than an SLA.

## Scope

In scope: the bot package, `scripts/import_wiki.py`, the Docker and deployment
configuration, and the CI workflows in this repository.

Out of scope, because they are not this project's to fix:

- vulnerabilities in third-party dependencies with no bot-specific exploit path —
  report those upstream; Dependabot and pip-audit already watch this repository;
- anything requiring the attacker to already hold the bot token or shell access
  to the host;
- abuse that Discord's own rate limits and moderation tools exist to handle;
- denial of service by volume.

## What is already deliberate

Some behaviour that looks like a finding is a decision:

- **Search queries and Discord user IDs are stored.** `-trending` needs the
  query log and the ✅/❌ feedback needs to attribute a vote. Both live in
  PostgreSQL (the `search_log` and `feedback` tables), on an internal-only
  container network. There is no retention policy yet — that is tracked in
  [ROADMAP.md](ROADMAP.md), not a vulnerability report.
- **Uploads are read fully into memory**, capped at 25 MB, and never written to
  disk. That cap is the denial-of-service control, together with the one upload
  per minute per user cooldown.
- **The game data is read-only at runtime.** The bot never writes to the
  `pages`/`redirects` tables (they are seeded and refreshed offline), and the
  game key can only come from the `GAMES` registry, never from chat: every query
  is a parameterised `WHERE game_key = ...`, so command text cannot reach the
  database as SQL.
- **The Postgres port is not published.** The bot reaches the database over the
  compose network only; the password comes from `.env`, never hardcoded.
- **The keep-alive endpoint answers unauthenticated.** It returns a fixed string
  and no state; it exists for uptime monitoring.

## Handling secrets

`TOKEN`, `PDX_TOOLS_USER_ID` and `PDX_TOOLS_API_KEY` are read from the
environment and never logged. `.env` is gitignored, and `detect-private-key`
runs as a pre-commit hook. If a token is ever exposed, reset it in the Discord
Developer Portal — rotating is cheap and immediate.
