"""Generate databases/seed.sql.gz from the current game data in Postgres.

The official postgres image runs everything in docker-entrypoint-initdb.d on a
fresh data volume and understands .sql.gz, so this dump is how the read-only
game data (the `pages` and `redirects` tables) ships without the old per-game
.db files. Regenerate it whenever scripts/import_wiki.py changes a game:

    python scripts/dump_seed.py

The database URL comes from the environment (see paradox_bot.config); pg_dump
must be on PATH.
"""

from __future__ import annotations

import gzip
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paradox_bot.config import settings

SEED = Path(__file__).resolve().parent.parent / "databases" / "seed.sql.gz"


def _libpq_url() -> str:
    """pg_dump speaks libpq, not asyncpg: drop the +asyncpg driver suffix."""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def main() -> None:
    cmd = [
        "pg_dump",
        "--no-owner",
        "--no-privileges",
        "--table=public.pages",
        "--table=public.redirects",
        "--dbname",
        _libpq_url(),
    ]
    print(f"Dumping pages + redirects to {SEED} ...")
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    SEED.parent.mkdir(exist_ok=True)
    with gzip.open(SEED, "wt", encoding="utf-8") as handle:
        handle.write(result.stdout)
    print(f"Wrote {SEED} ({SEED.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
