# ATM-P1-010B 로컬 검증 보고서

> 검증일: 2026-07-14
> 브랜치: `codex/p1-010b-buy-news-context`
> 기준: P1-008 완료 상태
> 상태: 구현·로컬 backend 검증 완료 / 원격 CI·push 미실행

## 구현 결과

- live BUY precheck는 뉴스 최신화 뒤 실제 최신 또는 캐시/RSS 뉴스를 별도로 조회합니다.
- 최신화 성공·실패·비활성과 실제 뉴스 context를 분리하고, 최대 3건의 whitelist snapshot만
  provider prompt에 전달합니다.
- 기사 snapshot은 `title`, 180자 이하 `summary`, `source`, `published_at`, `link`만 포함합니다.
- canonical exact user prompt의 version은 `buy_precheck.v2`이며 P1-008 `context_sha256`가 prompt
  전체를 검증합니다. precheck의 exact primary parent도 유지합니다.
- 뉴스 부재나 검색 실패만으로 BUY를 자동 veto하지 않으며 기존 risk, Entry Gate, reduce-only,
  provider deadline, 중앙 주문·Kill Switch 경계를 유지합니다.
- schema, paper, SELL, frontend는 변경하지 않았습니다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| P1-010B 및 연관 targeted | `121 passed` |
| backend 비-PostgreSQL 전체 회귀 | `561 passed, 74 deselected` |
| Ruff | `All checks passed!` |
| `git diff --check` | 통과 |
| 독립 Reviewer | 승인, 차단·중요 이슈 없음 |
| PostgreSQL 테스트·migration | 스키마 변경이 없어 불필요 |
| frontend | 변경 없음 |
| 외부 Upbit/Gemini/OpenAI 호출 | 0건 |
| 원격 push·PR | 0건 |

## 수용 시나리오

- refresh 이후 검색, 검색 이후 provider 호출 순서를 검증합니다.
- refresh 성공·실패·비활성에서도 검색을 수행하고 새 뉴스 또는 기존 캐시/RSS 뉴스가 prompt에
  포함되는지 검증합니다.
- 최대 3건, summary 180자, whitelist 필드, 본문·검색 내부 메타데이터 제외를 검증합니다.
- 검색 0건·검색 오류가 deterministic veto가 되지 않는지 검증합니다.
- canonical exact prompt/hash와 `buy_precheck.v2`, exact primary parent를 검증합니다.
- paper·SELL·P1-007/P1-009/P1-010A/P1-011 및 P0 중앙 주문 경계 회귀를 검증합니다.

실제 OpenSearch/RSS/AI 통합 호출은 금지 조건에 따라 수행하지 않고 fake 경계로 검증했습니다. 뉴스
refresh·검색 전체 wall-clock 예산과 분산 risk scheduler는 기존 P1-011/P2 후속 범위로 유지합니다.
