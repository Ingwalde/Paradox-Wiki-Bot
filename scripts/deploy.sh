#!/usr/bin/env bash
#
# Roll the running container onto a specific image, or fail loudly.
#
# Deliberately a committed script rather than inline workflow steps: the
# self-hosted Windows runner needs an explicitly chosen bash (see deploy.yml),
# and keeping the logic in a file means a Linux VPS runs exactly the same code
# with plain `bash scripts/deploy.sh`.
#
# Usage: DEPLOY_DIR=... IMAGE_TAG=sha-<commit> bash scripts/deploy.sh
set -euo pipefail

: "${DEPLOY_DIR:?DEPLOY_DIR is not set (see README > Деплой)}"
: "${IMAGE_TAG:?IMAGE_TAG is not set}"

IMAGE="ghcr.io/ingwalde/paradox-wiki-bot:${IMAGE_TAG}"
CONTAINER="paradox-wiki-bot"
HEALTH_TIMEOUT_SECONDS=90
DOCKER_TIMEOUT_SECONDS=180

fail() { echo "::error::$*"; exit 1; }

# The runner and the Docker engine both start at sign-in, and the runner wins:
# a deploy queued over a reboot reaches `docker compose pull` while the daemon
# is still coming up, and dies on "cannot find the file specified". Enabling
# Docker's autostart does not fix that -- it only guarantees the engine is
# starting, not that it has finished. So wait for it.
wait_for_docker() {
  local waited=0
  until docker info >/dev/null 2>&1; do
    [ "$waited" -ge "$DOCKER_TIMEOUT_SECONDS" ] &&
      fail "Docker engine not reachable after ${DOCKER_TIMEOUT_SECONDS}s. Is Docker Desktop running?"
    [ "$waited" -eq 0 ] && echo "Waiting for the Docker engine..."
    sleep 5
    waited=$((waited + 5))
  done
  [ "$waited" -gt 0 ] && echo "Docker engine ready after ${waited}s."
  return 0
}

wait_for_docker

[ -d "$DEPLOY_DIR" ] || fail "$DEPLOY_DIR does not exist. Create it and put .env there first."
[ -f "$DEPLOY_DIR/.env" ] || fail "No .env in $DEPLOY_DIR. The bot cannot start without TOKEN."

# Skip the copy when the deploy directory *is* the checkout -- `cp` errors out
# on "same file". That happens when the runner deploys into the working copy
# rather than a separate directory.
if [ "$(cd "$(dirname docker-compose.yml)" && pwd -P)" != "$(cd "$DEPLOY_DIR" && pwd -P)" ]; then
  cp docker-compose.yml "$DEPLOY_DIR/"
fi
cd "$DEPLOY_DIR"

echo "Deploying ${IMAGE}"

# A failed pull is NOT survivable: compose falls back to the locally cached
# image, the old container starts, and the health check below passes while
# nothing was actually deployed.
if ! docker compose pull; then
  fail "Could not pull ${IMAGE}. Refusing to restart -- that would relaunch the previous image and report a successful deploy for code that never shipped."
fi

docker compose up -d --remove-orphans

# Confirm the running container is the image just pulled, not a survivor of a
# failed recreate.
want=$(docker image inspect "$IMAGE" --format '{{.Id}}')
got=$(docker inspect --format '{{.Image}}' "$(docker compose ps -q paradox-bot)")
[ "$want" = "$got" ] || fail "paradox-bot is running $got but the pulled image is $want -- a recreate must have failed."
echo "Running image matches the pulled digest."

# start_period in the compose health check is 15s; allow well past it so a slow
# gateway connect is not reported as a failed deploy.
state=unknown
for _ in $(seq 1 $((HEALTH_TIMEOUT_SECONDS / 5))); do
  state=$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo unknown)
  [ "$state" = "healthy" ] && { echo "Healthy."; exit 0; }
  [ "$state" = "unhealthy" ] && break
  sleep 5
done

docker logs --tail 50 "$CONTAINER" || true
fail "Container did not become healthy within ${HEALTH_TIMEOUT_SECONDS}s (last state: ${state})."
