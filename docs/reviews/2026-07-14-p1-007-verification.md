# ATM-P1-007 로컬 검증 보고서

> 검증일: 2026-07-14
> 기준: 실제 `origin/main` 커밋 `7895f7b`
> 검증 브랜치: `codex/p1-007-origin-main-two-commits`
> 상태: 로컬 backend 검증 완료 / 원격 CI 미실행

## 1. 구현 결과

- 분석 로그 commit·refresh·ID 확인 실패를 rollback 후 호출자에게 전파합니다.
- 저장된 `AIAnalysisLog.id`가 자동 scheduler와 수동 AI Cycle의 cycle identity가 됩니다.
- executor의 종목별 최신 분석 조회를 제거하고 전달된 PK 단건 조회로 교체했습니다.
- ID 누락·미존재·종목 불일치는 포트폴리오·precheck·주문 경로 전에 차단합니다.
- 실패한 scheduler 종목은 주문 없이 건너뛰고 다음 종목은 자체 ID로 계속 처리합니다.
- 공개 분석 응답의 `symbol`, `decision`, `confidence`, `recommended_weight`, `reasoning`을 유지했습니다.

## 2. 테스트 결과

| 검증 | 결과 |
|---|---|
| P1-007 targeted·수동 cycle·executor 안전 회귀 | `32 passed` |
| backend 전체 | `140 passed` |
| Ruff `app tests` 전체 | 통과 |
| `git diff --check` | 통과 |

전체 회귀는 현재 `origin/main` 테스트 구성을 외부 API 없이 실행했습니다. 로컬 `.env.local`에는
기준 브랜치보다 최신인 설정 키가 있어 테스트 프로세스 동안만 파일을 격리하고 종료 시 원상 복원했습니다.

## 3. 검증 시나리오

- 분석 commit·refresh 실패와 refresh 후 ID 미확정 시 rollback·예외 전파
- 저장 실패 시 executor 호출 0회와 다음 scheduler 종목의 exact ID 전달
- A·B 분석 중 B가 최신이어도 A ID 실행 시 A만 선택
- ID 누락·없는 ID·symbol 불일치 fail-closed
- exact BUY·SELL·HOLD와 기존 stale·confidence·EntryGate 유지
- 수동 AI Cycle의 exact ID 전달과 기존 응답 필드 유지
- production `execute_ai_trade()` 호출의 명시적 `analysis_id=` 및 latest fallback 부재 AST 검사

독립 Reviewer는 exact ID 조회, 저장 실패 전파, scheduler·수동 cycle 전달, 공개 응답 유지와
범위 외 주문 경계 변경 부재를 검토했으며 차단 이슈 없이 승인했습니다.

## 4. 미실행·비변경 범위

- DB schema와 Alembic revision을 변경하지 않아 PostgreSQL migration 검증은 수행하지 않았습니다.
- frontend 변경이 없어 frontend test·ESLint·build는 재실행하지 않았습니다.
- 실제 Upbit, Gemini, OpenAI API와 운영 DB는 호출하지 않았습니다.
- 원격 push, PR, GitHub Actions는 실행하지 않았습니다.

## 5. 잔여 Delta

- risk unhealthy·unknown 신규 BUY 차단
- BUY precheck의 증액 금지
- AI provider deadline
- AI 분석 provider/model/stage/fallback/parent/hash 계보 migration
- BUY 직전 최신 뉴스의 immutable context 전달

이 항목들은 P1-007 선별 2커밋 범위에 포함하지 않습니다.
