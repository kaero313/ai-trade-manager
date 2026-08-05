# ATM-P1-010A 로컬 검증 보고서

> 검증일: 2026-07-14
> 브랜치: `codex/p1-010a-buy-precheck-reduce-only`
> 기준 커밋: `62aec73`
> 상태: 로컬 backend 검증 완료 / 원격 CI·push 미실행

## 구현 결과

- live BUY sizing은 1차 분석 비중, 2차 precheck 비중, 시스템 hard cap의 최솟값만 사용합니다.
- 2차 provider 원본 응답과 precheck 로그는 그대로 보존하며 주문의 분석 FK도 기존 precheck 로그를
  유지합니다.
- 시스템·사용자 prompt에 reduce-only 권한을 명시했지만 최종 강제 권위는 코드의 최솟값 계산입니다.
- live 목표 예산 5,000원 미만은 주문 없이 중단하고, 정확히 5,000원인 경계는 유지합니다.
- paper, SELL, 청산, reconciliation과 P0 중앙 주문·Kill Switch 계약은 변경하지 않았습니다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| P1-007/P1-009/P1-010A targeted | `67 passed` |
| backend 비-PostgreSQL 전체 회귀 | `511 passed, 73 deselected` |
| Ruff | 통과 |
| `git diff --check` | 통과 |
| PostgreSQL 테스트·migration | 스키마 변경이 없어 불필요 |
| frontend | 변경 없음 |
| 외부 Upbit/Gemini/OpenAI 호출 | 0건 |
| 원격 push·PR | 0건 |

## 수용 시나리오

- `(primary, precheck, hard cap)=(10,40,30)`은 10%, `(40,15,30)`은 15%, `(40,50,30)`은
  30%만 실제 live request 금액에 반영했습니다.
- 4,000원 목표는 중앙 주문 서비스 호출 0회, 5,000원 목표는 정확히 5,000원 요청입니다.
- 기존 포지션 때문에 남은 allocation이 5,000원 미만인 경우와 가용 KRW가 5,000원 미만인 경우도
  주문 0회로 고정했습니다.
- paper BUY는 primary와 execution 분석을 같은 비중으로 전달해 기존 결과를 유지했습니다.

독립 검토에서 중요 결함이나 P0 경계 회귀는 발견되지 않았습니다.
