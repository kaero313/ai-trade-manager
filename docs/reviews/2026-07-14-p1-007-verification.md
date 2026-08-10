# ATM-P1-007 로컬 검증 보고서

> 검증일: 2026-07-14
> 기준 커밋: `7a88359`
> 브랜치: `codex/p1-007-ai-cycle-binding`
> 상태: 로컬 backend 검증 완료 / 원격 CI 미실행

## 1. 구현 결과

- 분석 로그 `commit/refresh` 실패는 더 이상 성공으로 처리하지 않고 rollback 후 호출자에게 전파합니다.
- 저장된 `AIAnalysisLog.id`가 자동 scheduler와 수동 AI Cycle의 exact cycle identity가 됩니다.
- executor의 종목별 최신 분석 조회를 제거하고 전달된 PK 단건 조회로 교체했습니다.
- ID 누락·미존재·종목 불일치는 포트폴리오·precheck·주문 경로 전에 차단합니다.
- 실패한 scheduler 종목은 주문 없이 건너뛰고 다음 종목은 자체 ID로 계속 처리합니다.
- public 분석 응답의 `symbol`, `decision`, `confidence`, `recommended_weight`, `reasoning` 계약을
  유지했습니다.

## 2. 테스트 결과

| 검증 | 결과 |
|---|---|
| P1-007 targeted + 수동 cycle + executor + scheduler + architecture | `40 passed` |
| backend 전체 비-PostgreSQL | `469 passed, 73 deselected` |
| Ruff 전체 | 통과 |
| `git diff --check` | 통과 |

전체 비-PostgreSQL 회귀에는 `LiveOrderExecutionService`, 실주문 architecture, Kill Switch,
`BLOCK_ALL/EXIT_ONLY`, 거래 모드, 제출 배리어, reconciliation과 전량청산 회귀가 포함됩니다.

## 3. 검증 시나리오

- BUY 분석 commit 실패 시 rollback·예외 재전파
- 과거 BUY/SELL/BUY precheck 존재를 가정한 수동 cycle 저장 실패와 latest fallback 0회
- 첫 scheduler 종목 저장 실패 시 trade 0회, 다음 종목 exact ID 전달
- A/B 분석 중 B가 최신이어도 A ID 실행 시 A만 선택
- ID 누락·없는 ID·symbol 불일치 fail-closed
- exact BUY/SELL/HOLD, stale, confidence, EntryGate 유지
- public 분석 API 응답 필드 유지
- production `execute_ai_trade()` 호출의 명시적 `analysis_id=`와 latest fallback 부재 AST 검사

독립 Reviewer는 실제 persistence 실패 결합 경로와 exact-ID loader SQL 조건까지 재검토했으며, 기능
결함이나 P0 안전 경계 회귀를 발견하지 않았습니다. 초기 리뷰에서 지적된 테스트 mock 사각지대 두 건은
real `execute_ai_analysis()`와 real `_load_analysis_by_id()`를 호출하는 테스트로 보강했습니다.

## 4. 미실행·비변경 범위

- DB schema와 Alembic revision을 변경하지 않아 신규 PostgreSQL 전용 테스트와 migration 왕복은
  수행하지 않았습니다. Alembic head는 기존 `b8d4e6f1a2c3`을 유지합니다.
- frontend 변경이 없어 frontend test·ESLint·build는 재실행하지 않았습니다.
- 실제 Upbit, Gemini, OpenAI API와 운영 DB는 호출하지 않았습니다.
- 원격 push, PR, GitHub Actions는 실행하지 않았습니다.

## 5. 잔여 Delta

- provider/model/stage/fallback/parent/hash 계보와 primary/precheck 통계 분리는 P1-008 범위입니다.
- risk unhealthy/unknown 신규 BUY 차단은 조정된 우선순위에 따라 다음 P1-009 범위입니다.
- BUY precheck reduce-only, provider deadline, 실제 최신 뉴스 context는 각각 후속 P1-010A,
  P1-011, P1-010B 범위입니다.
