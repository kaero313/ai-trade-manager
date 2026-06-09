# 로컬 Linux 상시 운영 가이드

이 문서는 AI-Trade-Manager를 클라우드가 아닌 로컬 Linux PC에서 상시 운영하기 위한 절차를 정리한다. 웹 화면은 공개 인터넷에 노출하지 않고, Tailscale 사설망을 통해 본인 기기에서만 접근하는 구성을 기본값으로 둔다.

## 운영 구조

로컬 운영은 `docker-compose.local.yml` 하나로 관리한다.

- `backend`: FastAPI, Scheduler, Trading Engine, Slack/Telegram lifecycle을 함께 실행한다.
- `web`: Vite build 결과물을 Caddy가 정적 서빙하고 `/api`를 backend로 프록시한다.
- `db`: PostgreSQL 16. 모든 운영 상태의 SSOT다.
- `opensearch`: RAG 뉴스 검색과 임베딩 캐시를 담당한다.

backend는 반드시 단일 인스턴스로만 운영한다. FastAPI lifespan에서 스케줄러, 트레이딩 엔진, 메신저 봇이 함께 기동되므로 복수 인스턴스는 중복 주문과 중복 스케줄 실행 위험을 만든다.

## 최초 구성

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin tailscale ufw
sudo usermod -aG docker "$USER"
newgrp docker
```

```bash
cp .env.local.example .env.local
chmod +x ops/scripts/*.sh
```

`.env.local`에는 API key와 Slack/Telegram 토큰만 실제 값으로 채운다. Upbit 키는 paper/shadow 검증 전에는 비워두는 편이 안전하다.
운영 UI와 관리 API 보호를 위해 아래 값도 반드시 채운다.

```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext '원하는-비밀번호'
```

- `ADMIN_BASIC_AUTH_USER`: 웹 UI 접속용 Basic Auth 사용자명
- `ADMIN_BASIC_AUTH_HASH`: 위 명령으로 생성한 Caddy용 비밀번호 hash
- `ADMIN_API_TOKEN`: 설정 변경, 봇 제어, 수동 AI Cycle 같은 관리 API 호출용 긴 랜덤 토큰

```bash
./ops/scripts/start.sh
docker compose --env-file .env.local -f docker-compose.local.yml exec backend alembic upgrade head
./ops/scripts/healthcheck.sh
```

웹 UI는 로컬 PC에서 `http://127.0.0.1:8080`으로 확인한다.

## Tailscale 접근

공인 IP 포트포워딩은 사용하지 않는다. Linux PC와 핸드폰을 같은 tailnet에 등록한 뒤 Tailscale 경로로만 접근한다.

```bash
sudo tailscale up
tailscale serve --bg http://127.0.0.1:8080
tailscale serve status
```

핸드폰에서는 Tailscale 앱을 켠 뒤 `tailscale serve status`에 표시되는 HTTPS 주소로 접속한다. Basic Auth와 관리 API 토큰이 있어도 공개 인터넷용 로그인 시스템은 아니므로, 웹 UI를 일반 인터넷에 직접 공개하면 안 된다.

## 운영 인증 계층

로컬 운영 인증은 두 겹으로 둔다.

1. **Caddy Basic Auth**
   - 웹 UI와 `/api` reverse proxy 진입점 전체를 잠근다.
   - Tailscale 내부망이라도 브라우저 접속 시 사용자명/비밀번호를 먼저 요구한다.
2. **FastAPI `ADMIN_API_TOKEN`**
   - 설정 변경, 봇 시작/정지, 전량 매도, 수동 AI Cycle, paper reset 같은 상태 변경 API를 한 번 더 잠근다.
   - 프론트엔드는 최초 관리 작업 시 입력한 토큰을 `sessionStorage`에만 보관한다.

읽기 API는 관측 편의성을 위해 별도 토큰 없이 유지하지만, 웹 진입점은 Basic Auth 뒤에 있어야 한다.
`ADMIN_API_TOKEN`이 서버에 설정되지 않으면 보호 API는 `503`으로 차단된다.

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
