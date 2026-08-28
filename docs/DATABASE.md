# AI-Trade-Manager 데이터 모델 노트

이 문서는 현재 운영 데이터가 어디에 저장되고, 어떤 기준으로 복구되는지 정리합니다.

## 1. 저장소 역할

| 저장소 | 역할 | 복구 기준 |
|---|---|---|
| PostgreSQL | 실주문 제어·감사, 주문 의도, 청산 operation, API 요청 제한 window, 체결 이력, 포지션, 설정, AI 판단, 채팅, 포트폴리오 스냅샷의 기준 저장소 | 백업과 마이그레이션 |
| OpenSearch | RAG 뉴스 검색과 수집 상태 관측용 캐시 | 필요 시 재수집 |
| 환경변수 | 거래소, AI 제공자, Slack·Telegram, 관리자 인증·요청 제한 비밀값 | 운영 환경에서 별도 관리 |

## 2. 주요 데이터

| 데이터 | 용도 |
|---|---|
| 자산 | 거래 가능한 종목과 감시 여부 |
| 포지션 | 현재 보유 상태와 평균 진입가 |
| 주문 의도 | 거래소 제출 전후 상태, identifier, 요청값, 조회·복구 상태 |
| 거래 모드 제어 원장 | 계정 전체 paper/live 현재 상태, version, 변경 감사 event |
| 실주문 제어 원장 | 계정별 신규 주문 허용 범위, generation, 청산 operation 연결, 변경 감사 event |
| 주문 이력 | BUY, SELL 체결 기록과 연결된 AI 판단 |
| 청산 operation | REST 계정 전체 청산 멱등 키, phase·lease, 최초/취소 후/최종 계좌 증거, 주문·잔여 요약 |
| 청산 취소 원장·event | operation별 `wait/watch` 취소 상태와 append-only 단계·관측 감사 기록 |
| API 요청 제한 window | 고정 policy·principal별 PostgreSQL fixed-window 요청 수와 거절 수 |
| 봇 설정 | 봇 실행 여부, 런타임 상태, legacy/연구 전략 프로필과 프로필 version |
| 시스템 설정 | 분류된 운영 설정·내부 상태·보호 mirror와 행별 version |
| 관심 종목 | 사용자가 추적하는 종목 |
| AI 분석 로그 | BUY, SELL, HOLD 판단과 근거, 이후 정확도 평가 |
| 채팅 세션과 메시지 | AI 뱅커와 포트폴리오 미니챗 기록 |
| 포트폴리오 스냅샷 | 시간대별 총자산, 손익, 보유 구성 |

## 3. 운영 설정

시스템 설정은 스키마를 자주 바꾸지 않고 운영값을 조정하기 위한 versioned 키-값 저장소입니다.

| 범위 | 예시 |
|---|---|
| 매매 안전 정책 | 거래 모드, 실거래 매수 잠금, 관측 모드, 최소 확신도, 진입 게이트 |
| 스케줄 | 뉴스 수집, AI 자율 분석, 시장 심리 갱신 |
| AI 제공자 | 목적별 모델, 제공자 우선순위, 대체 경로 정책 |
| RAG 비용 제어 | 정기 수집과 BUY 직전 최신화의 비용 허용 범위 |
| Slack 알림 | 포트폴리오, 공포지수, 관심종목 AI 신호, 가격 영향 뉴스 알림 규칙 |

### `bot_configs`

- `config_json`은 Strategy Laboratory와 구버전 호환을 위한 legacy/연구 프로필입니다. 운영 AI 대상,
  Entry Gate와 주문 sizing의 권위값이 아닙니다.
- `is_active`는 자율 분석·하드 TP/SL 런타임의 실행 여부를 저장합니다.
- `runtime_last_heartbeat`, `runtime_last_error`, `runtime_latest_action`, `runtime_updated_at`은 5초
  heartbeat와 최근 런타임 상태를 별도 컬럼에 저장합니다. runtime writer는 `config_json`이나
  `config_version`을 갱신하지 않습니다.
- `config_version`은 1 이상의 값이며 `/api/config` legacy/연구 프로필 저장의 CAS 토큰입니다. GET은
  `ETag`와 `X-Config-Version`을 반환하고 POST는 같은 version의 `If-Match`를 요구합니다. 헤더 누락은
  `428`, stale version은 `409`입니다.

### `system_configs`

모든 행은 1 이상의 `version`을 갖습니다. 외부 변경 payload는 각 키의 `expected_version`을 반드시
포함하고, 중앙 설정 서비스가 정렬된 `SELECT ... FOR UPDATE`와 단일 트랜잭션으로 여러 키를 원자적으로
갱신합니다. 값이 바뀐 행과 내부 상태 writer는 version을 증가시킵니다.

| 분류 | 의미 | 예시 |
|---|---|---|
| `PUBLIC_MUTABLE` | REST·AI Banker 승인·Telegram의 공통 검증 서비스로 변경 가능 | 매매 대상, 주문 한도, 스케줄, AI/RAG/Slack 정책 |
| `INTERNAL_STATE` | 애플리케이션 내부 writer 또는 제한된 전용 reset만 변경 | paper KRW 잔액, 시장 심리 snapshot, provider runtime 상태 |
| `DEDICATED_PROTECTED` | P0 안전 서비스만 변경 | `trading_mode` mirror, `live_order_v2_enabled` |
| `LEGACY_READ_ONLY` | 호환 조회만 허용하고 신규 외부 저장 금지 | `autonomous_ai_interval_hours` |

외부 요청은 registry에 없는 키를 만들 수 없습니다. startup seed는 누락된 행만 version 1로 추가하고
이미 존재하는 운영값을 자동 교정하지 않습니다. `ai_provider_status`는 일반 다중 설정 payload에서
변경할 수 없으며 version을 요구하는 전용 reset API만 빈 상태로 초기화합니다.

마이그레이션 `d5e8a1c4b7f2`는 `c7a1e9d4f2b6`의 직접 자식입니다. 기존
`metadata.runtime_status`만 runtime 컬럼으로 옮기고 metadata의 다른 키는 보존합니다. legacy 시각이
PostgreSQL 16의 timestamp 입력 검증을 통과하지 못하면 해당 runtime 시각만 `NULL`로 격리합니다.
downgrade는 컬럼 값을 `metadata.runtime_status`로 재구성한 뒤 version·runtime 컬럼을 제거합니다.
현재 migration의 offline upgrade/downgrade SQL과 단일 head는 검증했으며 실제 PostgreSQL 16
backfill·제약·왕복 검증은 대기 상태입니다.

실주문 기능 플래그 `live_order_v2_enabled`는 기본값 `false`인 배포 퓨즈입니다. 값이 정확히 `true`여도
전역 실주문 제어와 봇 런타임 조건을 별도로 통과해야 하며 reconciliation은 플래그와 관계없이 계속
실행합니다.
마이그레이션 `e7b4c9a1d2f6`은 기존 PostgreSQL에도 이 키를 `false`로 멱등 삽입합니다.

이 키와 `trading_mode`는 보호 설정입니다. 일반 `/system/configs` 갱신과 AI Banker 설정 승인 경로는
변경 요청을 `409`로 거절합니다. 애플리케이션은 인증 장애 시 퓨즈를 `false`로 내릴 수 있지만,
일반 설정 API로 다시 켤 수 없습니다. `system_configs.trading_mode`는 권위값이 아니라 구버전 혼합
배포용 mirror이며, `trading_mode_controls`와 정확히 일치하지 않으면 상태를 unavailable로 처리합니다.

## 4. 주문 안전 원장

### `trading_mode_controls`

- `id=1`인 단일 행이 계정 전체의 `paper` 또는 `live` 현재 상태와 version을 저장합니다.
- 변경 사유 코드·본문, source, actor, 변경 시각을 함께 보존합니다.
- 신규·migration 직후 기본 상태는 `paper`이고, 모든 `BotConfig.is_active`와 그 server default는 false입니다.
- 행 누락, 알 수 없는 값, legacy mirror 누락·불일치는 허용 상태로 해석하지 않습니다.

### `trading_mode_control_events`

- `INITIALIZED`, `LIVE_ENABLED`, `PAPER_CONFIRMED` 전환을 append-only로 기록합니다.
- 운영 전환은 UUID v4 `request_id`와 SHA-256 fingerprint를 unique하게 저장해 같은 요청을 멱등 재생합니다.
- live event의 `reauth_jti`는 unique이므로 하나의 관리자 재인증 proof를 두 전환에 사용할 수 없습니다.
- `(control_id, version)` unique 제약과 update/delete 차단 trigger가 전환 순서와 감사 불변성을 보장합니다.

마이그레이션 `c4f8a2d7e1b3`은 Gate `BLOCK_ALL`, rollout OFF, 활성 청산·blocking intent 없음이라는
안전 preflight 아래 두 테이블을 만들고, 기존 raw mode를 초기 event의 감사 필드에 남긴 뒤 원장과
mirror를 `paper`, 모든 봇을 inactive로 고정합니다. 기존 explicit live도 보존하지 않습니다.
downgrade 역시 paper/inactive/BLOCK_ALL, rollout OFF, 활성 청산·blocking intent 없음이 확인될 때만
허용하며 live를 복원하지 않습니다.

마이그레이션 `f6b2c9d4e8a1`은 ATM-P0-004 청산 증거 원장을 추가합니다. upgrade와 downgrade 모두
같은 실주문 advisory transaction lock, rollout OFF, 모든 Gate `BLOCK_ALL`, 활성 청산·활성 긴급 승인·
blocking intent 없음을 fail-closed preflight로 요구합니다. 기존 활성 operation 또는 `ACTIVE` 승인이
있으면 legacy backfill을 진행하지 않습니다. downgrade는 여기에 더해 v2 operation과 취소·event
데이터가 전혀 없어야 하므로 실제
ACCOUNT_ALL 청산 증거가 생성된 DB에서는 허용되지 않습니다.

### `order_intents`

- `intent_key`는 동일 업무 이벤트의 재호출을 식별하고, `request_fingerprint`는 요청값 변경을 차단합니다.
- `identifier`는 Upbit에 전달하는 32자 UUID4 hex이며 영구 삭제하거나 재사용하지 않습니다.
- 요청 금액과 수량, 거래소 체결 값은 `Numeric(38,18)`로 저장합니다.
- 제출 상태와 거래소 상태, 체결 투영 상태를 서로 다른 컬럼으로 관리합니다.
- `post_attempt_count`는 0 또는 1만 허용합니다.
- 시장별 blocking partial unique index와 계정별 blocking BUY index가 동시 주문 충돌을 차단합니다.
- `OrderHistory.order_intent_id` unique FK로 종결 체결을 정확히 한 번만 반영합니다.
- reconciliation lease와 version CAS가 stale worker의 상태 덮어쓰기를 차단합니다.
- `prepared_control_generation/mode`는 판단 준비 시점의 제어 상태를, `control_generation/mode/event`는
  실제 제출 승인 상태를 보존합니다. migration 이전 NULL snapshot은 제출 허가로 해석하지 않습니다.

제출 상태는 `PREPARED`, `SUBMITTING`, `ACCEPTED`, `REJECTED`, `UNKNOWN`, `ABANDONED`, `NO_ORDER_CONFIRMED`입니다. `UNKNOWN`은 시간 경과만으로 해제하지 않고 조회 이력과 운영자 확인을 거칩니다.

### `liquidation_operations`

- UUID v4 `idempotency_key`를 unique로 저장합니다.
- `(broker, account_scope)`의 활성 `PREPARING/IN_PROGRESS` operation은 PostgreSQL partial unique
  index로 최대 하나만 허용합니다.
- 신규 계약은 `contract_version=2`, `cancel_scope=ACCOUNT_ALL`, SHA-256 `request_fingerprint`를
  저장합니다. migration 이전 행은 `contract_version=1`, `LEGACY_NONE`, `TERMINAL`,
  `LEGACY_UNVERIFIED`로 보존합니다.
- phase는 `BLOCKING`, `DISCOVERING_ORDERS`, `CANCELING_ORDERS`,
  `RECONCILING_CANCELED_ORDERS`, `SNAPSHOTTING_TARGETS`, `SUBMITTING`, `WAITING_FILLS`,
  `VERIFYING`, `TERMINAL` 순서로 진행합니다. 활성 상태와 `TERMINAL` phase의 조합은 DB 제약으로
  차단합니다.
- `version`, `lease_until`, `next_run_at`, `retry_count`가 다중 worker claim과 지수형 재시도를
  지원합니다. 일반 오류 재시도 간격은 15초, 30초, 1분, 2분, 5분, 10분, 최대 15분입니다.
- 최초·미체결 취소 후·최종 계좌 snapshot과 각 관측 시각을 따로 저장합니다.
- `target_snapshot`은 취소 확인 후 확정한 최초 주문 대상 수량을 보존하며 이후 새 자산 때문에
  자동 확장하지 않습니다. `result_snapshot`, `cancellation_summary`, `order_summary`,
  `remaining_summary`는 API의 종목별 결과와 집계를 구성합니다.
- `verification_status`는 `PENDING`, `VERIFIED`, `ERROR`, `LEGACY_UNVERIFIED`를 구분합니다.
  terminal operation이라도 최종 계좌·미체결·Position 증거가 없는 legacy 행은 성공 증명으로
  해석하지 않습니다.
- terminal operation은 체결량 0, 양의 `balance/locked`, dust, 미지원 마켓, 원장 불일치를
  `COMPLETED`로 분류하지 않습니다.
- operation과 identifier 기록은 hard delete하지 않습니다.
- 비상청산 권한은 `ACTIVE`, `REVOKED`, `CLOSED`로 별도 저장하고 승인 generation과 감사 event를
  연결합니다. 구버전 operation은 migration 시 terminal이면 `CLOSED`, 나머지는 `REVOKED`입니다.

### `liquidation_order_cancellations`

- 하나의 operation에서 발견한 Upbit UUID마다 한 행을 저장하며 `(liquidation_operation_id,
  exchange_uuid)`를 unique하게 강제합니다.
- `MANAGED` 주문은 `order_intent_id` FK가 필수이고 `EXTERNAL` 주문은 FK가 없어야 합니다. 수동·외부
  주문 체결을 가짜 OrderHistory로 만들지 않기 위한 경계입니다.
- 상태는 `DISCOVERED`, `CANCELING`, `UNKNOWN`, `CONFIRMED`, `FAILED`입니다. 외부 DELETE 전에
  `CANCELING`, attempt와 90초 lease를 먼저 커밋합니다.
- `attempt_count`는 한 주문의 DELETE 요청을 최대 3회로 제한하고, 별도
  `reconcile_attempt_count`는 불확실한 취소 결과 조회 횟수와 15초~15분 backoff를 보존합니다.
  `executed_volume`, `remaining_volume`, 오류 코드·메시지와 발견·요청·조회·해결 시각도 함께
  저장합니다.
- operation·취소 행에는 hard delete 차단 trigger가 적용됩니다.

### `liquidation_operation_events`

- operation 생성, phase 전환, 주문 발견·취소 요청·해결, 계좌 관측, 대상 확정, 주문 제출·해결,
  최종 검증, 오류와 종결을 sequence 순서로 기록합니다.
- `(liquidation_operation_id, sequence)`가 unique하고 event의 update/delete는 trigger로 차단됩니다.
- event에는 당시 operation version, 이전·다음 phase, source·actor, 세부 JSON, 축약 오류를 남깁니다.

### `live_order_controls`

- `(broker, account_scope)`당 한 행이며 `ARMED`, `EXIT_ONLY`, `BLOCK_ALL` 중 하나입니다.
- `EXIT_ONLY`일 때만 하나의 활성 청산 operation을 연결할 수 있습니다.
- 주문 허용 범위가 바뀌면 generation이 증가하고, no-op을 포함한 mutation은 version이 증가합니다.
- `UPBIT/primary` 초기 행은 migration에서 `BLOCK_ALL`, generation/version 1로 생성됩니다.
- 행 누락이나 불일치 상태는 허용으로 해석하지 않습니다.

### `live_order_control_events`

- 제어 변경을 append-only로 기록하며 UUID v4 request ID와 SHA-256 fingerprint로 재요청을 식별합니다.
- 같은 키의 다른 payload, 이후 상태에 의해 supersede된 과거 arm 요청을 구분합니다.
- 청산 승인·폐기·종결 event는 대상 operation FK를 영구 보존합니다.

마이그레이션 `a91f3e7c5b2d`가 위 두 테이블과 기존 원장의 감사 필드를 추가합니다. downgrade는 같은
계정 lock key의 transaction-level advisory lock을 DDL transaction 종료까지 보유하며, 기능 플래그가
명시적으로 false이고 모든 control이 `BLOCK_ALL`이며 ACTIVE 청산 권한과 blocking intent가 없을 때만
허용합니다.

런타임 제출 배리어는 같은 고정 key의 PostgreSQL session-level advisory lock을 사용합니다. 일반 주문
준비·claim·POST는 shared lock, 런타임 시작·거래 모드 전환·정지·재무장·청산 권한 변경은 exclusive
lock으로 직렬화합니다.
shared lock은 POST가 끝날 때까지 전용 connection session에 귀속되지만 POST 구간에는 DB
트랜잭션을 열지 않습니다. 따라서 direct connection 또는 session pooling만 지원하며, transaction
pooling 방식의 PgBouncer는 지원하지 않습니다.

제어 변경은 exclusive lock 획득 뒤 영속 `SUBMITTING` intent도 확인합니다. 제어 차단은 이미
커밋됐지만 연결 유실 등으로 POST 종료를 확정할 수 없는 `SUBMITTING`이 남아 있으면 호출자는
`ORDER_GATE_DRAIN_PENDING`을 받고 성공으로 간주하지 않습니다. 해당 intent는 reconciliation으로
계속 조회하며 자동 재POST하지 않습니다.

## 5. AI 분석 감사 계보

### `ai_analysis_logs`

- `stage`는 `TRADE_ANALYSIS`, `BUY_PRECHECK`, `LEGACY_UNKNOWN` 중 하나입니다.
- `provider`, `model`, `prompt_version`은 비어 있을 수 없습니다. 신규 실제 응답은 선택된 provider와
  model을 기록하고, provider 응답 없는 합성 HOLD는 `SYSTEM / DETERMINISTIC_HOLD`를 사용합니다.
- `fallback_used`는 실제 호출한 첫 후보 성공이면 false, 앞선 호출 실패 뒤 성공 또는 합성 HOLD이면
  true입니다. migration 이전 행은 NULL입니다.
- `BUY_PRECHECK.parent_analysis_id`는 exact primary 행을 가리키는 self FK이며 삭제는 `RESTRICT`입니다.
  stage·symbol 일치는 서비스에서 fail-closed로 검증합니다.
- `context_sha256`는 실제 user prompt의 lowercase 64자 SHA-256만 허용하며 NULL은 legacy만을 위한
  호환 값입니다.
- `buy_precheck.v2` user prompt에는 최신화 상태와 최대 3건의 제한된 뉴스 snapshot이 각각 포함됩니다.
  DB는 뉴스 원문을 `ai_analysis_logs`에 복제하지 않고 그 exact canonical prompt의 hash를 보존합니다.
- `(symbol, stage, created_at)`와 parent 인덱스가 최신 primary 및 parent 귀속 조회를 지원합니다.

마이그레이션 `c7a1e9d4f2b6`은 기존 행의 stage/provider/model/prompt_version을 모두
`LEGACY_UNKNOWN`으로 보존하고 fallback/parent/context는 NULL로 둡니다. reasoning, 주문 연결이나
생성 시각으로 과거 provider·primary/precheck를 추정하지 않습니다. 신규 정확도·calibration은
`TRADE_ANALYSIS`만 사용하고, 주문이 `BUY_PRECHECK`에 연결되면 read-time에 parent primary로 성과를
귀속합니다. 주문 FK 자체는 실제 주문을 결정한 precheck 로그를 계속 보존합니다.

P1-010B는 `prompt_version`의 신규 값과 기존 `context_sha256` 의미를 확장해 사용하며 DB schema와
Alembic head를 변경하지 않습니다. 뉴스 snapshot은 `title`, 180자 이하 `summary`, `source`,
`published_at`, `link`만 포함하고 실제 검색 원본은 재수집 가능한 OpenSearch/RSS 계층에 둡니다.

## 6. API 요청 제한 공유 원장

### `api_rate_limit_windows`

다중 worker가 같은 제한 결정을 공유하는 운영 카운터입니다. 기본 키는
`(policy_key, subject_hash, window_started_at)`이며 `request_count`, `rejected_count`,
`last_seen_at`, 생성·갱신 시각을 함께 저장합니다. PostgreSQL `statement_timestamp()`와 `date_bin()`으로
window를 정하고 `INSERT ... ON CONFLICT DO UPDATE` 한 문장에서 요청 수를 원자적으로 증가시킵니다.
`request_count`는 무한 누적 총계가 아니라 현재 window에서 `limit + 1`로 포화되는 판정용 카운터이며,
초과 요청은 `rejected_count`에 별도로 누적합니다.

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

`subject_hash`는 최소 32바이트의 독립 환경변수 `RATE_LIMIT_SUBJECT_SECRET`과 고정된
policy/principal을 HMAC-SHA256한 64자 hex입니다. raw 관리자 토큰, Telegram user ID, client IP,
header, URL path, query는 이 테이블에 저장하지 않습니다. 비밀값 자체도 PostgreSQL이 아니라 운영
환경에서 관리합니다.

window는 24시간 뒤 정리되는 일시적 운영 상태이며 append-only 보안 감사 원장이 아닙니다. migration
`b8d4e6f1a2c3`의 downgrade는 테이블을 제거하므로 제한 카운터도 초기화됩니다. 장시간 작업의 분산
동시성 lease와 Telegram poller lease·durable update receipt는 이 모델에 포함되지 않습니다.

빈 PostgreSQL 16.12에서 head upgrade, `b8d4e6f1a2c3`에서 `f6b2c9d4e8a1`로 downgrade, head
재업그레이드, `alembic check`, 단일 head/current를 검증했습니다. 신규 limiter PostgreSQL 테스트 9개는
재업그레이드 전후 모두 통과했고 전체 PostgreSQL marker 73개도 통과했습니다. 상세 결과는
[P1-003C 검증 보고서](reviews/2026-07-13-p1-003c-verification.md)에 기록합니다. 현재 상태는
`로컬 PostgreSQL 16·전체 회귀 완료 / 원격 CI 미실행`입니다.

## 7. OpenSearch 데이터

| 데이터 | 용도 |
|---|---|
| 뉴스 검색 캐시 | RAG 뉴스 검색 데이터 |
| 수집 상태 관측 캐시 | 수집, 크롤링, 임베딩, AI 제공자 오류, 비용 추정 관측 |

OpenSearch는 주문이나 포지션의 원장이 아닙니다. 매핑이 바뀌면 재색인할 수 있고, 데이터가 비어도 PostgreSQL 운영 상태는 유지됩니다.

## 8. 스키마 변경 원칙

- PostgreSQL 테이블이나 컬럼을 바꾸면 Alembic 마이그레이션을 만듭니다.
- OpenSearch 매핑 변경은 PostgreSQL 마이그레이션 대상이 아닙니다.
- 운영 스위치와 반복 규칙은 가능한 한 시스템 설정으로 관리합니다.
- 비밀값은 데이터베이스에 저장하지 않습니다.
- 미확정 주문이 남아 있으면 코드 롤백 전에 거래소와 identifier 상태를 조정하고, 원장 migration을 즉시 downgrade하지 않습니다.
