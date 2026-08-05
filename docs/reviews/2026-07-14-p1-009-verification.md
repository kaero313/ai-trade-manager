# ATM-P1-009 로컬 검증 보고서

> 검증일: 2026-07-14
> 브랜치: `codex/p1-009-risk-buy-fail-closed`
> 기준 커밋: `7e7ef6c`
> 상태: 로컬 backend 검증 완료 / 원격 CI·push 미실행

## 구현 결과

- 자동 scheduler가 하드 TP/SL·포트폴리오 리스크 결과를 cycle-local 불변 값으로 보존해 exact
  analysis ID와 함께 executor에 전달합니다.
- 수동 BUY는 주문 부작용이 없는 현재 리스크 평가를 사용합니다.
- executor는 상태 누락, `UNKNOWN`, `UNHEALTHY`에서 신규 BUY를 포트폴리오·Entry Gate·BUY precheck·
  주문 이전에 중단합니다.
- SELL, 하드 리스크 매도, emergency liquidation, reconciliation과 P0 중앙 주문·Kill Switch 계약은
  유지했습니다.
- 손상·비유한·범위 이탈 설정, portfolio error/stale, 양수 자산의 가격·평균 매입가·손익 불확실성은
  fail-open하지 않고 `UNKNOWN`입니다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| P1-007 identity + P1-009 risk + scheduler/manual/live-order targeted | `64 passed` |
| backend 비-PostgreSQL 전체 회귀 | `497 passed, 73 deselected` |
| Ruff | 통과 |
| `git diff --check` | 통과 |
| PostgreSQL 테스트·migration | 스키마 변경이 없어 불필요 |
| frontend | 변경 없음 |
| 외부 Upbit/Gemini/OpenAI 호출 | 0건 |
| 원격 push·PR | 0건 |

## 독립 검토 반영

초기 구현 검토에서 비유한 TP/SL 설정이 `DISABLED`로 축약될 가능성과 평균 매입가가 없는 양수
보유 자산이 `HEALTHY`로 판정될 가능성을 발견했습니다. 명시적으로 유효한 `0/0`만 `DISABLED`로
허용하고 나머지는 `UNKNOWN`으로 수정했으며 NaN·범위 이탈·원가 누락 회귀 테스트를 추가했습니다.

남은 Delta는 `PortfolioService`가 malformed 원문 숫자를 0으로 정규화하기 전에 별도 health 증거를
보존하는 전반 계약이며 ATM-P1-005에서 처리합니다. 독립 리스크 scheduler와 분산 lease는
ATM-P2-002/P2-003 범위로 유지합니다.
