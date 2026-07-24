# ATM-P1-009 신규 BUY 리스크 fail-closed 계획·구현 기록

> 상태: 구현 완료 / 로컬 backend 회귀 검증 / 원격 CI 미실행
> 기준: P1-007 완료 커밋 `7e7ef6c`
> 스키마 변경: 없음

## 1. 발견된 Delta

- 하드 TP/SL 점검 실패와 포트폴리오 오류가 빈 종목 집합으로 축약되어 같은 AI cycle의 신규 BUY가
  계속될 수 있었습니다.
- scheduler는 하드 리스크 결과를 executor에 전달하지 않았고, 수동 AI Cycle은 BUY 직전 리스크
  상태를 평가하지 않았습니다.
- 부분 ticker 실패는 양수 보유 자산의 현재가를 0으로 만들 수 있고, 원가 누락은 손익률을 0으로
  만들 수 있어 이를 정상 상태로 취급하면 fail-open이 됩니다.

## 2. 구현 계약

- `RiskCheckResult`는 `HEALTHY`, `UNHEALTHY`, `UNKNOWN`, `DISABLED`와 근거·영향 종목·선제 청산
  종목을 담는 cycle-local 불변 값입니다. 프로세스 전역 운영 상태로 사용하지 않습니다.
- 유효한 hard TP/SL 설정이 정확히 `0/0`이면 `DISABLED`, 완전한 포트폴리오에서 임계값 미도달이면
  `HEALTHY`, 임계값 도달이면 `UNHEALTHY`입니다.
- 설정 조회·파싱·범위·유한성 실패, portfolio error/stale, 양수 non-KRW 보유 자산의 잔고·현재가·
  평균 매입가·손익 불확실성은 `UNKNOWN`입니다.
- scheduler는 하드 리스크 결과 또는 예외를 하나의 값으로 고정해 모든 종목 executor 호출에
  전달합니다. 수동 BUY는 주문 부작용이 없는 `evaluate_new_buy_risk_health()`를 사용합니다.
- executor는 BUY일 때만 상태를 요구하며, 누락·`UNKNOWN`·`UNHEALTHY`이면 포트폴리오, Entry Gate,
  BUY precheck, 주문 제출 전에 중단합니다. `HEALTHY/DISABLED`만 기존 BUY 흐름을 유지합니다.
- SELL, emergency liquidation, reconciliation은 이 BUY 전용 veto를 적용받지 않습니다. 하드 TP/SL
  매도와 AI 주문은 기존 `LiveOrderExecutionService`와 `GENERAL` 정책을 계속 사용합니다.

## 3. 제외 범위와 후속 Delta

- 독립 리스크 scheduler, 분산 lease, 다중 worker 조정은 ATM-P2-002/P2-003 범위로 유지합니다.
- `PortfolioService`가 malformed 원문 숫자를 0으로 정규화하기 전에 별도 health 증거를 보존하는
  전반적 계약은 ATM-P1-005에서 다룹니다.
- P0 Kill Switch, `BLOCK_ALL/EXIT_ONLY`, 주문 intent·identifier·CAS와 전량청산 계약은 변경하지
  않습니다.

## 4. 수용 기준

- 상태 누락·리스크 평가 실패·불완전 포트폴리오·TP/SL 도달에서 신규 BUY 주문은 0회입니다.
- `HEALTHY/DISABLED` BUY는 기존 confidence, stale, Entry Gate, live BUY 잠금, 중앙 주문 경계를
  그대로 통과합니다.
- 같은 `UNKNOWN` 상태에서도 SELL은 유지되고, emergency liquidation과 reconciliation 코드에는
  새 의존성이 생기지 않습니다.
- 자동 scheduler와 수동 AI Cycle이 exact analysis ID와 같은 cycle의 risk result를 함께 전달합니다.
- backend 비-PostgreSQL 전체 회귀, Ruff, `git diff --check`를 통과합니다.

검증 결과는 [P1-009 로컬 검증 보고서](../reviews/2026-07-14-p1-009-verification.md)에 기록합니다.
