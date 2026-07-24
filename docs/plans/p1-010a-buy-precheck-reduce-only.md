# ATM-P1-010A BUY precheck reduce-only 계획·구현 기록

> 상태: 구현 완료 / 로컬 backend 회귀 검증 / 원격 CI 미실행
> 기준: P1-009 완료 커밋 `62aec73`
> 스키마 변경: 없음

## 1. 발견된 Delta

- live BUY 2차 LLM 검증 결과가 1차 분석의 `recommended_weight`를 대체했습니다.
- 주문 예산은 2차 비중과 시스템 상한만 비교해 2차 검증이 1차 비중보다 큰 값을 반환하면 주문
  비중이 증가할 수 있었습니다.
- 계산된 목표 예산이 5,000원보다 작아도 최소 주문액으로 올리는 동작이 비중 상한을 넘길 수
  있었습니다.

## 2. 구현 계약

- live BUY 최종 비중은 항상
  `min(1차 recommended_weight, 2차 recommended_weight, ai_max_buy_weight_pct)`입니다.
- 비유한 값이나 변환할 수 없는 비중은 0으로 처리해 주문하지 않습니다.
- 2차 LLM의 원본 응답과 precheck 로그는 감사 목적으로 보존하되, 주문 계산에서는 위 최솟값만
  사용합니다. 주문 intent와 `OrderHistory.ai_analysis_log_id`는 기존처럼 실제 precheck 로그를
  가리킵니다.
- system/user prompt에도 2차 검증은 BUY 차단 또는 축소만 가능하고 1차 비중을 초과할 수 없음을
  명시합니다. 코드의 최솟값 계산이 최종 권위입니다.
- live 목표 예산이 5,000원 미만이면 주문을 생략합니다. 정확히 5,000원이면 수수료 버퍼 계산 뒤
  5,000원 경계를 유지합니다.
- paper는 자체 primary 분석 비중을 같은 인자로 전달해 기존 계산 결과를 유지합니다.

## 3. 보존 경계

- P1-007 exact analysis ID, P1-009 BUY risk veto, confidence/stale/Entry Gate/live BUY 잠금 순서는
  바꾸지 않습니다.
- 중앙 `LiveOrderExecutionService`, 주문 intent·identifier·CAS, Kill Switch와
  `ARMED/EXIT_ONLY/BLOCK_ALL` 계약은 변경하지 않습니다.
- provider/model/stage 계보와 실제 뉴스 context는 각각 P1-008과 P1-010B 범위로 유지합니다.

## 4. 수용 기준

- `(primary, precheck, hard cap)`이 `(10,40,30)`, `(40,15,30)`, `(40,50,30)`일 때 각각
  `10`, `15`, `30`만 주문 예산에 사용합니다.
- live 목표 예산 4,000원은 주문 0회, 5,000원은 정확히 5,000원 주문입니다.
- remaining allocation, 가용 현금, 시스템 상한과 최소 주문 검사를 계속 적용합니다.
- paper BUY 결과와 SELL·청산·reconciliation 경계는 바뀌지 않습니다.
- backend 비-PostgreSQL 전체 회귀, Ruff, `git diff --check`를 통과합니다.

검증 결과는 [P1-010A 로컬 검증 보고서](../reviews/2026-07-14-p1-010a-verification.md)에 기록합니다.
