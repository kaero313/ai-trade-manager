# 로컬 Linux 상시 운영 가이드

AI-Trade-Manager는 공개 인터넷에 직접 노출하지 않고, 로컬 Linux PC와 Tailscale 사설망을 기준으로 운영합니다.

## 1. 운영 구조

| 구성 | 역할 |
|---|---|
| 웹 | 정적 웹 UI 제공, API 요청을 백엔드로 전달 |
| 백엔드 | FastAPI, 스케줄러, 매매 엔진, Slack/Telegram 실행 관리 |
| PostgreSQL | 운영 상태의 기준 저장소 |
| OpenSearch | RAG 뉴스 검색 캐시 |
| Tailscale | 외부 공개 없이 개인 기기 접근 |

backend는 단일 인스턴스로 운영합니다. 여러 개를 동시에 띄우면 스케줄러와 매매 루프가 중복 실행될 수 있습니다.

## 2. 최초 구성 체크리스트

1. Docker, Docker Compose, Tailscale, 방화벽 도구를 설치합니다.
2. 예제 환경 파일을 복사하고 실제 비밀값을 채웁니다.
3. 웹 UI용 기본 인증 계정과 관리 API 토큰을 설정합니다.
4. 컨테이너를 시작하고 데이터베이스 마이그레이션을 적용합니다.
5. 헬스체크로 web, backend, PostgreSQL, OpenSearch 상태를 확인합니다.

## 3. 접근 방식

- 웹 UI는 로컬 PC에서는 localhost 경로로 확인합니다.
- 원격 접속은 Tailscale 경로만 사용합니다.
- 일반 인터넷에 웹 UI, API, DB, OpenSearch 포트를 직접 열지 않습니다.

## 4. 인증 계층

| 계층 | 목적 |
|---|---|
| Caddy 기본 인증 | 웹 UI와 API 진입점 보호 |
| 관리자 API 토큰 | 설정 변경, 봇 제어, 수동 AI Cycle 같은 상태 변경 API 보호 |

관리자 API 토큰이 서버에 없으면 보호 API는 차단되어야 합니다.

## 방화벽 기준

기본 정책은 외부 유입 차단이다.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
sudo ufw status verbose
```

기본 Compose 설정은 web만 `127.0.0.1:8080`에 바인딩한다. 따라서 DB/API/OpenSearch는 호스트 외부에서 직접 접근할 수 없다. 운영 중에도 `5432`, `8000`, `9200`, `5601`은 일반 인터넷에 열지 않는다.

Tailscale serve가 아니라 Tailscale 인터페이스에 직접 포트를 열어야 하는 경우에만 다음처럼 제한적으로 허용한다.

```bash
sudo ufw allow in on tailscale0 to any port 8080 proto tcp
```

## systemd 자동 기동

레포지토리를 `/opt/ai-trade-manager`에 배치했다는 기준의 예시다. 다른 경로를 쓰면 `ops/systemd/ai-trade-manager.service`의 `WorkingDirectory`를 수정한다.

```bash
sudo cp ops/systemd/ai-trade-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ai-trade-manager
sudo systemctl start ai-trade-manager
sudo systemctl status ai-trade-manager
```

## 일상 운영 명령

```bash
./ops/scripts/healthcheck.sh
./ops/scripts/logs.sh backend
./ops/scripts/logs.sh web
./ops/scripts/restart.sh
./ops/scripts/stop.sh
```

로그는 장애 원인 추적을 위해 backend, web, db, opensearch 단위로 나누어 확인한다.

## 백업과 복구

PostgreSQL 백업:

```bash
./ops/scripts/backup_postgres.sh
```

복구 예시:

```bash
cat backups/postgres/ai_trade_manager_YYYYMMDD_HHMMSS.sql \
  | docker compose --env-file .env.local -f docker-compose.local.yml exec -T db \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

OpenSearch `market_news`는 재수집 가능한 캐시로 본다. 핵심 운영 상태와 주문/판단 로그는 PostgreSQL 백업을 우선한다.

## 안전 기본값

상시 운영 첫 단계는 실거래 자동화를 켜는 것이 아니라 관측 가능한 안전 운전으로 시작한다.

- `trading_mode=paper`
- `live_buy_enabled=false`
- `ai_entry_shadow_mode=true`
- BUY 후보는 shadow 로그로 먼저 검증한다.
- 며칠간 판단 로그, RAG/provider warning, paper 손익을 확인한 뒤 실거래 BUY 잠금을 수동 해제한다.

비상 정지는 웹 UI가 아니라 Slack/Telegram도 보조 채널로 둔다. 원격 접속이 안 되는 상황에서도 `/stop` 또는 비상 정지 버튼으로 봇을 멈출 수 있어야 한다.

## 장애 대응 체크리스트

1. `./ops/scripts/healthcheck.sh`로 web, backend, db, opensearch 상태를 확인한다.
2. `./ops/scripts/logs.sh backend`로 스케줄러, AI provider, 주문 게이트 로그를 확인한다.
3. 주문 위험이 있으면 Slack/Telegram `/stop` 또는 `./ops/scripts/stop.sh`를 먼저 실행한다.
4. DB 장애는 PostgreSQL 백업 기준으로 복구하고, OpenSearch 뉴스 캐시는 재수집한다.
5. 외부 접속 문제는 Tailscale 상태와 UFW 정책을 먼저 본다.

## 검증 기준

```bash
docker compose --env-file .env.local -f docker-compose.local.yml config
docker compose --env-file .env.local -f docker-compose.local.yml ps
./ops/scripts/healthcheck.sh
```

`docker compose config`는 `.env.local`의 secret 값을 치환해 출력할 수 있다. 로그나 캡처에 남기지 말고, 외부 공유가 필요한 경우 key 값을 마스킹한 뒤 사용한다.

운영 검증은 다음을 포함한다.

- 로컬 PC에서 `http://127.0.0.1:8080` 접속
- 핸드폰 Tailscale 경로에서 웹 UI 접속
- `/api` reverse proxy 정상 동작
- `alembic upgrade head` 완료
- PostgreSQL dump 생성
- Slack/Telegram 비상 정지 동작
- 일반 외부망 기준 DB/API/OpenSearch 포트 미노출
