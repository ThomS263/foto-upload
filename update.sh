#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
exec 9>.update.lock
flock -n 9 || exit 0
git pull --ff-only origin main
revision=$(git rev-parse HEAD)
if [[ -f .deployed-revision && "$(< .deployed-revision)" == "$revision" ]]; then
    exit 0
fi
docker compose up -d --build --wait --wait-timeout 180
printf '%s\n' "$revision" > .deployed-revision
