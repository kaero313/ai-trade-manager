#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env.local ]]; then
  set -a
  source .env.local
  set +a
fi

echo "[compose]"
docker compose --env-file .env.local -f docker-compose.local.yml ps

echo "[frontend]"
curl -fsS http://127.0.0.1:8080/ >/dev/null
echo "web ok"

echo "[backend]"
docker compose --env-file .env.local -f docker-compose.local.yml exec -T backend \
  python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/openapi.json', timeout=5).read()"
echo "backend ok"

echo "[postgres]"
docker compose --env-file .env.local -f docker-compose.local.yml exec -T db \
  pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-ai_trade_manager}"

echo "[opensearch]"
docker compose --env-file .env.local -f docker-compose.local.yml exec -T opensearch \
  sh -c "curl -fsS http://127.0.0.1:9200 >/dev/null"
echo "opensearch ok"
