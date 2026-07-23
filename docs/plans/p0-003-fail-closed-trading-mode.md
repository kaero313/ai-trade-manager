# P0-003 fail-closed 거래 모드 전환 계획 및 구현 결과

> 발견사항: `ATM-P0-003`
> 상태: 구현·로컬 회귀·PostgreSQL 16.12 최종 검증 완료 / 원격 CI 미실행
> 결정·실행 주체: 사용자와 Codex
> 선행 작업: `ATM-P0-001`, `ATM-P0-002`

## 1. 목표와 안전 불변식

- 신규·누락·오염된 설정은 절대로 실거래로 해석하지 않습니다.
- 기본 상태는 `paper + inactive + BLOCK_ALL`입니다.
- 거래 모드의 SSOT는 PostgreSQL의 단일 제어 행이며, 변경은 append-only 감사 event로 남깁니다.
- 일반 설정·AI 채팅 승인으로 거래 모드를 변경할 수 없습니다.
- live 전환, 런타임 시작, Gate `ARMED`는 서로 다른 관리자 작업입니다.
- live 전환 성공만으로 봇이나 실주문 Gate를 켜지 않습니다.
- 중앙 Upbit POST 경계는 제출 직전에도 거래 모드가 정확히 live인지 재검증합니다.
- Gemini/OpenAI 분석은 유지하며 paper·backtest 주문 동작은 변경하지 않습니다.

## 2. 구현 결과와 남은 검증 Delta

2026-07-11 구현으로 기존 fail-live Delta를 다음과 같이 제거했습니다.

- 거래 모드 기본값과 seed를 `paper`, 신규 `BotConfig.is_active`와 server default를 false로 변경했습니다.
- 누락·오타·원장/mirror 불일치는 effective `paper`와 unavailable 상태로 처리합니다.
- `trading_mode_controls` SSOT와 `trading_mode_control_events` append-only 감사 원장을 추가했습니다.
- 일반 `/system/configs`와 AI 채팅 승인 경로에서 `trading_mode` 변경을 보호했습니다.
- 중앙 주문 준비·최종 claim에서 거래 모드 원장과 mirror가 정확히 live인지 재검증합니다.
- React의 layout, Bot Control, 수동 AI Cycle 상태를 fail-closed로 바꾸고 저장된 관리자 토큰을 live
  재인증에 사용하지 않도록 했습니다.
- paper 수동 AI Cycle의 모의매매와 Gemini/OpenAI 분석 기능을 유지했습니다.

P0-001 중앙 주문 서비스와 P0-002 submission barrier를 재사용했습니다. 구현 Delta와 로컬
PostgreSQL 검증 Delta는 완료됐고, 원격 CI는 아직 실행하지 않았습니다.

## 3. 데이터 모델

### 3.1 `trading_mode_controls`

계정 전체 거래 모드의 단일 현재 상태를 저장합니다.

- `id=1` 고정, `mode IN ('paper', 'live')`
- `version >= 1`
- `reason_code`, `reason_text`, `changed_source`, `changed_actor_ref`
- `changed_at`, `created_at`, `updated_at`
- 초기값은 `paper`, version 1입니다.

### 3.2 `trading_mode_control_events`

성공한 전환을 삭제하지 않는 감사 원장으로 저장합니다.

- `control_id`, `version`, `from_mode`, `to_mode`, `action`
- `request_id` UUID v4와 `request_fingerprint` SHA-256 쌍
- `reason_code`, `reason_text`, `source`, `actor_ref`, `created_at`
- `(control_id, version)`과 `request_id`는 각각 unique입니다.
- 초기 migration event만 request pair가 `NULL`이며 운영 전환은 항상 UUID/fingerprint를 가집니다.

기존 `system_configs.trading_mode`는 구버전 혼재 배포를 위한 mirror로 유지합니다. 신코드는 제어 원장을
권위값으로 읽고, mirror가 누락되거나 제어 원장과 다르면 상태를 unavailable로 판정해 fail-closed합니다.

## 4. Migration 계약

새 migration은 P0-002 head 뒤에 적용합니다.

1. P0-002와 같은 advisory exclusive lock을 획득합니다.
2. `live_order_v2_enabled=false`, 모든 Gate `BLOCK_ALL`, 활성 청산 권한 0건, blocking intent 0건을
   확인합니다. 하나라도 위반하면 upgrade를 중단합니다.
3. 거래 모드 제어·event 테이블을 생성합니다.
4. 기존 원시 거래 모드 값을 감사 event에 남기고 제어 행을 `paper`로 초기화합니다.
5. legacy mirror를 `paper`로 upsert하고 모든 `BotConfig.is_active`를 false로 변경합니다.
6. `bot_configs.is_active`의 신규 행 server default를 false로 변경합니다.

기존 explicit live도 자동 보존하지 않습니다. 운영자는 새 코드 배포 후 전용 live 전환 API, 런타임
시작, Gate 재무장을 각각 다시 승인해야 합니다.

Downgrade는 mode paper, runtime inactive, Gate BLOCK_ALL, rollout OFF, 활성 청산·blocking intent가 없는
경우에만 허용합니다. 기존 행은 paper/inactive로 남기고 신규 테이블만 제거하며 live 상태를 복원하지
않습니다.

## 5. 서비스와 상태 계약

### 5.1 strict 조회

- 제어 행과 mirror가 모두 존재하고 정확히 일치할 때만 `state_available=true`입니다.
- 제어 행 누락·DB 오류·알 수 없는 mode·mirror 불일치는 effective `paper`와 unavailable 상태를
  반환합니다.
- 실제 매매 실행 경로의 strict 조회는 unavailable 상태에서 예외로 중단합니다.
- 포트폴리오와 UI는 오류를 live로 fallback하지 않습니다.

### 5.2 live 전환

`POST /api/bot/trading-mode/live`

- 관리자 토큰 재입력, UUID v4 `Idempotency-Key`, 10자 이상 사유가 필요합니다.
- 확인 문구는 `ENABLE_LIVE_TRADING`입니다.
- `POST /api/admin/reauth`가 5분짜리 purpose·jti 포함 proof를 발급하고 live 전환 event가
  `reauth_jti`를 unique하게 소비합니다. 저장된 브라우저 토큰은 재인증에 재사용하지 않습니다.
- proof 서명은 `ADMIN_API_TOKEN`과 분리된 `ADMIN_REAUTH_SIGNING_SECRET`을 사용합니다. 이 값이 없거나
  32자 미만·반복 패턴·placeholder·낮은 엔트로피이면 재인증 API 자체를 차단합니다.
- 요청에는 mode expected version과 Gate expected generation/version을 포함합니다.
- exclusive submission barrier 아래 다음 조건을 다시 확인합니다.
  - 현재 mode가 정상 paper
  - runtime inactive
  - rollout enabled
  - Gate `BLOCK_ALL`, 활성 청산 operation 없음
  - blocking intent 없음
- 성공 시 control과 mirror를 live로 같은 트랜잭션에서 바꾸고 event를 기록합니다.
- runtime과 Gate는 각각 inactive, `BLOCK_ALL`을 유지합니다.

### 5.3 paper 전환과 안전 복구

`POST /api/bot/trading-mode/paper`

- 관리자 토큰, UUID v4 `Idempotency-Key`, expected version, 10자 이상 사유가 필요합니다.
- 권한 축소 작업이므로 재인증 proof와 확인 문구는 요구하지 않습니다.
- 먼저 기존 P0-002 stop 경계로 runtime과 Gate를 정지합니다.
- 이어서 exclusive barrier 아래 control·mirror를 paper로 바꾸고 runtime inactive를 재확인합니다.
- 이미 paper지만 mirror가 손상된 경우에도 `PAPER_CONFIRMED` event로 안전 복구할 수 있습니다.
- `SUBMITTING` drain이 남으면 BLOCK_ALL은 유지하되 성공으로 표시하지 않고 재확인하게 합니다.

### 5.4 멱등성과 충돌

- 같은 key와 같은 fingerprint는 기존 결과만 재생합니다.
- 같은 key의 다른 payload는 `TRADING_MODE_IDEMPOTENCY_CONFLICT`로 차단합니다.
- 기존 요청 뒤 다른 전환이 적용됐으면 `TRADING_MODE_REQUEST_SUPERSEDED`를 반환합니다.
- expected version·Gate snapshot 불일치는 409이며 자동 재시도하지 않습니다.
- transport 오류만 같은 key와 같은 payload로 재시도합니다.

## 6. 주문·런타임 통합

- `get_trading_mode()`는 제어 원장과 mirror를 strict하게 검증합니다.
- 중앙 `LiveOrderSubmissionGateSnapshot`은 control mode와 mirror가 모두 live일 때만 일반·비상 POST를
  허용합니다.
- prepare 이후 mode가 바뀌어도 최종 claim에서 차단되어 Upbit POST는 0건입니다.
- `start_bot`은 거래 모드 전환·Gate 제어와 같은 advisory exclusive 배리어에서 직렬화되며 mode와 Gate를 변경하지 않습니다.
- paper 수동 AI Cycle은 Gate와 무관하게 기존 모의매매를 수행합니다.
- live 수동 AI Cycle은 mode live와 Gate `ARMED`일 때만 주문 평가를 수행합니다.

## 7. REST와 React 계약

- `GET /api/bot/trading-mode`: mode, version, 사유, 변경 주체·시각, availability를 반환합니다.
- `POST /api/admin/reauth`: 강제로 다시 입력한 관리 토큰을 검증하고 live mode 전환 전용 5분 proof를
  반환합니다.
- `BotStatus`에도 같은 거래 모드 상태를 포함해 5초 polling에서 일관되게 표시합니다.
- Bot Control은 Runtime / Trading Mode / Order Gate / Rollout을 별도 축으로 표시합니다.
- 누락·오염·조회 실패는 live로 표시하지 않고 `PAPER / UNAVAILABLE` 경고로 표시합니다.
- live 전환 modal은 저장된 관리 토큰을 재사용하지 않고 일회성 토큰 재입력을 요구합니다.
- live 전환 성공 뒤 start/arm API를 자동 호출하지 않습니다.
- `canArm`은 정상 live mode일 때만 true입니다.
- AI Banker의 generic `trading_mode` 승인은 비활성화하고 전용 운영 제어를 안내합니다.

## 8. 테스트와 완료 기준

- default seed와 신규 BotConfig가 paper/inactive입니다.
- 누락·오타·mirror 불일치·제어 행 누락은 주문 0건과 unavailable 상태가 됩니다.
- generic config·chat 경로의 `trading_mode` 변경은 409입니다.
- live 전환은 재인증·확인 문구·사유·멱등 키·expected snapshot을 모두 검증합니다.
- live 전환 후 runtime inactive, Gate BLOCK_ALL이 유지됩니다.
- paper 전환은 in-flight POST를 drain하고 이후 POST 0건을 보장합니다.
- 같은 요청 8세션에서 event와 전환은 정확히 한 번 적용됩니다.
- mode 변경과 최종 claim 경쟁은 advisory lock 순서로 선형화되며, paper 전환이 확정된 뒤에는 POST가
  발생하지 않습니다. 전환보다 먼저 선형화된 POST만 최대 한 번 허용됩니다.
- migration upgrade/downgrade/re-upgrade와 offline SQL, single head, `alembic check`를 검증합니다.
- frontend는 missing/invalid/loading을 live로 표시하지 않고, live 전환 재인증과 동일-key retry를
  검증합니다.
- paper manual cycle과 backtest 결과는 기존과 동일합니다.

2026-07-11 Docker 없이 backend 비-PostgreSQL `303 passed, 56 deselected`, Ruff, frontend
`33 tests`, ESLint, production build, migration offline 검증을 완료했습니다. 실제 PostgreSQL 전용
56개 테스트와 online Alembic upgrade/downgrade/re-upgrade는 P0-001/P0-002 미실행 항목과 함께 후속
실행합니다. 그 전에는 운영 실주문을 활성화하지 않습니다. 원격 CI와 git push는 실행하지 않았습니다.

2026-07-13 후속 검증에서는 로컬 PostgreSQL 16.12 marker 64개를 migration 왕복 전후 두 차례 모두
통과했습니다. `alembic downgrade d3a9f7c1b2e4` 후 재업그레이드, `alembic check`, 단일 head와 최신
비-PostgreSQL backend `359 passed, 64 deselected`, Ruff 통과를 확인했습니다. 원격 CI와 push는
실행하지 않았습니다.

## 9. 배포와 롤백

1. `live_order_v2_enabled=false`, Gate BLOCK_ALL, runtime inactive를 먼저 확인합니다.
2. 구버전 worker를 모두 drain한 뒤 migration을 적용합니다.
3. 새 코드를 배포하고 mode paper/inactive/BLOCK_ALL 및 mirror 일치를 확인합니다.
4. PostgreSQL·fault-injection·shadow 검증 뒤에만 live 전환을 별도로 승인합니다.
5. live 전환 후에도 runtime 시작과 Gate arm을 각각 별도로 수행합니다.

혼합 배포 중 신코드는 control/mirror 불일치를 차단하고, 구버전은 paper mirror를 읽으므로 live로
fallback하지 않습니다. downgrade나 코드 롤백은 safe preflight가 통과한 경우에만 수행합니다.
