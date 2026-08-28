"""Prometheus metrics for what the bot already does.

Exposed at /metrics on the same aiohttp app as /health (see paradox_bot.web) --
deliberately not prometheus_client.start_http_server on a separate thread. That
thread would keep answering 200 for a bot whose event loop has wedged, which is
the exact failure web.py exists to make visible; the metrics endpoint lives on
the bot's own loop for the same reason.

Only things that exist today are measured: searches, empty results, votes,
uploads by outcome, database errors, and search latency. No circuit-breaker or
live-API metrics -- those features do not exist yet.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

SEARCHES = Counter(
    "paradox_searches_total", "Wiki searches performed", ["game"]
)
EMPTY_RESULTS = Counter(
    "paradox_empty_results_total", "Searches that returned no results", ["game"]
)
VOTES = Counter(
    "paradox_votes_total", "Feedback votes recorded", ["vote"]
)
UPLOADS = Counter(
    "paradox_uploads_total",
    "pdx.tools uploads by outcome",
    ["outcome"],  # success | duplicate | api_error
)
DB_ERRORS = Counter(
    "paradox_db_errors_total",
    "StorageError occurrences by operation",
    ["operation"],  # search | suggest | stats | feedback | upload
)
SEARCH_DURATION = Histogram(
    "paradox_search_duration_seconds", "Latency of search_pages"
)
