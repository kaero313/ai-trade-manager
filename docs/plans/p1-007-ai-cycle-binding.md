# ATM-P1-007 AI cycle 분석 ID 고정 계획·구현 기록

> 기준: 실제 `origin/main` 커밋 `7895f7b`
> 선별 구현 브랜치: `codex/p1-007-origin-main-two-commits`
> 상태: 로컬 backend 전체 회귀 완료 / 원격 CI 미실행

## 1. 문제와 목표

기존 분석 저장 함수는 DB commit 실패를 rollback·로그만 남기고 호출자에게 전달하지 않았습니다.
scheduler와 수동 AI Cycle은 그 뒤에도 executor를 호출했고, executor는 해당 cycle의 분석이 아니라
종목별 최신 `AIAnalysisLog`를 다시 조회했습니다. 새 분석 저장 실패나 같은 종목의 동시 분석에서
과거 BUY·SELL 분석이 현재 cycle의 실행 입력으로 바뀔 수 있는 구조였습니다.

P1-007은 다음 계약만 독립적으로 적용합니다.

- 분석 로그가 저장되고 ID가 확인된 경우에만 해당 cycle의 주문 평가를 시작합니다.
- `execute_ai_analysis()`는 저장된 `AIAnalysisLog`를 반환합니다.
- scheduler와 수동 AI Cycle은 그 행의 정확한 ID를 executor에 전달합니다.
- executor는 PK 단건 조회만 사용하고 ID 누락·미존재·종목 불일치를 fail-closed로 건너뜁니다.
- 실패한 scheduler 종목의 주문 실행은 0회이며 다음 종목은 독립적으로 계속합니다.

## 2. 구현 계약

1. `_persist_ai_analysis_log()`는 `add → commit → refresh → ID 확인`을 완료한 저장 행을 반환합니다.
2. commit·refresh·ID 확인 실패는 rollback과 오류 로그 후 호출자에게 재전파합니다.
3. `execute_ai_analysis()`의 반환형은 저장된 `AIAnalysisLog`이며 공개 분석 응답 필드는 유지합니다.
4. `execute_ai_trade(..., analysis_id=...)`는 유효한 양의 정수 ID만 받고 `AIAnalysisLog.id`로 조회합니다.
5. 전달된 행에 기존 stale, confidence, recommended weight, HOLD, EntryGate, BUY precheck와 paper/live 분기를 그대로 적용합니다.
6. 분석 ID가 없거나 조회되지 않거나 요청 symbol과 다르면 포트폴리오·precheck·주문 경로에 진입하지 않습니다.

## 3. 변경 범위

- `app/services/trading/ai_analyst.py`: 저장 실패 전파와 저장 행 반환
- `app/services/trading/ai_executor.py`: exact ID 조회와 identity 검증
- `app/core/scheduler.py`: 자동 cycle의 exact ID 전달
- `app/api/routes/ai.py`: 수동 cycle의 exact 저장 행·ID 사용
- 관련 단위·route·scheduler·architecture 회귀 테스트

DB schema는 변경하지 않으므로 Alembic migration과 `docs/DATABASE.md` 변경은 없습니다.

## 4. 제외 범위

- `AIAnalysisLog` provider/model/stage/fallback/parent/hash 계보와 migration
- BUY precheck reduce-only, risk health BUY veto, provider deadline, 뉴스 context
- 설정 SSOT와 frontend UI
- broker, 기존 주문 생성 경계와 거래 모드 안전장치 변경

## 5. 수용 기준

- 과거 BUY·SELL 로그가 있어도 새 분석 저장 실패 시 주문 실행 0회
- 분석 A 뒤에 B가 저장돼도 A cycle은 전달받은 A ID만 실행
- ID 누락·미존재·종목 불일치 시 주문 경로 진입 0회
- 정상 BUY·SELL·HOLD에서 exact ID와 기존 stale·confidence·EntryGate 유지
- scheduler와 수동 AI Cycle의 모든 production 호출이 `analysis_id=`를 명시
- 공개 AI 분석 응답과 기존 주문 안전 경계 유지

검증 결과는 [P1-007 로컬 검증 보고서](../reviews/2026-07-14-p1-007-verification.md)에 기록합니다.
