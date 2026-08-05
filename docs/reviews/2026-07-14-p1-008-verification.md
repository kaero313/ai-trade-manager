# ATM-P1-008 로컬 검증 보고서

> 검증일: 2026-07-14
> 브랜치: `codex/p1-008-ai-analysis-lineage`
> PostgreSQL: 16.12 / `postgres:16-alpine` digest `97ff59a4e30e…`
> 상태: 구현·로컬 PostgreSQL 16·backend 검증 완료 / 원격 CI·push 미실행

## 검증 계약

- 승인된 7개 계보 필드와 `c7a1e9d4f2b6` migration
- legacy 무추정 backfill, stage/hash CHECK, parent self FK `ON DELETE RESTRICT`
- primary/provider fallback/합성 HOLD와 precheck parent/prompt/context hash
- executor·accuracy·calibration·self-correction primary-only
- latest primary 우선·legacy fallback·precheck 제외
- 주문 FK 보존과 precheck parent primary 성과 귀속
- P1-007/P1-009/P1-010A/P1-011 및 P0 중앙 주문 경계 회귀

## 검증 결과

| 검증 | 결과 |
|---|---:|
| P1-008 및 연관 targeted | `136 passed, 1 deselected` |
| PostgreSQL 16 marker 전체 | `74 passed, 544 deselected` |
| P1-008 PostgreSQL migration 재실행 | `1 passed, 4 deselected` |
| migration downgrade/re-upgrade | 통과 |
| `alembic check` | `No new upgrade operations detected.` |
| Alembic current/head | `c7a1e9d4f2b6` 단일 head |
| backend 비-PostgreSQL 전체 | `544 passed, 74 deselected` |
| Ruff | `All checks passed!` |
| `git diff --check` | 통과 |
| 독립 Reviewer | 승인, 차단·중요 이슈 없음 |

PostgreSQL 테스트는 별도 `atm-p1-008-pg16-test` 컨테이너와 전용 임시 볼륨에서 실행했습니다. 실제
운영 DB, Upbit, Gemini, OpenAI API는 호출하지 않았습니다.

## 남은 Delta

- migration 이전 legacy 행은 primary/precheck를 안전하게 구분할 근거가 없어, 신규 primary가 없는
  종목의 호환 최신 조회에서 과거 precheck가 노출될 수 있습니다. 임의 추정은 하지 않습니다.
- `context_sha256`는 무결성 값이지 원문 복원 수단이 아닙니다.
- 실제 BUY 직전 최신 뉴스 snapshot과 새 precheck prompt version은 다음 `ATM-P1-010B` 범위입니다.
- 원격 CI·push·PR은 실행하지 않았습니다.
