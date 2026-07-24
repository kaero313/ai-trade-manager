# ATM-P1-010B BUY 직전 최신 뉴스 context 계획·구현 기록

> 상태: 구현·로컬 backend 검증 완료 / 원격 CI 미실행
> 기준: P1-008 완료 브랜치 `codex/p1-008-ai-analysis-lineage`
> 스키마 변경: 없음

## 1. 발견된 Delta

- live BUY 직전 뉴스 최신화를 수행했지만 2차 LLM prompt에는 refresh 상태만 전달했습니다.
- 해당 시점의 실제 최신 또는 캐시 뉴스 내용이 precheck 판단과 `context_sha256`에 고정되지
  않았습니다.
- 최신화 실패·비활성과 검색 결과 부재를 구분하는 불변 context 계약이 없었습니다.

## 2. 구현 계약

- BUY precheck 직전 설정에 따라 뉴스 최신화를 먼저 시도합니다.
- 최신화 성공·부분 성공·실패·비활성 여부와 무관하게 해당 종목의 최신 또는 캐시/RSS 뉴스를 별도로
  조회합니다.
- 기사 snapshot은 최대 3건이며 `title`, 180자 이하 `summary`, `source`, `published_at`, `link`만
  허용합니다. 전체 본문, 검색 score, 내부 수집 메타데이터는 provider에 전달하지 않습니다.
- refresh 결과는 `buy_precheck_news_refresh`, 실제 판단 자료는 `buy_precheck_news_context`로
  분리합니다.
- 1차 분석 값, Entry Gate, 포트폴리오와 두 뉴스 값을 canonical user prompt에 고정합니다. prompt
  version은 `buy_precheck.v2`이며 P1-008 `context_sha256`는 provider에 전달한 exact prompt 전체를
  해시합니다. precheck 로그의 parent는 해당 cycle의 exact primary ID를 유지합니다.
- 뉴스가 없거나 조회가 실패한 사실은 context에 드러내지만 그 사실만으로 BUY를 자동 veto하지
  않습니다. 기존 LLM 판단과 모든 BUY 안전 경계가 최종 권위입니다.

## 3. 보존 경계

- P1-007 exact analysis ID와 P1-008 exact primary parent를 유지합니다.
- P1-009 risk fail-closed, P1-010A reduce-only, P1-011 provider deadline 순서를 바꾸지 않습니다.
- 중앙 `LiveOrderExecutionService`, 주문 intent·identifier·CAS, Kill Switch와
  `ARMED/EXIT_ONLY/BLOCK_ALL` 계약을 변경하거나 우회하지 않습니다.
- live BUY 전용 변경이며 paper, SELL, emergency liquidation, reconciliation 동작은 변경하지 않습니다.
- DB schema와 외부 REST API, frontend는 변경하지 않습니다.

## 4. 수용 기준

- refresh가 끝난 뒤 뉴스 조회, 그 뒤 provider 호출 순서가 보장됩니다.
- refresh 성공, 실패, 비활성 모두 실제 뉴스 조회를 수행하고 최신 또는 캐시/RSS snapshot을 prompt에
  포함합니다.
- 기사 수는 3건 이하이고 summary는 건당 180자 이하이며 허용하지 않은 본문·검색 내부 필드는
  prompt에 들어가지 않습니다.
- 뉴스 0건이나 검색 오류만으로 deterministic HOLD를 만들지 않습니다.
- 같은 snapshot과 cycle context는 같은 canonical exact prompt/hash를 만들고, 변경된 뉴스는 hash를
  변경합니다.
- precheck 로그는 `buy_precheck.v2`와 exact primary parent를 유지합니다.
- 관련 targeted, backend 비-PostgreSQL 전체 회귀, Ruff, `git diff --check`를 통과합니다.

검증 결과는 [P1-010B 로컬 검증 보고서](../reviews/2026-07-14-p1-010b-verification.md)에 기록합니다.
