# ATM-P1-007 AI cycle 분석 ID 고정 계획·구현 기록

> 기준 브랜치: `codex/p1-003c-rate-limit-telegram-sender`
> 기준 커밋: `7a88359`
> 구현 브랜치: `codex/p1-007-ai-cycle-binding`
> 상태: 구현 및 로컬 backend 비-PostgreSQL 전체 회귀 완료 / 원격 CI 미실행

## 1. 문제와 목표

기존 분석 저장 함수는 DB commit 실패를 rollback·로그만 남기고 호출자에게 전달하지 않았습니다.
이후 scheduler와 수동 AI Cycle은 executor를 계속 호출했고, executor는 해당 cycle의 분석이 아니라
종목별 최신 `AIAnalysisLog`를 다시 조회했습니다. 따라서 새 분석 저장 실패나 같은 종목의 동시 분석에서
과거 BUY/SELL 또는 BUY 직전 검증 로그가 현재 cycle의 입력으로 바뀔 수 있었습니다.

P1-007의 목표는 다음과 같습니다.

- 분석 로그가 커밋·확인된 경우에만 해당 cycle의 주문 평가를 시작합니다.
- `execute_ai_analysis()`는 저장된 `AIAnalysisLog`를 반환합니다.
- scheduler와 수동 AI Cycle은 반환된 정확한 ID를 명시적으로 전달합니다.
- executor는 PK로 단건 조회하고 ID 누락·미존재·종목 불일치를 fail-closed로 건너뜁니다.
- 실패한 scheduler 종목의 주문 실행은 0회이고 다음 종목은 독립적으로 계속할 수 있습니다.

## 2. 구현 계약

1. `_persist_ai_analysis_log()`는 ORM 행을 생성하고 `add → commit → refresh`를 완료한 뒤 ID가 있는
   저장 행을 반환합니다.
2. 저장·refresh·ID 확인 실패는 rollback과 오류 로그 후 반드시 재전파합니다.
3. `execute_ai_analysis()`는 AI 응답 객체 대신 동일 필드를 가진 저장 `AIAnalysisLog`를 반환합니다.
   `/api/ai/test-analysis`의 기존 JSON 필드는 유지합니다.
4. `execute_ai_trade(..., analysis_id=...)`는 유효한 양의 정수 ID만 받고 `AIAnalysisLog.id` PK로
   조회합니다. 종목별 `created_at DESC` 최신 조회는 주문 경로에서 사용하지 않습니다.
5. stale, confidence, recommended weight, HOLD, EntryGate, live BUY lock, BUY precheck와 paper/live
   실행 분기는 exact 행에 기존 순서대로 적용합니다.
6. live BUY precheck가 승인 로그를 새로 저장해 주문 입력으로 사용하는 기존 동작과
   `LiveOrderExecutionService` 중앙 주문 경계는 변경하지 않습니다.

## 3. 제외 범위

- `AIAnalysisLog` provider/model/stage/fallback/parent/hash와 Alembic migration
- BUY precheck reduce-only, risk health BUY veto, provider deadline, 뉴스 context
- 설정 SSOT와 frontend UI
- 주문 intent, identifier, CAS, Kill Switch, `BLOCK_ALL`, `EXIT_ONLY`, 전량청산 계약

## 4. 변경 범위

- `app/services/trading/ai_analyst.py`: 저장 실패 전파와 저장 행 반환
- `app/services/trading/ai_executor.py`: exact ID 조회와 fail-closed identity 검증
- `app/core/scheduler.py`: 자동 cycle의 exact ID 전달
- `app/api/routes/ai.py`: 수동 cycle의 exact 저장 행·ID 사용
- 관련 unit, scheduler, route, architecture, P0 회귀 테스트

DB schema는 변경하지 않으므로 migration과 `docs/DATABASE.md` 변경은 없습니다.

## 5. 수용 기준

- 과거 BUY/SELL/precheck가 있어도 새 분석 저장 실패 시 주문 실행 0회
- 분석 A 이후 B가 최신으로 저장돼도 A ID cycle은 A만 실행
- ID 누락·미존재·종목 불일치 시 portfolio·precheck·주문 경로 진입 0회
- 정상 BUY/SELL/HOLD에서 exact ID와 기존 stale·confidence·EntryGate 유지
- scheduler와 수동 AI Cycle의 모든 production 호출이 `analysis_id=`를 명시
- 중앙 실주문 architecture와 P0 안전 경계 회귀 통과

검증 결과는 [P1-007 로컬 검증 보고서](../reviews/2026-07-14-p1-007-verification.md)에 기록합니다.
