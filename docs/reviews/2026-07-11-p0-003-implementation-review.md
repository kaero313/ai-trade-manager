# ATM-P0-003 fail-closed 거래 모드 구현 리뷰

> 검토일: 2026-07-11
> 최초 판정: 코드 구현 및 로컬 비-PostgreSQL 검증 완료 / PostgreSQL 16 최종 검증 대기
> 후속 상태(2026-07-13): 로컬 PostgreSQL 16.12 최종 검증 완료 / 원격 CI 미실행
> 원격 상태: CI 미실행, git push 미실행

## 1. 결론

기존의 누락·오염된 거래 모드를 live로 해석할 수 있던 fail-live 경로를 제거했습니다. 거래 모드의
PostgreSQL SSOT와 감사 원장, strict legacy mirror 검증, 전용 관리자 전환 API, 최종 Upbit POST 직전
live 재확인, React fail-closed 표시가 하나의 안전 경계로 연결됐습니다.

기본 상태는 `paper + inactive + BLOCK_ALL`입니다. live 전환 성공만으로 런타임이나 주문 Gate가
활성화되지 않으며, live 전환·런타임 시작·Gate 재무장은 각각 독립된 관리자 작업입니다. 따라서 현재
코드는 P0-003 구현 기준을 충족하지만, Docker PostgreSQL 16에서 경합과 migration 왕복을 확인하기
전에는 운영 실주문 활성화를 승인할 수 없습니다.

## 2. 구현 확인

### PostgreSQL 원장과 migration

- `trading_mode_controls` 단일 행이 paper/live 현재 상태와 version의 SSOT입니다.
- `trading_mode_control_events`는 초기화·live 전환·paper 확인을 append-only로 저장합니다.
- UUID v4 request ID, SHA-256 fingerprint, `(control_id, version)`, live 재인증 jti에 unique 제약을 둡니다.
- `system_configs.trading_mode`는 혼합 배포용 mirror로만 유지하며 누락·오염·불일치는 unavailable입니다.
- migration `c4f8a2d7e1b3`은 Gate `BLOCK_ALL`, rollout OFF, 활성 청산·blocking intent 없음이라는
  preflight를 통과한 뒤 기존 live를 보존하지 않고 mode를 paper, 모든 봇을 inactive로 강제합니다.
- downgrade도 safe preflight를 통과할 때만 허용하며 과거 live를 복원하지 않습니다.

### 관리자 전환 계약

- `GET /api/bot/trading-mode`가 mode, version, 변경 사유·주체·시각, 원장 가용성과 mirror 일치를 제공합니다.
- `POST /api/bot/trading-mode/live`는 UUID v4 `Idempotency-Key`, mode/Gate expected snapshot,
  10자 이상 사유, `ENABLE_LIVE_TRADING` 확인 문구와 5분 재인증 proof를 요구합니다.
- `POST /api/admin/reauth`는 저장된 브라우저 인증을 재사용하지 않고 명시적으로 다시 입력한
  `X-Admin-Token`을 검증합니다. request body에는 purpose만 전달합니다.
- proof는 별도 `ADMIN_REAUTH_SIGNING_SECRET`으로 서명하고 jti를 event에서 한 번만 소비합니다.
- `POST /api/bot/trading-mode/paper`는 권한 축소 경로로서 proof 없이 먼저 runtime과 Gate를 정지한 뒤
  control과 mirror를 같은 트랜잭션에서 paper로 전환합니다.

### 주문·런타임 통합

- 런타임 시작, 거래 모드 전환, Gate 전환은 같은 PostgreSQL advisory exclusive 배리어로 직렬화됩니다.
- live 전환은 rollout ON, runtime inactive, Gate `BLOCK_ALL`, 활성 청산 없음, blocking intent 없음,
  정상 paper 원장이라는 precondition을 재검증합니다.
- 중앙 주문 서비스는 준비와 최종 claim 모두에서 거래 모드 원장과 mirror가 정확히 live인지 확인합니다.
- mode 전환과 final claim이 경합해도 live 조건이 깨진 요청은 `PREPARED → SUBMITTING` 전에 차단되어
  Upbit POST를 수행하지 않습니다.
- 일반 설정 API와 AI Banker 설정 승인 경로는 `trading_mode`와 rollout 보호 키를 변경하지 못합니다.

### React와 분석 기능

- layout과 Bot Control은 누락·오염·loading·조회 실패를 live로 보정하지 않고
  `PAPER / UNAVAILABLE`로 표시합니다.
- Runtime / Trading Mode / Order Gate / Rollout을 별도 상태 축으로 표시합니다.
- live 전환 시 관리자 토큰 재입력을 강제하고, 성공 후 start/arm을 자동 호출하지 않습니다.
- Gemini/OpenAI 분석 기능은 유지됐습니다. paper 수동 AI Cycle은 기존 모의매매를 유지하고 live
  주문 평가만 정확한 live와 `ARMED` 상태를 요구합니다.

## 3. 로컬 검증 결과

Docker를 실행하지 않은 현재 환경에서 다음을 완료했습니다.

- backend 비-PostgreSQL: `303 passed, 56 deselected`
- Ruff: `app`, `tests` 통과
- frontend: `33 tests` 통과
- frontend ESLint와 production build 통과
- trading mode migration offline SQL과 단일 Alembic head 검사 통과

실제 Upbit API·키와 운영 DB는 사용하지 않았고 실주문 기능도 활성화하지 않았습니다. 원격 CI와 git
push도 수행하지 않았습니다.

## 4. 보류 항목과 운영 제한

PostgreSQL 전용 56개 테스트와 online Alembic 왕복은 Docker PostgreSQL 16이 준비되면 실행해야 합니다.
여기에는 다음 고위험 계약이 포함됩니다.

- 거래 모드 전환 8세션 경합과 event exactly-once
- start/mode/Gate advisory lock 직렬화
- mode 변경과 최종 Upbit POST claim 경합
- partial unique index, CAS, reconciliation, 청산 종결 exactly-once 회귀
- migration upgrade/downgrade/re-upgrade와 `alembic check`

이 검증이 모두 통과하고 control/mirror 일치, 장기 `SUBMITTING/UNKNOWN` 없음, rollout OFF,
runtime inactive, Gate `BLOCK_ALL`을 확인하기 전까지 live 전환과 실주문 활성화를 운영 완료로 간주하지
않습니다.

## 5. 최종 판정

P0-003의 구현 Delta와 비-PostgreSQL 회귀는 완료됐습니다. 남은 blocker는 코드 우회 대상이 아니라
실제 PostgreSQL 16의 동시성·migration 검증입니다. 다음 작업은 Docker가 준비된 뒤 P0-001/P0-002와
함께 PostgreSQL 전용 56개 테스트를 두 차례 실행하고 migration 왕복 결과를 기록하는 것입니다.

## 6. 2026-07-13 후속 검증

위 3~5절은 2026-07-11 당시의 판정과 테스트 수를 보존한 기록입니다. 후속 검증에서는 격리된 로컬
PostgreSQL 16.12에서 최신 marker 64개를 migration 왕복 전후 두 차례 모두 통과했습니다.
`alembic downgrade d3a9f7c1b2e4` 후 재업그레이드, `alembic check`, 단일 head와 최신
비-PostgreSQL backend `359 passed, 64 deselected`, Ruff 통과를 확인했습니다. 원격 CI와 git push는
실행하지 않았습니다.
