#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env.local ]]; then
  echo ".env.local 파일이 없습니다. .env.local.example을 복사한 뒤 실행하세요." >&2
  exit 1
fi

docker compose --env-file .env.local -f docker-compose.local.yml up -d --build
