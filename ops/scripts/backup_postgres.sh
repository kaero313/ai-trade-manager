#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env.local ]]; then
  echo ".env.local 파일이 없습니다. .env.local.example을 복사한 뒤 실행하세요." >&2
  exit 1
fi

set -a
source .env.local
set +a

BACKUP_DIR="${ROOT_DIR}/backups/postgres"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/ai_trade_manager_${TIMESTAMP}.sql"

mkdir -p "$BACKUP_DIR"

docker compose --env-file .env.local -f docker-compose.local.yml exec -T db \
  pg_dump -U "${POSTGRES_USER:-postgres}" "${POSTGRES_DB:-ai_trade_manager}" > "$BACKUP_FILE"

echo "PostgreSQL 백업 생성: ${BACKUP_FILE}"
