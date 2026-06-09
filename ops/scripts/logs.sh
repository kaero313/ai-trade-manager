#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE="${1:-backend}"

cd "$ROOT_DIR"
docker compose --env-file .env.local -f docker-compose.local.yml logs -f "$SERVICE"
