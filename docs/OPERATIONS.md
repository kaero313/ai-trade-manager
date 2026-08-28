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
3. 웹 UI용 기본 인증 계정, 관리 API 토큰, 별도의 관리자 재인증 서명 secret과 요청 제한 subject secret을 설정합니다. Telegram을 사용한다면 bot token, 허용 chat ID, 허용 user ID도 모두 설정합니다.
4. 컨테이너를 시작합니다. 로컬·개발 Compose는 `migrate` one-shot 서비스가 `alembic upgrade head`를
   성공적으로 완료한 뒤에만 backend를 시작하므로 마이그레이션을 수동으로 먼저 적용할 필요가 없습니다.
   `migrate`가 실패하면 backend는 시작되지 않습니다.
5. 공개 `GET /api/health`를 사용하는 backend 헬스체크로 web, backend, PostgreSQL, OpenSearch 상태를 확인합니다.
6. `paper + inactive + BLOCK_ALL`, `live_order_v2_enabled=false` 상태에서 거래 모드·주문 원장·reconciliation 상태 API를 먼저 확인합니다.
7. 실주문 제출용 DB 연결이 direct connection 또는 session pooling인지 확인합니다. transaction pooling 방식의 PgBouncer는 사용하지 않습니다.

## 3. 접근 방식

- 웹 UI는 로컬 PC에서는 localhost 경로로 확인합니다.
- 원격 접속은 Tailscale 경로만 사용합니다.
- 일반 인터넷에 웹 UI, API, DB, OpenSearch 포트를 직접 열지 않습니다.

## 4. 인증 계층

| 계층 | 목적 |
|---|---|
| Caddy 기본 인증 | 웹 UI와 API 진입점 보호 |
| 관리자 API 토큰 | 공개 GET allowlist를 제외한 계좌·주문·설정·채팅·AI·백테스트 등 애플리케이션 API 보호 |

인증 없이 허용되는 범위는 `GET /api/health`, 전체 공개 market GET, 일반 뉴스 목록
`GET /api/news/`뿐입니다. 계좌·주문·포트폴리오, 관심종목, 설정, 채팅, AI/LLM 비용 작업, 백테스트와
봇 제어를 포함한 나머지 API는 관리자 토큰을 요구합니다. 관리자 API 토큰이 서버에 없으면 보호 API는
`503`으로 fail-closed 처리됩니다.

React는 앱 진입 시 `AdminSessionGate`에서 저장하거나 입력한 토큰을 `GET /api/admin/session`으로 먼저
검증합니다. 검증 전에는 기존 layout과 민감 query를 mount하지 않습니다. 취소, 서버의 토큰 미설정,
잘못된 토큰은 잠금 화면에 남기며 운영자가 직접 다시 시도해야 합니다. 일반 API client와 raw chat SSE는
모두 `X-Admin-Token`을 전송하고, 현재 토큰에 대한 `401/403` 응답을 받으면 저장 토큰을 폐기하고 민감
화면을 즉시 unmount합니다. 늦은 이전 요청이 새 토큰을 지우지는 않습니다. 설정 화면의 수동 토큰
초기화도 같은 잠금 경계를 사용합니다. 이 앱 진입 검증은 live 전환의 별도 재인증 proof를 대체하지
않습니다. FastAPI 자동 `/docs`, `/redoc`, `/openapi.json`은 기본 비활성화되어 `404`를 반환합니다.

Slack 연결 테스트 `POST /api/slack/test`는 `ADMIN_API_TOKEN` 인증과 서버의 `SLACK_WEBHOOK_URL`을
모두 요구합니다. 요청 body에는 `text`, `username`, `icon_emoji`만 사용할 수 있고 `webhook_url`을
포함한 알 수 없는 필드는 `422`로 거부됩니다. Slack 미설정은 `503`, 전송 실패는 외부 오류 상세를
숨긴 고정 `502`입니다. webhook URL이나 외부 예외 원문을 로그에 남기지 않습니다.
또한 `httpx`와 `httpcore`의 INFO/DEBUG 요청 로그는 전역적으로 억제해 Slack·Telegram 등 URL과 헤더에
포함될 수 있는 인증 정보가 파일·stderr에 기록되지 않게 합니다.

### 4.1 PostgreSQL 공유 요청 제한

모든 API route는 코드에 고정된 비용·위험 policy 하나에 매핑됩니다. 분류되지 않은 route는 허용하지
않으며 PostgreSQL fixed-window 원장에서 다중 worker가 같은 카운터를 공유합니다.

| policy | 고정 principal | fixed-window 제한 |
|---|---|---:|
| `PUBLIC_MARKET_READ` | `public:global` | 60초당 120회 |
| `PUBLIC_NEWS_READ` | `public:global` | 60초당 12회 |
| `ADMIN_DB_READ` | `admin:primary` | 60초당 600회 |
| `ADMIN_EXTERNAL_READ` | `admin:primary` | 60초당 120회 |
| `EXPENSIVE_ACTION` | `admin:primary` | 300초당 20회 |
| `STATE_MUTATION` | `admin:primary` | 60초당 60회 |
| `SAFETY_STOP` | `admin:primary` | 60초당 600회 |
| `AUTH_FAILURE` | `auth-failure:global` | 300초당 10회 |
| `HEALTH_EXEMPT` | 저장하지 않음 | 제한 면제 |

`POST /api/bot/stop`, `POST /api/bot/trading-mode/paper`, `POST /api/bot/order-gate/block`은
일반 상태 변경 제한과 분리된 `SAFETY_STOP` 용량을 사용합니다. 이는 무제한 우회가 아니라 안전을
강화하는 제어가 일반 mutation에 의해 고갈되지 않도록 분리한 bucket입니다. `GET /api/health`는 요청
제한을 적용하지 않고 PostgreSQL readiness를 계속 보고합니다.

제한을 초과하면 `429 RATE_LIMIT_EXCEEDED`와 정수 `Retry-After`를 반환합니다. 유효한 관리자 요청이나
공개 market·뉴스 요청에서 PostgreSQL 제한 상태를 확정하지 못하거나 route가 분류되지 않았으면 외부
호출·상태 변경 전에 `503 RATE_LIMIT_UNAVAILABLE`로 fail-closed합니다. 잘못되거나 누락된 관리자
credential은 제한 DB 장애가 나더라도 기존 `401/403` 거절을 유지합니다.

`RATE_LIMIT_SUBJECT_SECRET`은 최소 32바이트의 독립 비밀값으로 생성하고 `ADMIN_API_TOKEN`이나
`ADMIN_REAUTH_SIGNING_SECRET`을 재사용하지 않습니다.

```dotenv
RATE_LIMIT_SUBJECT_SECRET=<독립적으로 생성한 32바이트 이상의 secret>
```

DB에는 고정 principal을 이 secret으로 HMAC-SHA256한 subject hash만 저장합니다. raw 관리자 토큰,
Telegram user ID, client IP, header, URL path, query는 요청 제한 원장이나 제한 오류 로그에 기록하지
않습니다.

### 4.2 CORS와 개발 포트

`CORS_ALLOWED_ORIGINS`에는 브라우저 접근을 허용할 정확한 HTTP(S) origin을 쉼표로 구분해 설정합니다.
wildcard `*`, user info, 루트 `/` 외 경로, query, fragment 또는 잘못된 port가 포함된 값은 시작 단계에서
거부됩니다.
CORS credential 전송은 허용하지 않으며 허용 header는 필요한 인증·멱등 header로 제한됩니다.

```dotenv
CORS_ALLOWED_ORIGINS=https://trade.example.internal,http://127.0.0.1:5173
```

개발 Compose가 publish하는 frontend, backend, PostgreSQL, OpenSearch, Dashboards 포트는 모두
`127.0.0.1`에만 바인딩합니다. `start_dev.bat`으로 실행하는 native backend도 `127.0.0.1`만 listen합니다.
LAN 또는 공용 인터페이스 접근이 필요하다는 이유로 이를 `0.0.0.0`으로 바꾸지 말고 Tailscale/Caddy
진입점에서 별도로 보호합니다.

로컬 Compose의 backend healthcheck는 공개 `http://127.0.0.1:8000/api/health`를 사용합니다.
FastAPI 자동 `/openapi.json`은 비활성화되어 있으므로 healthcheck 대상으로 되돌리지 않습니다.

로컬·개발 Compose 모두 `migrate` one-shot 서비스(`alembic upgrade head`)가 PostgreSQL healthcheck
통과 후 실행되고, backend는 `service_completed_successfully` 조건으로 그 완료를 기다립니다. clean
clone에서도 빈 DB 재시작 루프 없이 스키마가 먼저 준비됩니다.

### 4.3 Telegram 활성 조건

Telegram polling은 `TELEGRAM_BOT_TOKEN`, 허용 `TELEGRAM_CHAT_ID`, 단일
`TELEGRAM_ALLOWED_USER_ID`가 모두 유효할 때만 활성화됩니다. 하나라도 없거나 숫자 형식이 잘못되면
외부 polling을 시작하지 않습니다.

```dotenv
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_CHAT_ID=<허용 chat의 숫자 ID>
TELEGRAM_ALLOWED_USER_ID=<허용 운영자의 숫자 user ID>
```

명령은 update의 chat ID와 `message.from.id`가 각각 설정값과 일치할 때만 실행합니다. bot sender,
`sender_chat`, sender identity가 없는 update와 상태 변경 `edited_message`는 거부합니다. polling 오류
로그에는 고정된 event와 예외 타입만 남고 exception 문자열이나 traceback은 남지 않으므로, 장애 조사
시 토큰이 포함된 URL을 직접 출력하지 않습니다.

live 전환용 재인증 proof는 `ADMIN_REAUTH_SIGNING_SECRET`으로 서명합니다. 이 값은
`ADMIN_API_TOKEN`과 다른 비밀값이어야 하고, 최소 32자이면서 반복 패턴·예제 placeholder가 아닌 강한
값이어야 합니다. 운영 호스트에서 다음처럼 생성해 비밀 저장소 또는 `.env.prod`에 설정합니다.

```bash
openssl rand -base64 48
```

```dotenv
ADMIN_REAUTH_SIGNING_SECRET=<위 명령으로 생성한 별도 secret>
```

서버가 이 값을 안전하다고 판정하지 못하면 `/api/admin/reauth`는
`ADMIN_REAUTH_UNAVAILABLE`로 fail-closed합니다. secret과 proof를 로그, 화면 캡처, 운영 문서에 남기지
않으며 secret 변경 시 기존 5분 proof는 즉시 무효가 됩니다.

### 4.4 웹 UI 상태 해석과 장애 대응

웹 UI는 semantic dark/light AppShell을 사용하지만 색상만으로 운영 상태를 판단하지 않습니다.
상단 `ModeBanner`와 각 상태 패널의 텍스트를 함께 확인합니다.

- portfolio `LIVE`는 현재 실시간 응답, `SNAPSHOT`은 저장된 관측값, `STALE/CACHED`는 마지막 값과
  조회 장애가 함께 존재함을 뜻합니다. `ERROR/UNAVAILABLE/LOADING/EMPTY`는 0원 포트폴리오와 다릅니다.
- 거래 모드나 Gate를 확정하지 못하면 `UNAVAILABLE`이며 LIVE 또는 `ARMED`로 보정하지 않습니다.
- `PREPARED/SUBMITTING/UNKNOWN/ACCEPTED`는 체결 성공이 아닙니다. 청산도
  `COMPLETED + VERIFIED`만 성공이며 `PARTIAL`, `FAILED`, `LEGACY_UNVERIFIED`,
  `NO_ASSETS + VERIFIED`는 각각의 설명을 그대로 확인합니다.
- portfolio가 unavailable이면 AI briefing, dashboard mini chat과 AI Banker 전송이 차단됩니다. 화면을
  새로 고쳐 데이터를 다시 확인하되 0원으로 간주해 승인하거나 주문하지 않습니다.
- Settings는 편집을 시작한 각 키의 `expected_version`을 유지합니다. `409`는 stale draft 충돌이고,
  `503 + saved=true`는 DB 저장 뒤 runtime reload 실패이므로 동일한 실패로 처리하지 않습니다.
- AI Banker의 제안 승인도 제안 시점의 exact `current_value + expected_version`만 사용합니다. SSE 오류나
  portfolio unavailable 상태에서는 승인을 재구성하거나 전송하지 않습니다.

desktop sidebar와 mobile drawer 전환은 안전 controller를 unmount하지 않도록 구성되어 있습니다.
반응형 전환 도중 진행 중인 봇·청산 요청이 있다면 다른 멱등성 키로 새 작업을 만들지 말고 동일 화면의
pending 상태 또는 terminal snapshot을 확인합니다.

## 5. 안전 기본값

- `paper + inactive + BLOCK_ALL`로 시작합니다.
- 실거래 매수는 잠근 상태로 둡니다.
- 관측 모드에서 매수 후보와 차단 사유를 먼저 확인합니다.
- 며칠간 판단 로그, RAG 경고, 모의 거래 손익을 확인한 뒤 실거래 매수 잠금을 해제합니다.
- fault-injection과 shadow 검증이 끝나기 전에는 `live_order_v2_enabled`를 활성화하지 않습니다.
- 전량청산 UI는 terminal 결과를 사용자가 닫거나 새 작업을 준비할 때까지 같은 `Idempotency-Key`와
  마지막 operation snapshot을 sessionStorage에 보존합니다.
- migration은 기존 `UPBIT/primary` Gate `BLOCK_ALL`과 rollout OFF를 preflight로 확인한 뒤 거래 모드 원장과 mirror를 `paper`, 모든 봇을 inactive로 초기화합니다. 애플리케이션 시작이나 봇 시작은 이를 자동 전환하지 않습니다.

### 5.1 설정 변경과 동시성 운영

운영 설정은 `GET /api/system/configs`가 반환한 각 행의 `version`을 기준으로 변경합니다. REST 다중 변경,
AI Banker 승인과 Telegram `/setrisk`는 같은 서버 registry·검증·원자 저장 서비스를 사용합니다.

```http
PUT /api/system/configs
Content-Type: application/json

[
  {
    "config_key": "ai_max_buy_weight_pct",
    "config_value": "20",
    "expected_version": 3
  },
  {
    "config_key": "ai_max_concurrent_positions",
    "config_value": "2",
    "expected_version": 7
  }
]
```

- 모든 키와 값을 먼저 검증하고 정렬된 행을 잠근 뒤 version을 확인합니다. 하나라도 stale·누락·무효이면
  변경 전체가 rollback됩니다.
- version 충돌·보호 키·필수 행 누락은 `409`, 형식·범위·unknown key는 `422`입니다. 클라이언트는
  최신 목록을 다시 읽고 운영자가 변경 내용을 재검토해야 하며 stale 값을 자동 병합하지 않습니다.
- 저장 커밋 후 스케줄러 reload만 실패하면 `503` 응답의 `detail.saved=true`를 확인합니다. 이 경우
  저장은 취소되지 않았으므로 동일 payload를 즉시 재전송하지 말고 최신 설정을 다시 조회합니다.
- Settings UI는 키별 최초 편집 version을 저장 기준으로 고정합니다. 편집 중 query가 갱신돼 기준 version과
  달라지면 최신 version으로 draft를 자동 재기반하지 않고 API 호출 없이 입력과 기준 version을 폐기한 뒤
  최신 설정을 다시 불러옵니다. 실제 운영 대상과 한도는 `ai_trade_target_symbols`,
  `ai_trade_excluded_symbols`, `max_allocation_pct`, `ai_max_buy_weight_pct`,
  `ai_max_concurrent_positions` 등 `SystemConfig`에서 읽습니다.
- `BotConfig.config_json`의 `symbols`, `allocation_pct_per_symbol`, strategy/risk/schedule은 legacy/연구
  프로필입니다. Settings 운영값으로 표시하지 않으며 Laboratory의 참고 초기값으로만 사용할 수 있습니다.

연구 프로필 API를 직접 사용할 때는 먼저 version을 읽습니다.

```http
GET /api/config
# ETag: "4"
# X-Config-Version: 4

POST /api/config
If-Match: "4"
Content-Type: application/json

{...BotConfig 연구 프로필...}
```

`If-Match`가 없으면 `428`, 다른 writer가 먼저 저장했으면 `409`입니다. heartbeat와 최근 오류·동작은
`bot_configs.runtime_*` 컬럼만 갱신하므로 연구 프로필 저장과 서로 덮어쓰지 않습니다.

AI Banker의 설정 변경 제안은 생성 시점의 `expected_version`을 보존합니다. 승인이 늦어져 version이
달라지면 `409`이며 새 제안을 받아야 합니다. Telegram `/setrisk`는 다음 이름만 지원합니다.

- `max_allocation`
- `max_buy_weight`
- `max_positions`
- `entry_score`
- `min_confidence`

예전 `daily_loss`, `max_capital`, `position`, `cooldown`, 알 수 없는 이름 또는 중복 이름이 하나라도
포함되면 전체 명령을 변경 없이 거절합니다. 성공 메시지는 실제 저장된 SystemConfig key/value/version을
표시합니다.

`ai_provider_status`는 내부 운영 상태이므로 일반 설정 저장이나 AI Banker로 초기화할 수 없습니다.

```http
POST /api/system/ai/providers/status/reset
Content-Type: application/json

{"expected_version": 12}
```

provider 상태 화면에서 현재 SystemConfig version을 사용하며 stale reset은 `409`입니다. 거래 모드는
`trading_mode_controls`, 실주문 Gate는 `live_order_controls`, 배포 퓨즈는 P0 전용 경계를 계속
사용합니다. 이 값들을 일반 설정 API로 변경하려는 요청은 거절됩니다.

## 6. 실주문 Gate와 원장 운영

### 6.1 런타임·퓨즈·Gate 구분

실주문 허용 여부는 네 제어를 따로 확인합니다.

| 제어 | 의미 | 운영 기준 |
|---|---|---|
| 거래 모드 | 계정 전체 paper/live 책임 경계 | 전용 `/api/bot/trading-mode/*` API |
| 봇 런타임 | 자율 AI 분석·하드 TP/SL·일반 집행 스케줄 | `/api/bot/start`, `/api/bot/stop` |
| `live_order_v2_enabled` | 배포·인증 장애용 절대 퓨즈 | 기본 OFF, 일반 설정 API 변경 금지 |
| 실주문 Gate | 신규 Upbit POST 허용 범위 | `ARMED`, `EXIT_ONLY`, `BLOCK_ALL` |

- `ARMED`는 검증된 일반 주문만 허용합니다.
- `EXIT_ONLY`는 DB에 연결된 하나의 활성 전량청산 operation만 허용합니다. 하드 TP/SL과 일반 매도도 차단합니다.
- `BLOCK_ALL`은 전량청산을 포함한 모든 신규 POST를 차단합니다.
- 거래 모드 원장과 legacy mirror가 모두 존재하고 정확히 일치할 때만 상태를 신뢰합니다. 그 외에는 `PAPER / UNAVAILABLE`입니다.
- `/api/bot/start`는 런타임만 시작하고 Gate를 바꾸지 않습니다.
- `/api/bot/stop`은 런타임을 정지하고 Gate를 `BLOCK_ALL`로 만듭니다.
- `/api/bot/order-gate/block`은 신규 주문만 차단하며 실행 중인 분석 런타임은 유지합니다.
- 상태 조회가 실패하거나 제어 행이 없으면 `BLOCK_ALL`로 표시하고 허용으로 해석하지 않습니다.

Gate가 차단돼도 Gemini/OpenAI 제공자와 분석 로그 기능은 제거되지 않습니다. 런타임이 RUNNING이면
자율 분석은 계속되며 paper 수동 AI Cycle은 기존 모의매매를 수행합니다. live 수동 AI Cycle과 중앙
실주문 경계만 정확한 live 상태와 `ARMED`를 요구합니다. 런타임 자체를 STOPPED로 바꾸면 자율 AI
분석과 하드 TP/SL은 건너뜁니다. 두 경우 모두 reconciliation은 계속 실행합니다.

AI 분석 로그 저장과 주문 평가는 하나의 cycle identity로 연결됩니다. 분석 로그 commit 또는 refresh가
실패하면 해당 종목에서는 executor를 호출하지 않으며, 과거 BUY/SELL 또는 BUY 직전 검증 로그를 대신
실행하지 않습니다. executor 로그의 `analysis_id` 누락·미존재·종목 불일치는 모두 정상 주문 후보가
아닌 fail-closed skip으로 취급합니다. 자율 scheduler는 실패한 종목을 기록하고 다음 종목을 독립적으로
처리하며, 수동 AI Cycle은 저장 실패를 `500`으로 반환하고 주문 평가를 수행하지 않습니다.

신규 BUY는 같은 cycle에서 확정한 리스크 상태를 추가로 요구합니다. 하드 TP/SL 설정이 유효하고
포트폴리오 가격·평균 매입가·손익이 완전하며 임계값을 넘지 않은 `HEALTHY`, 또는 유효한 `0/0`
설정으로 명시적으로 비활성화된 `DISABLED`에서만 진행합니다. 설정 파싱 실패·NaN·범위 이탈,
portfolio error/stale, 양수 보유 자산의 가격 또는 평균 매입가 누락은 `UNKNOWN`, 임계값 도달은
`UNHEALTHY`입니다. `UNKNOWN/UNHEALTHY` 및 상태 누락은 신규 BUY만 차단합니다. 기존 SELL,
emergency liquidation, reconciliation은 계속 가능하지만 모두 기존 중앙 주문 서비스와 Gate를
통과하므로 STOP이나 `BLOCK_ALL/EXIT_ONLY`를 우회하지 않습니다.

live BUY 2차 검증은 증액 권한이 없습니다. 최종 주문 비중은 1차 분석 비중, 2차 검증 비중,
`ai_max_buy_weight_pct` 중 최솟값입니다. precheck 로그에 1차보다 큰 원본 값이 남을 수 있지만 실제
주문 예산에는 사용되지 않습니다. 최종 목표 예산이 5,000원 미만이면 주문을 생략하며 5,000원으로
상향 보정하지 않습니다. 정확히 5,000원인 경계만 최소 주문액으로 유지합니다.

live BUY precheck 뉴스 context는 다음 순서로 구성합니다.

1. 설정이 활성화되어 있으면 BUY 직전 뉴스 최신화를 먼저 시도하고 성공·부분 성공·실패 상태를
   `buy_precheck_news_refresh`에 기록합니다. 비활성도 명시적인 상태입니다.
2. 최신화 결과와 무관하게 해당 종목의 최신 또는 캐시/RSS 뉴스를 다시 조회합니다.
3. 최대 3건에서 `title`, 180자 이하 `summary`, `source`, `published_at`, `link`만 추려
   `buy_precheck_news_context` 불변 snapshot을 만듭니다.
4. 두 값을 1차 분석 값·Entry Gate·포트폴리오 context와 함께 canonical user prompt로 직렬화하고,
   `buy_precheck.v2` 및 그 exact prompt의 `context_sha256`를 precheck 로그에 저장합니다. DB parent는
   해당 cycle의 exact primary ID를 계속 가리킵니다.

최신화 실패·비활성 시에도 기존 캐시/RSS 조회는 계속합니다. 검색이 실패하거나 뉴스가 0건이면 그
상태를 LLM context에 노출하지만 뉴스 부재만으로 BUY를 자동 veto하지 않습니다. 반대로 뉴스가 있다고
BUY를 자동 승인하지도 않으며, risk 상태, confidence, Entry Gate, reduce-only sizing, 중앙 주문 서비스,
Kill Switch와 `ARMED/EXIT_ONLY/BLOCK_ALL`은 그대로 적용됩니다. paper와 SELL에는 이 live BUY 전용
snapshot 경로를 추가하지 않습니다.

AI provider timeout은 다음처럼 운영합니다.

- primary 분석: provider당 20초, fallback 포함 provider 실행 총 35초. 모두 실패하면 해당 cycle에
  새 HOLD 로그를 저장하며 과거 분석을 실행하지 않습니다.
- live BUY precheck: OpenAI 단일 15초. timeout·오류는 HOLD 감사 로그를 남기고 주문 0회로 닫습니다.
- 포트폴리오·뉴스 감성·백테스트 리포트: provider당 20초, 총 35초.
- 채팅: provider당 30초, 총 45초.
- 직접 SDK 호출: Gemini/OpenAI application/HTTP 30초, SDK 내부 재시도 없음. 뉴스 번역은 문서
  한 건의 Gemini→OpenAI 전체 fallback을 60초로 추가 제한합니다.

timeout은 quota나 429가 아니므로 provider rate-limit 차단 시간을 만들지 않습니다. 실제 429·quota만
기존 cooldown 정책을 적용합니다. 외부 task 취소는 fallback으로 전환하지 않습니다. 위 총예산은
provider 실행 구간 기준이며 후보 조회·상태 기록 DB 지연은 별도입니다. deadline은 독립 하드 TP/SL
scheduler나 다중 worker lease를 제공하지 않으므로 그 운영 모델은 `ATM-P2-002`·`ATM-P2-003` 후속
설계를 따릅니다. STOP·`BLOCK_ALL/EXIT_ONLY`와 중앙 주문 경계는 timeout 처리로 우회되지 않습니다.

AI 분석 감사 조회에서는 stage를 먼저 확인합니다.

- `TRADE_ANALYSIS`: 주문 executor, 정확도 worker, BUY calibration과 자기교정의 유일한 신규 입력입니다.
- `BUY_PRECHECK`: exact primary를 `parent_analysis_id`로 연결한 live BUY 2차 판단입니다. provider 응답
  veto는 원본 값을 유지하며 provider 미응답 HOLD만 `SYSTEM / DETERMINISTIC_HOLD`입니다.
- `LEGACY_UNKNOWN`: migration 이전 행이며 provider나 stage를 추정하지 않습니다. 신규 primary가 없는
  종목의 최신 화면에서만 호환 노출하고 신규 정확도·calibration에는 포함하지 않습니다.

`context_sha256`는 provider에 전달한 exact user prompt의 무결성 확인값이며 원문 복원 수단은
아닙니다. `prompt_version`과 함께 비교하고, precheck 주문 성과는 주문 FK를 primary로 다시 쓰지 않고
parent를 조회해 귀속합니다. parent 누락·다른 stage·symbol 불일치는 주문 실행과 AI confidence 귀속에
사용하지 않습니다. migration `c7a1e9d4f2b6` 이전으로 downgrade하면 계보 컬럼이 제거되므로 운영
데이터가 생성된 뒤에는 감사 정보 손실을 고려해야 합니다.

### 6.2 제출 배리어와 연결 요구사항

실주문 제출은 PostgreSQL session-level advisory shared lock, 런타임 시작·거래 모드 전환·정지·재무장·청산 제어는 같은 key의
exclusive lock을 사용합니다. 기본 lock 획득 제한은 shared 5초, exclusive 30초입니다. 제한 안에
획득하지 못하면 성공으로 처리하지 않고 `503` 계열 Gate 오류를 반환합니다.

- 배리어 connection은 PostgreSQL에 직접 연결하거나 session pooling을 사용해야 합니다.
- transaction pooling 방식의 PgBouncer는 session lock 소유권을 보장하지 못하므로 비호환입니다.
- shared connection은 Upbit POST 동안 유지되지만 DB 트랜잭션은 닫혀 있습니다.
- PostgreSQL `idle_session_timeout`, proxy timeout, pool recycle 값은 최대 Upbit POST timeout과 lock
  해제·오류 정리 여유보다 길게 설정합니다. 현재 Upbit HTTP 기본 timeout은 10초입니다.
- pool은 동시 POST가 점유하는 connection 외에 exclusive 제어·reconciliation이 사용할 여유를 둡니다.
- unlock 실패나 task 취소 시 connection을 invalidate/close하므로 강제로 재사용하지 않습니다.

exclusive lock은 정상 shared POST 반환을 기다립니다. 여기에 더해 DB에 `SUBMITTING` intent가 남아
있는지도 확인합니다. 차단 상태는 이미 커밋됐지만 과거 connection 유실 등으로 POST 종료를 확정할
수 없으면 API는 `503 ORDER_GATE_DRAIN_PENDING`을 반환합니다. 이 응답을 “정지 실패로 Gate가 다시
열림” 또는 “정지 성공”으로 단정하지 말고 `/api/bot/order-gate`와 해당 intent를 확인합니다. Gate는
계속 `BLOCK_ALL`이며 reconciliation으로 거래소 상태를 조정한 뒤 같은 제한 명령을 다시 확인합니다.
관리자 UI는 이 경우 정지 재확인 버튼 또는 동일 차단 `Idempotency-Key`를 보존합니다.

### 6.3 거래 모드 전환 절차

상태는 관리자 `GET /api/bot/trading-mode`로 조회합니다. 응답의 `state_available=false`, version 0,
mirror 불일치 또는 조회 오류를 live로 보정하지 않습니다. React UI도 이 경우 `PAPER / UNAVAILABLE`로
표시하고 live 전환·재무장을 차단합니다.

live 전환은 다음 순서를 따릅니다.

1. runtime inactive, rollout ON, Gate `BLOCK_ALL`, 활성 청산과 blocking intent 없음, 거래 모드 원장과
   mirror가 정상 paper인지 확인합니다.
2. UI에 관리자 토큰을 다시 입력합니다. 저장된 브라우저 토큰을 재사용하지 않습니다. REST 호출은
   입력한 토큰을 `X-Admin-Token` 헤더에만 넣고 `POST /api/admin/reauth` body에는
   `{"purpose":"ENABLE_LIVE_TRADING"}`만 보냅니다.
3. 5분짜리 `reauth_proof`를 받으면 UUID v4 `Idempotency-Key`, 현재 mode `expected_version`, 현재 Gate
   `expected_gate_generation`과 `expected_gate_version`, 10자 이상 사유, 정확한 확인 문구
   `ENABLE_LIVE_TRADING`, proof를 `POST /api/bot/trading-mode/live`에 보냅니다.
4. 네트워크 응답을 잃은 경우에만 같은 키와 같은 payload를 재전송합니다. stale snapshot이나 같은
   키의 다른 payload는 `409`이며 자동으로 값을 바꾸거나 새 키로 재시도하지 않습니다.
5. 전환 성공 뒤에도 runtime inactive와 Gate `BLOCK_ALL`을 확인합니다. 그 다음 런타임 시작과 Gate
   재무장을 각각 별도 승인합니다.

paper 전환은 `POST /api/bot/trading-mode/paper`에 UUID v4 `Idempotency-Key`, 현재 mode
`expected_version`, 10자 이상 사유를 보냅니다. 권한 축소이므로 재인증 proof와 확인 문구는 요구하지
않습니다. 서버는 먼저 런타임을 정지하고 Gate를 `BLOCK_ALL`로 만든 뒤 mode 원장과 mirror를 같은
트랜잭션에서 paper로 바꿉니다. `SUBMITTING` drain이 남으면 성공으로 간주하지 않고 Gate와 intent를
조정한 뒤 같은 제한 요청을 확인합니다.

### 6.4 정지·재무장 절차

1. 즉시 차단은 관리자 UI 또는 `POST /api/bot/order-gate/block`에 UUID v4 `Idempotency-Key`와 10자
   이상 사유를 보냅니다. 네트워크 응답을 잃으면 payload와 키를 모두 그대로 재사용합니다.
2. 분석 런타임까지 멈추려면 `POST /api/bot/stop`을 사용합니다. Slack/Telegram `/stop`도 같은
   `LiveOrderControlService`를 거칩니다.
3. 재무장 전에 런타임 RUNNING, `trading_mode=live`, rollout ON, blocking intent 없음, 활성 청산 없음을
   확인합니다.
4. `POST /api/bot/order-gate/arm`에 현재 `expected_generation`, `expected_version`, UUID v4
   `Idempotency-Key`, 10자 이상 사유, 정확한 확인 문구 `ENABLE_LIVE_ORDERS`를 보냅니다.
5. stale generation/version, 같은 키의 다른 payload, 이후 정지로 supersede된 과거 요청은 `409`이며
   새 상태를 조회한 뒤 운영자가 다시 판단합니다.

Slack/Telegram `/start`도 런타임만 시작합니다. 메신저에는 재무장 명령이 없으며 재무장은 관리자
REST/UI에서만 수행합니다.

`live_order_v2_enabled`는 일반 `/system/configs`와 AI Banker 설정 승인으로 변경할 수 없고 해당
요청은 `409`입니다. 현재 공개 API는 퓨즈를 켜는 기능을 제공하지 않습니다. 운영 배포 절차에서만
통제된 DB 변경으로 활성화하고, 그 뒤 별도의 Gate 재무장을 수행합니다.

### 6.5 인증 장애와 전량청산

Upbit 인증·권한·허용 IP·HTTP 418 오류는 같은 장애 세대의 감사 event를 멱등하게 남기면서
`live_order_v2_enabled=false`와 `BLOCK_ALL`을 적용합니다. 자동 재활성화하지 않습니다. 키·IP·권한을
복구하고 미확정 주문을 조정한 뒤 퓨즈 활성화와 재무장을 각각 다시 수행합니다.

현재 전량청산 계약은 Upbit `primary` 계정 전체의 `wait/watch` 주문을 취소하므로 봇이 만든 주문뿐
아니라 사용자가 Upbit 화면에서 직접 만든 주문도 취소합니다. UI 경고를 읽고 정확한 확인 문구를
직접 입력한 뒤 실행합니다.

```http
POST /api/bot/liquidate
Idempotency-Key: <UUID v4>
Content-Type: application/json

{"scope":"ACCOUNT_ALL","confirmation":"CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL"}
```

과거 `LIQUIDATE_ALL` body는 P0-002 시점의 역사적 계약이며 현재 API에서는 `422`입니다. 같은 UUID에
다른 scope/fingerprint를 보내면 `409 LIQUIDATION_IDEMPOTENCY_CONFLICT`입니다. 신규 operation은
거래 모드 원장과 mirror가 정확히 live일 때만 만들며, `(UPBIT, primary)`에 활성 operation이 이미
있으면 새 작업을 만들지 않고 기존 작업 상세를 확인합니다.

실행·복구 순서는 다음과 같습니다.

1. POST가 exclusive 제출 배리어에서 operation 생성, 런타임 정지, `BLOCK_ALL`, 기존 POST drain을
   먼저 커밋합니다. 이 단계의 `202`는 접수일 뿐 청산 성공이 아닙니다.
2. worker가 계좌 최초 snapshot과 모든 `wait/watch` 주문을 100개씩 끝까지 조회합니다. 발견한
   Upbit UUID를 관리 주문과 수동·외부 주문으로 구분해 취소 원장에 저장합니다.
3. 취소는 최대 20개 UUID를 claim·commit한 뒤 DB 트랜잭션 없이 한 번 호출합니다. 응답 유실,
   5xx·429·파싱 오류가 나면 각 UUID를 조회해 실제 상태를 판정합니다. 명확히 계속 열려 있는
   주문만 다음 스케줄에서 다시 취소하며 주문별 최대 3회입니다.
4. 관리 주문의 취소 중 체결은 기존 OrderIntent reconciliation으로 `OrderHistory`와 Position에
   exactly-once 투영합니다. 해결되지 않은 blocking intent 또는 미체결 주문이 있으면 청산 매도를
   제출하지 않습니다.
5. 미체결 주문 0을 다시 확인하고 계좌를 재조회한 뒤 청산 대상을 불변 snapshot으로 확정합니다.
   이때 Upbit `balance`는 이미 주문 가능한 수량이므로 `balance - locked`가 아니라 `balance` 자체를
   시장가 매도 수량으로 사용합니다. `locked`는 별도 잔여 증거로 유지합니다.
6. 활성 KRW 마켓이 없으면 `UNSUPPORTED_MARKET`, 평가액 5,000원 미만이면
   `DUST_REMAINING`, 전량 잠금이면 `LOCKED_REMAINING`으로 기록하고 POST하지 않습니다. 주문 가능한
   snapshot만 해당 operation의 `EXIT_ONLY` 권한으로 중앙 주문 서비스에 제출합니다.
7. 모든 intent가 종결·투영되면 worker가 미체결 주문, 계좌 전체, live Position을 최종 검증합니다.
   새 미체결 주문은 최대 3회의 추가 발견·취소 라운드로 처리하지만 snapshot 이후 생긴 자산에
   자동 2차 시장가 매도를 만들지 않습니다.
8. operation 종결과 authorization `CLOSED`, Gate `BLOCK_ALL` 복귀는 같은 exclusive 트랜잭션 경계에
   저장합니다. `COMPLETED`, `PARTIAL`, `FAILED`, `NO_ASSETS` 어느 결과도 자동 재무장하지 않습니다.

계좌 응답의 currency 중복·소문자, `balance/locked` 누락·빈 값·음수·비유한 수·Decimal 파싱 실패는
`NO_ASSETS`로 낮추지 않고 operation 오류로 남겨 재조회합니다. Upbit 취소·조회 중 인증·권한·418이
발생하면 퓨즈 OFF와 `BLOCK_ALL`을 적용하고 operation은 실패 종결합니다.

성공 판정은 다음 증거를 모두 요구합니다.

- 전체 `wait/watch` 주문 0
- 모든 비-KRW `balance=0` 및 `locked=0`
- 청산 OrderIntent가 거래소 종결 상태이고 체결 투영 `APPLIED/SKIPPED`
- 거래소 보유량과 live Position 차이가 통화별 `1e-12` 이하
- 수동·외부 주문에서 미조정 체결이 발견되지 않음

모두 만족한 `COMPLETED + VERIFIED`만 성공입니다. 처음부터 자산·잠금·Position이 모두 없고 같은
검증을 통과하면 `NO_ASSETS + VERIFIED`입니다. dust, 잠금, 미지원 자산, 주문 실패는 `PARTIAL`이며,
외부 주문 체결이나 거래소 잔고와 Position 차이는 `LEDGER_MISMATCH`로 `PARTIAL` 처리합니다. 이를
맞추기 위해 가짜 체결 이력이나 자동 Position 보정을 만들지 않습니다.

API 응답의 `phase`, `verification_status`, `summary`, `cancellations`, 종목별 최초·취소 후·최종
`balance/locked`, `requested/executed_volume`, `result_code`를 함께 확인합니다. phase는 다음 순서입니다.

`BLOCKING → DISCOVERING_ORDERS → CANCELING_ORDERS → RECONCILING_CANCELED_ORDERS → SNAPSHOTTING_TARGETS → SUBMITTING → WAITING_FILLS → VERIFYING → TERMINAL`

- `POST /api/bot/liquidate`: 진행 중이면 `202`, 같은 키의 terminal 결과면 `200`입니다.
- `GET /api/bot/liquidations/{id}`: PostgreSQL 상태만 읽으며 worker 실행, Upbit 취소·조회, 주문 제출을
  수행하지 않습니다.
- 복구 job: 애플리케이션 시작 시 한 번, POST 접수 직후 즉시, 이후 15초 주기로 due operation을
  claim합니다. transient 오류 backoff는 15초에서 최대 15분입니다.
- UI: terminal 결과와 UUID를 사용자가 닫거나 새 청산을 준비할 때까지 보존하며
  `COMPLETED + VERIFIED`만 성공색으로 표시합니다. legacy `COMPLETED`는 `LEGACY_UNVERIFIED` 경고입니다.
- Slack/Telegram: 청산 실행 기능을 제공하지 않습니다. `/status`에는 활성 operation ID, phase,
  잔여 수만 표시하며 비상 정지는 기존 `/stop`을 사용합니다.

### 6.6 주문 원장과 reconciliation

- 신규 배포는 `alembic upgrade head`를 먼저 적용한 뒤 백엔드를 시작합니다.
- `/api/orders/intents`에서 `SUBMITTING`, `UNKNOWN`, 장기 `PENDING/ERROR` 상태를 확인합니다.
- reconciliation은 시작 시점과 15초 주기로 identifier 조회만 수행합니다.
- `UNKNOWN` 상태에서는 같은 마켓 주문이 차단되며, 매수 UNKNOWN은 다른 신규 매수도 차단합니다.
- 관리자 즉시 조회는 `/api/orders/intents/{id}/reconcile`을 사용합니다.
- `NO_ORDER_CONFIRMED` 해제는 15분 이상 경과, 5회 이상의 404, 10분 이상의 조회 간격, 최신 404, Upbit 화면 확인과 사유를 모두 요구합니다.
- 관리자 해제 중에는 전용 lease와 version CAS가 적용되며 재조정이 진행 중이면 `409`로 다시 시도하게 합니다.
- identifier와 청산 operation은 재사용하거나 hard delete하지 않습니다.

전량청산 operation은 주문별 상태만으로 `COMPLETED`를 계산하지 않습니다. 최종 계좌·미체결 주문·
Position 증거까지 `VERIFIED`여야 하며, 그 전에는 `PENDING/ERROR`와 현재 phase로 표시합니다. 운영자는
종목별 `result_code`, 최초·최종 `balance/locked`, `submission_status`, `exchange_state`,
`projection_status`, 체결·잔여 수량과 취소 원장을 함께 확인합니다.

## 7. 백업과 복구

- PostgreSQL 백업을 운영 복구 기준으로 봅니다.
- OpenSearch 뉴스 캐시는 재수집 가능한 데이터로 봅니다.
- 장애 시 주문 위험을 먼저 멈추고, 그 다음 로그와 저장소 상태를 확인합니다.
- UNKNOWN 주문이 남아 있으면 기존 코드로 롤백하거나 주문 원장 migration을 downgrade하지 않습니다.
- 백업 복구 후에도 과거 identifier가 보존됐는지 확인합니다.

배포·롤백은 다음 순서를 지킵니다.

1. 구버전에서 먼저 rollout 퓨즈를 OFF로 커밋하고 봇과 신규 주문을 정지합니다.
2. 진행 중 POST와 `SUBMITTING`을 drain한 뒤 migration과 신버전 코드를 배포합니다.
3. 모든 인스턴스가 신버전이고 거래 모드와 mirror가 paper, runtime inactive, Gate가 `BLOCK_ALL`인지 확인합니다.
4. PostgreSQL 경합·fault-injection 검증 전에는 퓨즈를 ON으로 바꾸지 않습니다. 퓨즈 ON 뒤에도 별도
   `ARMED` 전이가 필요합니다.
5. `EXIT_ONLY`, `SUBMITTING`, `UNKNOWN`, 미종결 `ACCEPTED`, projection `ERROR`, 배리어 장애가 남으면
   코드 롤백이나 migration downgrade를 수행하지 않습니다.
6. 구버전으로 롤백해야 하면 신버전에서 먼저 퓨즈 OFF, `BLOCK_ALL`, in-flight drain을 완료하고
   구버전 프로세스를 시작합니다.

ATM-P0-004 migration upgrade/downgrade는 rollout OFF, 모든 Gate `BLOCK_ALL`, 활성 청산·활성 긴급
승인·blocking intent 없음이 필수입니다. downgrade는 여기에 더해 v2 operation, 취소 원장,
operation event가 한 건도 없어야 합니다. 실제 ACCOUNT_ALL 청산 증거가 생성된 DB는 downgrade하지
말고 현재 코드로 복구·조정합니다.

reconciliation worker는 퓨즈 OFF, `BLOCK_ALL`, 런타임 STOPPED에서도 identifier GET과 종결 체결
투영을 계속합니다. 안전을 이유로 이 worker를 함께 끄지 않습니다.

## 8. 운영 점검

| 항목 | 확인 기준 |
|---|---|
| 웹 UI | 로컬과 Tailscale 경로에서 접속 가능 |
| API | 공개 GET allowlist는 토큰 없이 동작하고, 나머지는 관리자 토큰 없이는 차단; route policy·429/503·health 면제 확인 |
| DB | 마이그레이션 적용 완료, `api_rate_limit_windows` 원자 집계와 백업 가능 |
| 거래 모드 | control/mirror 일치, 상태 available, 의도한 paper/live version |
| 주문 원장 | 장기 SUBMITTING/UNKNOWN 없음, reconciliation 정상, 기능 플래그 의도와 일치 |
| RAG | OpenSearch 상태와 RAG warning 확인 |
| 메신저 | Slack 테스트는 관리자 인증·서버 webhook만 사용; Telegram은 token+허용 chat ID+허용 user ID가 모두 있고 chat·sender가 일치할 때만 명령 실행; 청산 실행 명령 없음 |
| 네트워크 | CORS allowlist, 개발 publish 포트 loopback, Compose `/api/health` healthcheck 확인; 일반 외부망에서 DB/API/OpenSearch 미노출 |
| UI 상태 사실성 | portfolio 상태·갱신 시각·오류, PAPER/LIVE/UNAVAILABLE, Gate 상태와 청산 verification을 텍스트로 확인; 장애를 0원·성공으로 해석하지 않음 |

## 9. 현재 검증 상태

2026-07-13 기준 격리된 Docker PostgreSQL 16.12 환경에서 P0-001~P0-004의 최종 검증을
완료했습니다. 원격 CI는 아직 실행하지 않았습니다.

- backend 전체 비-PostgreSQL 테스트: `359 passed, 64 deselected`
- Ruff: `app`, `tests` 통과
- frontend: `38 tests`, ESLint, production build 통과
- frontend build의 기존 chunk-size 경고는 남아 있습니다.
- PostgreSQL marker 테스트: migration 왕복 전후 각각 `64 passed, 359 deselected`, skip 0건
- 빈 DB `alembic upgrade head`, fail-closed 준비 후 `alembic downgrade d3a9f7c1b2e4`, 재업그레이드,
  `alembic check`, 단일 head/current `f6b2c9d4e8a1` 확인
- trading mode 8세션 경합, start/mode/Gate advisory 직렬화, 최종 POST 경쟁, 주문 원장
  exactly-once, 청산 lease/CAS·선취소·최종 증명을 실제 PostgreSQL에서 통과
- 실제 Upbit·Gemini API, 운영 DB, 원격 CI, git push는 사용하거나 실행하지 않았습니다.

2026-07-13 ATM-P1-003A에서 Slack 테스트 관리자 인증, 서버 webhook 고정, 알 수 없는 필드 거부와
오류·secret 비노출을 추가했습니다. Slack API·관리자 인증 전용 `16 passed`, 최신 backend 비-PostgreSQL
`368 passed, 64 deselected`, Ruff, frontend `38 passed`, ESLint와 production build를 통과했습니다.
이 변경에는 DB schema나 frontend 호출 경로 변경이 없습니다.

2026-07-13 ATM-P1-003B에서 공개 GET allowlist와 나머지 민감 API의 관리자 경계, React 전역
`AdminSessionGate`, raw chat SSE 토큰 전송, CORS allowlist, 개발 포트 loopback, Telegram fail-closed
활성 조건과 secret 비노출 logging을 반영했습니다. DB schema 변경은 없으며 `docs/DATABASE.md`도 변경할
계약이 없습니다. 최신 backend 비-PostgreSQL `394 passed, 64 deselected`, Ruff, frontend `54 passed`,
ESLint와 production build를 통과했습니다. 기존 500KB chunk-size 경고만 유지됩니다. 실제 외부 API,
운영 DB, 원격 CI, git push는 사용하거나 실행하지 않았습니다. endpoint별 공유 rate limit과 Telegram
실제 sender identity 검증은 당시 P1-003C 후속 범위로 남겼습니다.

2026-07-13 ATM-P1-003C는 **로컬 PostgreSQL 16·전체 회귀 완료 / 원격 CI 미실행** 상태입니다. 고정
policy/principal 기반 PostgreSQL fixed-window, raw 값 비저장, health 면제, 별도 `SAFETY_STOP`
bucket, Telegram 허용 user ID 검증을 구현했습니다. P1-003B에서 자동 OpenAPI를 비활성화한 뒤 로컬
Compose healthcheck가 계속 `/openapi.json`을 조회하던 회귀는 `/api/health`와 정적 회귀 검사로
수정했습니다.

- `postgres:16-alpine`, PostgreSQL 16.12에서 fresh upgrade와 `b8d4e6f1a2c3` → `f6b2c9d4e8a1`
  downgrade → head 재업그레이드, `alembic check`, 단일 head/current 통과
- PostgreSQL marker `73 passed`; 신규 limiter 9개는 재업그레이드 전후 각각 통과
- backend 비-PostgreSQL `451 passed`, backend 합계 `524 passed`, Ruff 통과
- 보안·migration 대상 회귀 `98 passed`, 마지막 보안 hardening 대상 `89 passed`
- frontend `54 passed`, ESLint·production build 통과; 기존 500KB chunk 경고 유지

Windows Docker fsync 지연 때문에 기존 PostgreSQL 테스트의 2~5초 대기를 30초로 보강하고 취소 phase
테스트를 bounded refresh로 수정했습니다. 검증 안정화를 위한 테스트 변경뿐이며 운영 코드는 바꾸지
않았습니다. 실제 외부 API·운영 DB·원격 CI·push와 Docker Compose 전체 기동은 실행하지 않았습니다.

잔여 위험은 네 가지입니다. Caddy shared-ingress rate-limit plugin은 아직 설치·고정·검증하지 않았고,
만료 window 정리가 제한 판정 SQL의 hot path에 있어 대량 backlog·장시간 lock용 bounded DB timeout을
후속 보강해야 합니다. 또한 fixed-window는 장시간 AI·backtest 작업의 분산 동시성 lease를 제공하지
않으며, Telegram에는 다중 poller lease와 durable update receipt가 없어 단일 backend poller 운영
전제를 유지합니다.

P1-003C의 상세 환경과 검증 증거는
[P1-003C 검증 보고서](reviews/2026-07-13-p1-003c-verification.md)를 참조합니다. P0-001~P0-004의
이전 migration 왕복과 격리 자원 정리 증거는
[P0 로컬 PostgreSQL 16 최종 검증 보고서](reviews/2026-07-13-p0-postgres-verification.md)에 있습니다.

2026-07-15 ATM-P1-004/006은 BotConfig runtime 분리, BotConfig/SystemConfig version, 중앙 키별 검증,
REST·AI Banker·Telegram의 공통 CAS 계약과 실제 SystemConfig 소비 UI를 구현했습니다. migration
`d5e8a1c4b7f2`의 offline SQL, 단일 head, backend 비-PostgreSQL 627개, frontend 66개,
Ruff·ESLint·production build를 통과했습니다. 이후 UI-001 Phase 0에서 격리된 PostgreSQL 16.12의
marker 79개를 migration 왕복 전후 두 차례 통과해 backfill·제약·다중 세션 CAS를 로컬에서
확인했습니다. 원격 CI와 실제 운영 DB 적용은 수행하지 않았습니다. 상세 구현 기록은
[P1-004/006 검증 보고서](reviews/2026-07-15-p1-004-006-verification.md)를 참조합니다.

2026-07-15 ATM-UI-001은 Stitch 디자인을 semantic dark/light AppShell로 이식하고 Dashboard, Portfolio,
AI Banker, Laboratory, Settings와 안전 제어 패널을 같은 상태 언어로 정리했습니다. 공통
`PortfolioDataState`는 live/snapshot/cached/error/empty/loading을 구분하고, cache가 없는 장애를 0원으로
표시하거나 unavailable portfolio를 AI context로 전달하지 않습니다. 봇·청산 controller의 mount,
멱등성 identity, Settings CAS, AI Banker exact 승인, P0 주문·Kill Switch 경계는 유지했습니다.

로컬 검증은 PostgreSQL 16.12 marker 79개를 migration 왕복 전후 두 차례, frontend 119개,
backend 비-PostgreSQL 627개, Ruff와 ESLint, production build를 통과했습니다. production build에는
단일 JS 청크 약 1.30MB의 크기 경고가 남아 있습니다. 브라우저 자동화 플러그인 런타임 오류로 320~1440px screenshot matrix 증거는
확보하지 못했으며 수동/자동 viewport QA 후속이 필요합니다. 실제 Upbit·AI API, 운영 DB, 원격 CI,
Git commit·push는 사용하지 않았습니다. 상세 내용은
[UI-001 검증 보고서](reviews/2026-07-15-ui-001-verification.md)를 참조합니다.
