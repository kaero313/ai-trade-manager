# ATM-P1-003 API·메신저 보안 경계 계획·구현 기록

> 발견사항: `ATM-P1-003`
> 상태: 003A Slack 테스트 경계 구현 완료 / 003B 민감 API·개발 ingress 경계 구현·로컬 회귀 완료 / 003C 로컬 PostgreSQL 16·전체 회귀 완료 / 원격 CI 미실행
> 구현 기준일: 2026-07-13
> 원본 리뷰: [2026-07-10 프로젝트 안전성 리뷰](../reviews/2026-07-10-project-safety-review.md)

## 1. Delta 판정

원본 리뷰의 Telegram 무단 명령 위험은 P0 구현 과정에서 허용 chat ID가 없거나 일치하지 않으면 명령을
거부하도록 보강됐습니다. 관리자 API 토큰도 설정 변경, 봇 제어, 주문 복구 경로에 도입됐습니다.

반면 `POST /api/slack/test`는 인증 없이 요청자가 보낸 `webhook_url`로 서버가 POST할 수 있었고 외부
예외 원문을 API 응답에 그대로 반환했습니다. 이는 애플리케이션 경계에서 임의 외부 URL 호출과
webhook secret 노출을 허용할 수 있어 정책 결정 없이 즉시 닫을 수 있는 003A로 분리했습니다.

현재 frontend에는 Slack 테스트 API 호출 함수나 버튼이 없습니다. 새 UI를 만드는 것은 보안 결함 수정
범위를 넓히므로 포함하지 않았습니다. 향후 UI를 추가할 때는 공통 `apiClient`와 관리자 토큰 요청 경계를
사용해야 합니다.

## 2. 003A 확정 계약

- `POST /api/slack/test`는 `require_admin_token`을 반드시 통과합니다.
- 관리자 토큰이 서버에 없으면 `503`, 요청에 없으면 `401`, 일치하지 않으면 `403`입니다.
- 요청 payload는 `text`, `username`, `icon_emoji`만 허용합니다.
- `webhook_url`을 포함한 모든 알 수 없는 필드는 Pydantic `extra=forbid`로 `422` 처리합니다.
- `SlackClient.send_message()`에는 호출자 URL override 인자가 없고 서버 `SLACK_WEBHOOK_URL`만 사용합니다.
- 서버 webhook이 없으면 외부 호출 없이 `503`입니다.
- 외부 전송 실패는 고정된 `502` 메시지만 반환합니다.
- 로그에는 구조화된 event와 예외 타입만 남기며 예외 문자열, traceback, 요청 URL은 남기지 않습니다.
- `httpx`와 `httpcore` logger는 애플리케이션 logging에서 최소 `WARNING`으로 제한해 라이브러리의
  request INFO와 헤더 DEBUG 로그가 외부 URL·인증 정보를 기록하지 못하게 합니다.
- 스케줄러와 주문 안전 경보가 사용하는 별도 `SlackBot` 기능은 변경하지 않습니다.
- paper, backtest, Gemini/OpenAI 분석, DB schema와 실주문 동작은 변경하지 않습니다.

## 3. 검증 결과

- Slack API·관리자 인증 전용 backend: `16 passed`
- backend 전체 비-PostgreSQL: `368 passed, 64 deselected`
- Ruff: 통과
- `git diff --check`: 통과
- frontend: 호출 경로가 없어 코드 변경 없음; 기존 `38 passed`, ESLint, production build 통과
- 실제 Slack, Upbit, Gemini/OpenAI, 운영 DB 호출 없음
- 원격 CI와 git push 미실행

테스트는 관리자 인증, 임의/알 수 없는 필드 거부, 서버 설정 client만 호출, 미설정 상태, 고정 오류 응답,
실제 `SlackClient` transport 성공·HTTP 오류 시 응답·라이브러리 로그의 webhook secret 비노출과
`SlackClient` 시그니처를 검증합니다.

## 4. 003B Delta와 확정 계약

API 전체와 React 소비 경로를 다시 조사한 결과, 기존 관리자 인증은 일부 설정 변경·봇 제어·복구
endpoint에만 적용돼 있었습니다. Upbit 계좌·주문 조회, dashboard·portfolio, 관심종목, 채팅·AI 비용,
백테스트와 일부 상태 조회가 보호 경계 밖에 있었고 React는 앱 mount 직후 여러 query를 동시에
시작했습니다. 일반 `apiClient`와 달리 raw chat SSE fetch에는 관리자 token header도 없었습니다.

개인 관리자 콘솔이라는 운영 모델에 따라 003B 계약을 다음처럼 확정했습니다.

- 공개 API는 `GET /api/health`, 전체 공개 market GET, 일반 뉴스 목록 `GET /api/news/`만 허용합니다.
- 뉴스 RAG/status·sentiment, 계좌·주문·dashboard·portfolio, 관심종목, 설정, 채팅, AI/LLM 비용 작업,
  백테스트와 봇 제어를 포함한 나머지 API는 `require_admin_token`을 요구합니다.
- `GET /api/admin/session`은 토큰이 유효할 때 `{ "authenticated": true }`를 반환하는 frontend 검증
  endpoint입니다.
- React는 `AdminAuthProvider` 내부의 전역 `AdminSessionGate`를 통과한 뒤에만 기존 layout과 query를
  mount합니다. 저장하거나 입력한 토큰 검증 전에는 민감 요청을 시작하지 않습니다.
- raw chat SSE도 `X-Admin-Token`을 보내며, 일반 API client와 마찬가지로 `401/403`에서 저장 토큰을
  폐기하고 Gate를 즉시 잠급니다. 거절된 요청 토큰이 현재 저장 토큰과 일치할 때만 무효화하므로 늦은
  Axios·SSE 응답이 교체된 새 토큰을 지우지 않습니다.
- FastAPI 자동 `/docs`, `/redoc`, `/openapi.json`과 OAuth redirect는 공개 allowlist 밖이므로 기본
  비활성화합니다.
- Slack 003A의 관리자 인증, 서버 webhook 고정, 오류·secret 비노출 계약은 그대로 유지합니다.

## 5. CORS·개발 ingress·Telegram 계약

- `CORS_ALLOWED_ORIGINS`는 쉼표로 구분한 정확한 HTTP(S) origin allowlist입니다. wildcard `*`, user
  info, 루트 `/` 외 경로·query·fragment와 잘못된 port는 거부합니다.
- CORS는 `allow_credentials=false`이고 허용 method/header를 애플리케이션에 필요한 범위로 명시합니다.
- 개발 Compose의 frontend·backend·PostgreSQL·OpenSearch·Dashboards publish port와 native backend는
  `127.0.0.1`에만 바인딩합니다. 컨테이너 내부 서비스 listen 주소는 Compose 네트워크 통신을 위해
  유지합니다.
- Telegram client는 bot token과 허용 chat ID가 모두 설정돼야 enabled입니다. 하나라도 없으면 polling을
  시작하지 않습니다.
- Telegram polling 예외는 고정 event와 예외 타입만 기록하고 exception 원문과 traceback을 남기지
  않습니다.
- paper, backtest 계산 로직, Gemini/OpenAI 분석, 실주문·청산 계약은 변경하지 않습니다.
- DB schema 변경은 없습니다. `docs/DATABASE.md`를 검토했으며 동기화할 schema 계약이 없어 변경하지
  않습니다.

## 6. 검증 결과

- 공개 GET allowlist와 보호 route의 인증 누락을 막는 architecture 테스트
- 관리자 session gate의 최초 검증, 취소·재시도, `401/403`, 서버 token 미설정 동작
- Axios·raw chat SSE의 token header, 인증 실패 즉시 잠금과 늦은 응답의 새 token 보존
- FastAPI 자동 문서·OpenAPI 경로 `404`
- CORS 정상 origin, 비허용 origin, wildcard·비정상 origin 거부
- 개발 Compose와 native backend의 loopback binding
- Telegram token/chat ID 조합별 활성 조건과 polling 오류 secret 비노출
- backend 전체 비-PostgreSQL, Ruff, frontend test·ESLint·production build, `git diff --check`
- 실제 Slack·Telegram·Upbit·Gemini/OpenAI, 운영 DB, 원격 CI와 git push 미사용

2026-07-13 로컬 최종 결과는 다음과 같습니다.

- backend 전체 비-PostgreSQL: `394 passed, 64 deselected`
- Ruff `app`, `tests`: 통과
- frontend 전체: `54 passed` (`8` files)
- frontend ESLint·production build: 통과
- production build의 기존 500KB chunk-size 경고는 유지
- `git diff --check`: 통과
- 실제 Slack·Telegram·Upbit·Gemini/OpenAI, 운영 DB, 원격 CI와 git push: 미사용·미실행

DB schema·migration 변경이 없어 PostgreSQL marker와 migration 왕복은 이번 변경의 재검증 대상이
아닙니다. 독립 보안 리뷰에서 자동 API 문서 노출과 인증 만료 뒤 화면 유지 문제를 발견했고, 각각
기본 `404`와 session invalidation 즉시 unmount로 수정한 뒤 잔여 P0~P2 구현 결함 없음 판정을 받았습니다.

## 7. P1-003C Delta와 확정 계약

003B는 관리자 인증과 단일 호스트 노출 경계를 닫았지만, 공개 API 비용과 관리자 고비용·상태 변경
요청을 다중 worker에서 공유해 제한하지 못했고 Telegram도 허용 chat 안의 실제 sender를 구분하지
못했습니다. P1-003C는 프로세스 메모리 카운터 대신 PostgreSQL fixed-window를 사용하고 모든 API
route를 다음 고정 policy 중 하나로 분류합니다.

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

- canonical method/path가 policy map에 없으면 요청을 허용하지 않습니다.
- `GET /api/health`는 limiter를 우회해 PostgreSQL readiness를 계속 보고합니다.
- `POST /api/bot/stop`, paper 전환, 주문 Gate 차단은 일반 상태 변경과 분리된 `SAFETY_STOP`
  bucket을 사용합니다. 이는 무제한 우회가 아니라 안전 조치용 예약 용량입니다.
- 초과 요청은 `429 RATE_LIMIT_EXCEEDED`, 정수 `Retry-After`와 제한 header를 반환합니다.
- 유효한 관리자 요청과 공개 market·뉴스 요청에서 PostgreSQL 결정을 확정하지 못하면 외부 호출이나
  상태 변경 전에 `503 RATE_LIMIT_UNAVAILABLE`로 fail-closed합니다. 잘못되거나 누락된 관리자
  credential은 DB 장애 중에도 기존 `401/403` 거절을 유지합니다.

## 8. 저장 모델·Telegram·Compose 계약

migration `b8d4e6f1a2c3`은 `api_rate_limit_windows`를 추가합니다. 기본 키는
`(policy_key, subject_hash, window_started_at)`이고 PostgreSQL 시각과
`INSERT ... ON CONFLICT DO UPDATE`로 요청 수와 거절 수를 원자적으로 집계합니다. window는 24시간 뒤
정리되는 일시적 운영 카운터이며 append-only 감사 로그가 아닙니다.

`subject_hash`는 최소 32바이트의 독립 `RATE_LIMIT_SUBJECT_SECRET`과 고정 policy/principal을
HMAC-SHA256한 값입니다. raw 관리자 토큰, Telegram user ID, client IP, header, URL path, query는
요청 제한 DB나 제한 오류 로그에 저장하지 않습니다.

Telegram polling은 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ALLOWED_USER_ID`가 모두
유효할 때만 활성화합니다. 명령 실행 전 chat ID와 `message.from.id`를 함께 검증하고 bot sender,
`sender_chat`, sender가 없는 update와 상태 변경 `edited_message`를 거부합니다.

003B에서 FastAPI `/openapi.json`을 비활성화한 뒤에도 `docker-compose.local.yml`의 backend
healthcheck가 이를 계속 조회해 backend가 unhealthy가 되는 회귀를 발견했습니다. healthcheck를 공개
`/api/health`로 변경하고 기존 ingress 보안 테스트에 정적 회귀 검사를 추가했습니다.

## 9. 검증 상태

P1-003C는 **로컬 PostgreSQL 16·전체 회귀 완료 / 원격 CI 미실행** 상태입니다.

- 이미지 `postgres:16-alpine`, PostgreSQL 16.12, digest
  `sha256:97ff59a4e30e08d1c11bdcd9455e7832368c0572b576c9092cde2df4ae5552a3`
- 빈 DB head upgrade, `b8d4e6f1a2c3` → `f6b2c9d4e8a1` downgrade → head 재업그레이드,
  `alembic check`, 단일 head/current 통과
- PostgreSQL marker `73 passed`; 신규 limiter PostgreSQL 테스트 9개는 재업그레이드 전후 각각 통과
- backend 비-PostgreSQL `451 passed`, backend 합계 `524 passed`, Ruff 통과
- 보안·migration 대상 회귀 `98 passed`, 마지막 보안 hardening 대상 `89 passed`
- frontend `54 passed`, ESLint·production build 통과; 기존 500KB chunk 경고 유지

Windows Docker fsync 지연으로 기존 PostgreSQL 테스트의 2~5초 대기를 30초로 늘리고 취소 phase
테스트를 bounded refresh로 수정했습니다. 이는 느린 로컬 Docker에서도 같은 조건을 관측하기 위한 테스트
안정화이며 운영 코드는 변경하지 않았습니다.

실제 Slack·Telegram·Upbit·Gemini/OpenAI, 운영 DB, 원격 CI, git push와 Docker Compose 전체 기동은
실행하지 않았습니다. 상세 실행 증거는
[P1-003C 검증 보고서](../reviews/2026-07-13-p1-003c-verification.md)에 기록합니다.

## 10. 잔여 위험과 후속 범위

- Caddy shared-ingress rate-limit plugin은 아직 설치·버전 고정·검증하지 않았습니다. PostgreSQL
  limiter는 애플리케이션 진입 뒤의 의미 기반 제한이며 ingress 앞단의 volumetric 방어를 대체하지
  않습니다.
- 만료 window 정리는 현재 제한 판정 SQL의 hot path에서 수행됩니다. 대량 backlog나 장시간 lock
  보유에 대비한 bounded DB timeout 또는 별도 정리 작업은 후속 범위입니다.
- fixed-window는 AI·backtest 같은 장시간 작업의 동시 실행 수를 제한하는 분산 lease/semaphore가
  아닙니다. 장기 작업 lease는 후속 범위입니다.
- Telegram에는 bot별 poller lease와 `(bot_scope, update_id)` durable receipt가 없습니다. 현재는 단일
  backend poller 운영 전제이며 다중 worker exactly-once와 crash replay 방지는 후속 범위입니다.
