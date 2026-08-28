# Build stage — pip and the wheels it downloads stay here and never reach the
# runtime image. Keeps the shipped image smaller and cuts the CVE surface the
# Trivy scan in .github/workflows/ci.yml has to look at.
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime stage
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Apply Debian security updates on top of the base image. python:3.13-slim is
# rebuilt on its own schedule, so between rebuilds it ships OS packages with
# published fixes. The Trivy gate runs with ignore-unfixed, meaning only CVEs
# the project can actually act on fail the build; upgrading here is that action.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Only the installed packages come across — no pip cache, no build wheels.
COPY --from=builder /install /usr/local

# The base image's own build tooling is what Trivy flags, not our dependencies:
# CVE-2025-47273 in setuptools 70.3.0, and GHSA-6v7p-g79w-8964 in the msgpack
# copy vendored inside pip. Neither runs once the bot is started.
#
# setuptools is upgraded rather than removed because pkg_resources still gets
# imported by the occasional library. pip is deleted outright — nothing imports
# it at runtime, and deleting is what actually clears the vendored msgpack,
# which upgrading pip would not, since the latest release still vendors it.
# The glob means a base-image bump that moves the path removes nothing and
# Trivy fails again rather than passing on a false assumption.
RUN python -m pip install --no-cache-dir --upgrade "setuptools>=78.1.1" \
    && rm -rf /usr/local/lib/python3.*/site-packages/pip \
              /usr/local/lib/python3.*/site-packages/pip-*.dist-info \
              /usr/local/bin/pip /usr/local/bin/pip3*

COPY . .

# Writable state lives in Postgres now; only logs/ is written on the host.
# Fixed uid/gid 1000, not a system user: logs/ is bind-mounted from the host,
# and a bind mount keeps the host's ownership. A system account gets an
# arbitrary uid in the 100s, which then cannot write to a directory owned by
# the host's first non-root user — uid 1000 on Ubuntu, which is what Oracle
# Cloud and Hetzner images ship. Matching it means the mount just works.
RUN mkdir -p logs \
    && addgroup --gid 1000 botuser \
    && adduser --uid 1000 --gid 1000 --disabled-password --gecos "" botuser \
    && chown -R botuser:botuser /app

USER botuser

# Cosmetic only — publishing is docker-compose.yml's job. Documents the
# keep-alive/health port the app listens on.
EXPOSE 8080

# `exec` replaces the shell with the Python process (same PID) so SIGTERM from
# `docker stop` / `compose down` reaches it directly instead of being swallowed
# by dash. discord.py closes the gateway cleanly on that signal.
CMD ["sh", "-c", "exec python main.py"]
