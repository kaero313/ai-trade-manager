# AI-Trade-Manager 아키텍처 노트

AI-Trade-Manager는 AI 판단을 바로 주문으로 연결하지 않고, 데이터 품질과 안전 조건을 확인한 뒤 실행 여부를 결정하는 개인용 트레이딩 운영 콘솔입니다.

## 1. 전체 구조

| 영역 | 역할 |
|---|---|
| 프론트엔드 | semantic dark/light AppShell 안에서 대시보드, 포트폴리오, AI 뱅커, 연구소, 설정 화면과 fail-closed 운영 상태 제공 |
| 백엔드 | API, 스케줄러, 매매 엔진, 메신저 봇 실행 관리 |
| PostgreSQL | 실주문 제어·감사, 주문 의도, 거래소 상태, 체결 이력, 포지션, API 요청 제한 window, 설정, AI 판단, 채팅, 포트폴리오 스냅샷의 기준 저장소 |
| OpenSearch | RAG 뉴스 검색과 수집 상태 관측용 캐시 |
| AI 제공자 | Gemini와 OpenAI 기반 분석, 임베딩, 대체 경로 처리 |
| 외부 연동 | Upbit 주문/시세, Slack/Telegram 알림·상태 조회와 비상 정지 |

## 2. 실행 흐름

1. 시장 데이터, 기술 지표, 포트폴리오, RAG 뉴스를 모읍니다.
2. AI가 BUY, SELL, HOLD 판단과 근거를 분석 로그로 커밋하고, 해당 호출에서 저장된 정확한 분석 ID를 cycle identity로 확정합니다. 저장 실패는 해당 종목 cycle을 중단합니다.
3. 실행 단계는 전달받은 ID로 분석 로그를 단건 조회하고 종목 일치를 검증한 뒤 확신도, 만료, 진입 게이트, 실거래 매수 잠금, 관측 모드를 다시 확인합니다. 종목별 최신 분석을 암묵적으로 대신 실행하지 않습니다.
4. BUY 후보는 직전 뉴스 최신화와 2차 검증을 거친 뒤에만 주문 후보가 됩니다.
5. 실주문은 PostgreSQL 거래 모드 원장·legacy mirror, 배포 퓨즈, 봇 런타임, 3상태 주문 Gate를 확인하고 주문 의도를 저장한 뒤 원자적으로 제출 권한을 획득한 실행자만 거래소에 한 번 전송합니다.
6. 주문 접수 여부가 불명확하면 같은 identifier로 조회하며 자동 재주문하지 않습니다.
7. 종결 주문의 실제 누적 체결량만 포지션과 체결 이력에 한 번 반영합니다.
8. 주문, 차단 사유, RAG warning, provider 상태는 운영자가 확인할 수 있게 남깁니다.

## 3. 핵심 화면

| 화면 | 목적 |
|---|---|
| 대시보드 | 시세, 포트폴리오, AI 판단, 봇 상태, 최근 체결 확인 |
| AI 뱅커 | 포트폴리오와 시장 상황을 멀티에이전트 방식으로 질의 |
| 연구소 | 전략 파라미터와 리스크 정책을 과거 데이터로 검증 |
| 설정 | 거래 모드, AI 제공자, RAG 비용 제어, Slack 알림 규칙 관리 |
| 포트폴리오 | 자산 구성, 손익, 스냅샷 기반 흐름 확인 |

### 3.1 프론트엔드 AppShell과 상태 사실성

프론트엔드는 Stitch 정적 목업을 직접 복사하지 않고 색상·정보 계층·레이아웃을 semantic token과
공통 `AppShell`로 재구현합니다. 고정 desktop sidebar는 펼침형과 아이콘 레일 사이를 전환하며 sidebar
폭, 본문 여백과 고정 Navbar offset을 같은 상태에서 함께 갱신합니다. 본문·Navbar·안전 배너의 최대 폭도
`1440px → 1600px`로 함께 바뀌어 회수한 160px를 실제 콘텐츠에 사용합니다. mobile drawer는 별도의
확장형 메뉴를 유지합니다. 본문 scrollport는 고정 Navbar 아래에서 시작하고, compact `ModeBanner`는
그 안의 `top: 0` sticky 영역으로 스크롤 전후 항상 Navbar 바로 아래에 남습니다. 이 셸은 기존 `/`,
`/portfolio`, `/chat`, `/laboratory`, `/settings` 경로와 Dashboard `?symbol=` deep link를 유지합니다.
dark/light theme는 같은 의미 토큰을 공유하며 원격 font·이미지 CDN이나 목업 데이터에 의존하지 않습니다.

Dashboard는 1024px부터 중앙 차트를 전체 폭에 먼저 배치하고 보조 패널과 운영 제어를 2열로 구성하며,
1536px부터 3열 운영 화면으로 전환합니다. `LIVE FLOW`처럼 실거래 모드로 오인할 수 있는 명칭 대신
`AI ACTIVITY`를 사용하고, 상단 Runtime과 중복되는 ENGINE 표시는 제거합니다. `ControlPanel`과
`BotControlPanel`은 넓은 하단 제어 영역으로 옮겨도 각각 한 인스턴스만 항상 mount합니다.

`Navbar`, Dashboard, Portfolio와 AI Banker는 하나의 순수 `PortfolioDataState` 판정을 공유합니다.
상태는 `live`, `snapshot`, `cached`, `error`, `empty`, `loading`으로 구분하며, cache가 없는 오류나
비유한 값은 0원 자산으로 렌더링하지 않습니다. cached refetch 오류는 마지막 값을 유지하되 stale·오류와
갱신 시각을 함께 표시합니다. portfolio가 unavailable이면 AI briefing과 채팅 전송을 frontend에서
차단하므로 장애 값을 정상 0원 context로 전달하지 않습니다.

화면 재배치는 domain controller를 조건부로 제거하지 않습니다. 봇·청산·수동 AI controller는
항상 mount되어 pending idempotency identity와 terminal snapshot을 보존합니다. 안전 조작 dialog는
focus trap, 최초 focus, Escape 취소, 배경 inert와 focus 복귀를 제공하고, HTTP 성공이나 주문 접수를
체결·청산 성공으로 축약하지 않습니다. AI Banker는 SSE `error`를 실패로 종결하고 exact
`current_value + expected_version` 승인 계약을 유지합니다.

Strategy Laboratory는 EMA/RSI/TP/SL/cooldown 기반의 결정론적 규칙 참고 전략입니다. 운영 LLM 전략을
과거 시점에 재현한 것으로 표시하지 않으며 AI provider/model은 결과 해설의 출처로만 취급합니다.

### 3.2 설정 SSOT와 변경 경계

설정이라는 이름의 데이터를 하나의 범용 JSON으로 취급하지 않습니다. 실제 소비자와 변경 권한에 따라
다음 저장소를 권위값으로 사용합니다.

| 범위 | SSOT | 변경 경계 |
|---|---|---|
| 운영 매매 대상·Entry Gate·주문 한도·스케줄·AI/RAG/Slack 정책 | 분류된 `system_configs` 행 | 중앙 `SystemConfigService` |
| 봇 실행 여부 | `bot_configs.is_active` | 봇 시작·정지 서비스 |
| heartbeat·최근 오류·최근 동작 | `bot_configs.runtime_*` 컬럼 | 런타임 상태 writer |
| 연구소·legacy 전략 프로필 | `bot_configs.config_json` | `If-Match` 기반 `/api/config` |
| 거래 모드 | `trading_mode_controls`와 append-only event | 전용 거래 모드 서비스 |
| 실주문 허용 범위 | `live_order_controls`와 append-only event | 전용 Kill Switch 서비스 |
| 배포·인증 장애 퓨즈 | 보호된 `live_order_v2_enabled` | P0 전용 내부 경계 |

`SystemConfig` registry는 각 키를 `PUBLIC_MUTABLE`, `INTERNAL_STATE`, `DEDICATED_PROTECTED`,
`LEGACY_READ_ONLY`로 분류합니다. REST·AI Banker 승인·Telegram `/setrisk`가 변경할 수 있는 범위는
`PUBLIC_MUTABLE`뿐입니다. provider 상태, paper 잔액과 시장 심리 snapshot은 내부 writer만 변경하고,
거래 모드와 실주문 퓨즈는 일반 설정으로 되돌리지 않습니다. 알 수 없는 키를 외부 요청으로 새로
생성할 수 없으며 startup seed는 누락된 행만 보충합니다.

외부 `SystemConfig` 변경은 모든 값을 먼저 canonicalize하고, 정렬된 행 잠금과 각 행의
`expected_version` 확인을 거쳐 한 트랜잭션에서 처리합니다. 여러 키 중 하나라도 stale·누락·무효이면
전체를 rollback합니다. `live_buy_enabled`와 `ai_entry_shadow_mode`처럼 서로 의존하는 키도 병합된 최종
상태를 같은 잠금 범위에서 검증합니다. 저장된 행은 각자 version이 증가하며, 스케줄러 reload가 커밋
뒤 실패하면 성공으로 위장하지 않고 `503`과 `saved=true`를 반환해 클라이언트가 최신 값을 다시
조회하게 합니다.

AI Banker는 제안 생성 시점의 version을 승인 payload에 고정합니다. Telegram `/setrisk`는
`max_allocation`, `max_buy_weight`, `max_positions`, `entry_score`, `min_confidence`만 같은 중앙 서비스로
변경하며 미지원·중복 항목이 하나라도 있으면 전체 요청을 거절합니다. AI provider runtime 상태는 일반
설정 payload로 초기화할 수 없고 `POST /api/system/ai/providers/status/reset`에 현재 version을 전달해야
합니다.

Settings UI는 실제 운영 소비자인 `ai_trade_target_symbols`, `ai_trade_excluded_symbols`,
`max_allocation_pct`, `ai_max_buy_weight_pct`, `ai_max_concurrent_positions` 등을 직접 표시합니다.
각 키의 `expected_version`은 최초 편집 시점에 고정하며, 편집 중 query가 갱신되더라도 stale draft를 최신
version으로 재기반하지 않습니다. 기준 version 불일치는 API 호출 전에 draft를 폐기하고 최신 설정을 다시
조회하는 충돌로 처리합니다.
`allocation_pct_per_symbol`을 포함한 legacy BotConfig 프로필은 운영 설정 화면에서 제거하고 연구소의
참고 초기값으로만 읽습니다.

## 4. 안전장치

- 모의 거래와 실거래 모드를 분리합니다.
- 신규 실거래 매수는 기본적으로 잠그고, 관측 모드에서 먼저 확인합니다.
- AI 판단은 주문 명령이 아니라 실행 게이트의 입력입니다.
- scheduler와 수동 AI Cycle은 저장된 분석 ID를 명시적으로 전달하며, ID 누락·미존재·종목 불일치 시 fail-closed로 주문 평가를 끝냅니다.
- 매수는 확신도, 진입 게이트, RAG 품질, 포트폴리오 상태, 과거 판단 성과를 함께 봅니다.
- live 수동 AI Cycle도 기존 게이트를 우회하지 않으며, paper 수동 AI Cycle에는 실주문 Gate를 적용하지 않습니다.
- `live_order_v2_enabled`가 명시적으로 활성화되지 않으면 신규 실주문을 제출하지 않습니다.
- 거래 모드의 안전 기본값은 `paper`이고 신규 봇 런타임은 inactive, 주문 Gate는 `BLOCK_ALL`입니다.
- `trading_mode_controls`와 `system_configs.trading_mode` mirror가 모두 존재하고 정확히 일치할 때만 거래 모드 상태를 신뢰합니다.
- 봇 런타임과 주문 Gate를 분리합니다. `/bot/start`는 분석 런타임만 시작하며 Gate를 자동으로 `ARMED`로 바꾸지 않습니다.
- 주문 Gate는 일반 주문을 허용하는 `ARMED`, 하나의 승인된 청산 operation만 허용하는 `EXIT_ONLY`, 모든 신규 POST를 막는 `BLOCK_ALL`로 구성합니다.
- 같은 주문 의도는 영구 보존되는 32자 identifier를 사용하며 Upbit POST를 최대 한 번만 수행합니다.
- 미확정 주문은 같은 마켓 주문을 차단하고, 미확정 매수는 공유 KRW를 고려해 다른 신규 매수도 차단합니다.
- 전량청산은 계정 전체 `wait/watch` 주문 취소와 최종 계좌·Position 검증 증거가 없으면 성공으로 종결하지 않습니다.

## 5. 실주문 제어와 멱등 경계

거래 모드의 현재 상태는 PostgreSQL `trading_mode_controls` 단일 행이 SSOT이고,
`trading_mode_control_events`가 성공한 전환을 append-only로 보존합니다. 기존
`system_configs.trading_mode`는 혼합 배포 호환용 mirror일 뿐이며, 원장 누락·알 수 없는 값·mirror
불일치는 모두 effective `paper`와 unavailable 상태가 됩니다. 일반 설정 API와 AI Banker 채팅 승인
경로는 `trading_mode`와 `live_order_v2_enabled`를 변경할 수 없습니다.

거래 모드는 전용 `GET /api/bot/trading-mode`, `POST /api/bot/trading-mode/live`,
`POST /api/bot/trading-mode/paper` API로만 조회·전환합니다. live 전환은 UUID v4
`Idempotency-Key`, 현재 mode/Gate expected version, 10자 이상 사유, `ENABLE_LIVE_TRADING` 확인 문구,
5분짜리 관리자 재인증 proof를 모두 요구합니다. 재인증 proof의 jti는 전환 event에서 한 번만 소비합니다.
paper 전환은 권한 축소이므로 proof나 확인 문구 없이 멱등 키·expected version·사유를 요구하고 먼저
런타임과 Gate를 안전하게 정지합니다.

런타임 시작, 거래 모드 전환, 주문 Gate 전환은 같은 PostgreSQL session-level advisory exclusive
배리어로 직렬화됩니다. 따라서 live 전환 성공 뒤에도 런타임은 inactive이고 Gate는 `BLOCK_ALL`이며,
운영자가 시작과 재무장을 별도로 수행해야 합니다.

`LiveOrderExecutionService`가 AI BUY/SELL, 하드 TP/SL, REST 전량청산의 유일한 실주문 경계입니다.

1. 첫 shared 제출 배리어에서 현재 Gate를 확인하고 허용된 요청만 `OrderIntent(PREPARED)`와 제어 generation 스냅샷을 커밋합니다.
2. 최종 shared 제출 배리어에서 거래 모드 원장과 mirror가 모두 정확히 live인지, Gate와 generation이 유효한지 다시 확인하고 `PREPARED → SUBMITTING` CAS에 성공한 실행자만 POST합니다.
3. claim 트랜잭션을 닫고 shared session lock만 보유한 상태에서 Upbit POST를 최대 한 번 호출합니다.
4. 성공 응답은 `ACCEPTED`, 명시적 거절은 `REJECTED`, 접수 여부가 불명확하면 `UNKNOWN`으로 저장합니다.
5. reconciliation은 identifier GET만 수행하며 POST를 재실행하지 않습니다.
6. `done/cancel`에서 실제 체결가와 수량을 확인한 뒤 `OrderHistory`와 `Position`을 같은 트랜잭션으로 투영합니다.

제출 배리어는 PostgreSQL session-level advisory shared/exclusive lock입니다. 정지·재무장·청산 제어는
exclusive lock으로 기존 shared POST 구간을 drain하고, 제출은 shared lock으로 제어 변경과
직렬화합니다. POST 중 DB 트랜잭션은 열지 않지만 전용 DB connection은 유지하므로 운영 연결은
PostgreSQL direct connection 또는 session pooling이어야 합니다. transaction pooling 방식의
PgBouncer는 이 계약과 호환되지 않습니다.

Reconciliation 결과 저장은 claim 당시 version을 확인하고 90초 lease를 사용합니다. 관리자
`NO_ORDER_CONFIRMED` 처리도 별도 lease와 version CAS를 획득하므로 늦게 도착한 worker가 종결 상태를
되돌릴 수 없습니다. payload 불일치는 UNKNOWN/ERROR로 자원을 계속 차단하고 치명 로그와 Slack
운영 경보를 남깁니다.

계정 전체 전량청산 v2는 클라이언트 UUID v4 `Idempotency-Key`와 정확한 body
`{"scope":"ACCOUNT_ALL","confirmation":"CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL"}`로만 생성합니다.
같은 키의 다른 fingerprint는 `409`이며, 기존 `LIQUIDATE_ALL` 확인 문구는 P0-002 당시의 역사적
계약으로 현재 API에서는 `422`입니다. `POST /api/bot/liquidate`는 exclusive 배리어에서 operation과
`BLOCK_ALL`을 먼저 커밋하고 진행 중이면 `202`를 반환합니다. 응답 뒤 worker를 즉시 깨우며,
`GET /api/bot/liquidations/{id}`는 DB 상태만 읽고 취소·주문 같은 외부 mutation을 수행하지 않습니다.

청산 operation은 다음 phase를 PostgreSQL lease와 version으로 진행합니다.

`BLOCKING → DISCOVERING_ORDERS → CANCELING_ORDERS → RECONCILING_CANCELED_ORDERS → SNAPSHOTTING_TARGETS → SUBMITTING → WAITING_FILLS → VERIFYING → TERMINAL`

worker는 Upbit `primary` 계정의 모든 `wait/watch` 주문을 페이지 단위로 발견하고 봇 관리 주문과
수동·외부 주문을 함께 취소 원장에 기록합니다. 취소는 UUID 20개 단위로 외부 호출 전에 claim하며,
응답 유실이나 오류는 주문 조회로 판정합니다. 관리 주문의 취소 중 체결은 기존 OrderIntent
reconciliation과 exactly-once 투영을 마친 뒤에만 청산 대상을 확정합니다. Upbit 인증·권한·418
오류는 rollout 퓨즈 OFF와 `BLOCK_ALL`을 적용합니다.

잔고 응답은 모든 행을 strict `Decimal`로 검증합니다. Upbit의 `balance`는 이미 주문 가능한 수량이므로
`locked`를 다시 차감하지 않고 `balance` 자체를 매도 요청량으로 사용합니다. `locked`는 별도 잔여
증거이며, 5,000원 미만은 `DUST_REMAINING`, 활성 KRW 마켓이 없으면 `UNSUPPORTED_MARKET`으로 남깁니다.
주문 가능한 대상 snapshot만 `EXIT_ONLY`로 중앙 주문 서비스에 제출하고, snapshot 이후 새로 나타난
자산에 자동 2차 매도를 만들지 않습니다.

최종 검증은 미체결 주문을 다시 두 번 확인하고 계좌 전체와 live Position을 비교합니다. 모든 비-KRW
`balance/locked`가 0이고 모든 청산 intent가 종결·투영됐으며 Position 차이가 `1e-12` 이하일 때만
`COMPLETED + VERIFIED`입니다. dust·잠금·미지원 자산·주문 실패는 `PARTIAL`, 수동·외부 주문 체결이나
거래소 잔고와 Position 차이는 `LEDGER_MISMATCH`를 포함한 `PARTIAL`입니다. 내부 이력을 꾸며 맞추거나
자동 Position 보정은 하지 않습니다. 종결 상태와 관계없이 authorization을 닫고 Gate는 같은 exclusive
트랜잭션 경계에서 `BLOCK_ALL`로 복귀합니다. 기존 v1 종결 기록은 `LEGACY_UNVERIFIED`로 보존합니다.

주문/청산 복구 job은 애플리케이션 시작 시 한 번, 청산 POST 직후 즉시, 이후 15초 주기로 실행됩니다.
일반 OrderIntent 복구는 identifier GET만 수행하고, 청산 worker는 DB phase에 따라 취소·조회와 승인된
대상의 중앙 주문 제출을 진행합니다. Slack/Telegram은 청산 실행 명령을 제공하지 않고 상태 응답에
활성 operation의 phase와 잔여 수만 표시합니다.

`live_order_v2_enabled`는 일반 설정 API와 AI Banker 설정 승인 경로에서 변경할 수 없는 보호 키입니다.
인증·권한·IP·418 오류가 발생하면 이 퓨즈를 끄고 Gate를 `BLOCK_ALL`로 전환합니다. 반대로 켜는
공개 API는 제공하지 않으며 배포 검증과 운영자 재무장은 별도 단계입니다.

Gate가 `BLOCK_ALL` 또는 `EXIT_ONLY`여도 Gemini/OpenAI 분석 자체는 유지됩니다. paper 수동 AI
Cycle은 Gate와 무관하게 기존 모의매매를 수행하고, live 수동 AI Cycle만 정확한 live 상태와
`ARMED`를 요구합니다. `BotConfig.is_active=false`인 런타임 정지는 하드 TP/SL과 자율 AI 분석·집행을
모두 건너뛰지만, 실주문 reconciliation과 종결 체결 투영은 계속합니다.

자율 AI scheduler는 각 종목 분석 로그의 커밋이 성공한 경우에만 반환된 `analysis_id`로 집행을
호출합니다. 저장 실패 시 그 종목의 집행은 0회이며 다음 종목은 독립 cycle로 계속 처리할 수 있습니다.
수동 AI Cycle도 같은 반환 ID로 응답과 주문 평가를 구성하므로 동시 분석이 더 최신 로그를 저장해도
현재 요청의 분석이 바뀌지 않습니다. live BUY의 기존 2차 검증과 중앙 `LiveOrderExecutionService`
경계는 이 identity 전달 이후에도 그대로 적용됩니다.

자율 scheduler는 분석 루프 앞에서 하드 TP/SL과 포트폴리오 상태를 불변 `RiskCheckResult`로 평가하고
그 값을 해당 cycle의 모든 종목 실행에 전달합니다. 수동 AI Cycle의 BUY는 주문 부작용이 없는 동일
평가를 수행합니다. `HEALTHY` 또는 명시적으로 비활성화된 `DISABLED`만 신규 BUY를 허용하며, 평가
실패·stale 데이터·불완전한 가격/원가·비유한 설정은 `UNKNOWN`, TP/SL 임계값 도달은
`UNHEALTHY`로 처리합니다. executor는 이 상태가 누락되거나 `UNKNOWN/UNHEALTHY`이면 포트폴리오
재조회, Entry Gate, BUY precheck, 주문 제출 전에 BUY만 중단합니다. 기존 SELL, 하드 리스크 매도,
비상청산, reconciliation과 `ARMED/EXIT_ONLY/BLOCK_ALL` 판정은 이 BUY 전용 veto와 분리됩니다.

live BUY의 2차 LLM precheck는 veto/reduce-only 계층입니다. 원본 precheck 응답과 로그는 감사용으로
보존하지만 주문 sizing은 `min(primary weight, precheck weight, system hard cap)`만 사용합니다.
precheck가 더 큰 비중을 반환해도 primary보다 주문을 늘릴 수 없고, 계산된 live 목표 예산이 Upbit
최소 주문액보다 작으면 최소액으로 올리지 않고 중단합니다. 주문의 분석 연결은 실제 precheck 로그를
유지해 어떤 2차 판단이 주문으로 이어졌는지 추적합니다.

BUY precheck 직전 뉴스 최신화와 판단 context는 서로 다른 증거입니다. 최신화가 성공하거나 실패하거나
설정으로 비활성화되어도 최신 또는 기존 캐시/RSS 뉴스를 다시 조회하며, 조회 결과에서 `title`,
180자 이하 `summary`, `source`, `published_at`, `link`만 허용한 최대 3건의 snapshot을 만듭니다.
최신화 상태와 뉴스 snapshot은 각각 `buy_precheck_news_refresh`, `buy_precheck_news_context`로 1차
분석 값·Entry Gate·포트폴리오와 함께 canonical user prompt에 고정합니다. precheck 로그는 exact
primary를 parent로 유지하며, `buy_precheck.v2`의 `context_sha256`는 이 exact prompt 전체를
검증합니다. 뉴스 부재나 조회 장애는 context에 드러내되 그 사실만으로 자동 veto하지 않으며, 최종
판단은 기존 precheck와 P0 Gate를 계속 통과해야 합니다.

AI provider 호출은 목적별 application deadline을 갖습니다. primary 분석은 provider당 20초·전체
35초, BUY precheck는 OpenAI 단일 15초, 포트폴리오·뉴스 감성·백테스트 리포트는 provider당
20초·전체 35초, 채팅은 provider당 30초·전체 45초입니다. timeout은 rate limit으로 분류하지 않고
다음 허용 provider로만 전환합니다. 모든 primary provider가 실패하면 현재 cycle의 HOLD를 저장하고,
BUY precheck가 끝나지 않으면 BUY를 veto합니다. 외부 task 취소는 fallback으로 바꾸지 않고 그대로
전파합니다. 이 전체 예산은 provider 실행 구간을 뜻하며 후보 조회와 provider 상태 DB 기록 시간은
포함하지 않습니다.

`AIAnalysisLog`는 `TRADE_ANALYSIS`, `BUY_PRECHECK`, `LEGACY_UNKNOWN` stage를 구분합니다. 신규
primary와 precheck는 실제 성공 provider/model, 실제 호출 failover 여부, stage별 prompt version,
provider에 전달한 exact user prompt의 UTF-8 SHA-256을 저장합니다. precheck는 주문을 직접 결정한
로그로서 `OrderHistory`·intent 연결을 유지하고, `parent_analysis_id`로 exact primary를 가리킵니다.
provider 응답이 없어서 만든 HOLD만 `SYSTEM / DETERMINISTIC_HOLD`로 기록하며 실제 veto 응답은 원본
decision/confidence/weight/reasoning을 보존합니다.

실행 executor와 정확도·calibration·자기교정은 `TRADE_ANALYSIS`만 사용합니다. 최신 분석 API,
포트폴리오 briefing, 관심종목 신호는 신규 primary를 우선하고 아직 신규 primary가 없는 종목에만
`LEGACY_UNKNOWN`을 호환 조회하며 `BUY_PRECHECK`를 primary처럼 선택하지 않습니다. live BUY 성과는
주문 FK를 바꾸지 않고 조회 시 precheck parent primary에 귀속합니다. 채팅 감사 도구는 모든 stage와
계보를 표시합니다.

## 6. RAG와 관측성

- RSS/API 뉴스는 OpenSearch에 검색 캐시로 저장합니다.
- 검색은 벡터 검색과 키워드 검색을 함께 사용하고, 같은 기사는 중복 제거합니다.
- Gemini 임베딩 실패 시 OpenAI 대체 경로를 시도하고, 둘 다 실패하면 키워드 검색으로 낮춰 동작합니다.
- Gemini/OpenAI SDK 호출은 30초 application/HTTP 제한과 내부 자동 재시도 억제를 적용합니다. 뉴스
  번역은 provider별 제한 외에도 문서 한 건의 Gemini→OpenAI fallback 전체를 60초로 제한합니다.
- RAG 상태 API는 실뉴스 여부, 임베딩 누락, AI 제공자 오류, 대체 문서 여부를 경고로 보여줍니다.
- 정기 수집과 BUY 직전 최신화는 비용 정책을 다르게 적용합니다.
- BUY 직전 최신화 상태는 실제 기사 본문을 대신하지 않습니다. precheck는 최신화 뒤 별도 검색으로
  최대 3건의 제한된 snapshot을 만들며, 최신화 실패·비활성 시에도 기존 캐시/RSS 검색을 시도합니다.

## 7. 운영 원칙

- 백엔드는 단일 인스턴스 운영을 기본으로 봅니다.
- 일반 스케줄러 작업의 중복을 피하기 위해 단일 인스턴스를 기본으로 유지합니다. 주문 reconciliation은 DB lease와 version CAS로 중복 실행에 안전하게 동작합니다.
- provider deadline은 한 번의 LLM 지연을 제한하지만, 하드 TP/SL을 독립 worker로 분리하거나 다중
  scheduler lease를 제공하지는 않습니다. 해당 구조는 `ATM-P2-002`·`ATM-P2-003`에서 설계합니다.
- PostgreSQL은 복구 기준이고, OpenSearch 뉴스 데이터는 재수집 가능한 캐시입니다.
- 운영 인증은 웹 진입점 보호와 애플리케이션 관리 API 보호를 분리합니다. 인증 없이 허용하는 API는
  `GET /api/health`, 전체 공개 market GET, 일반 뉴스 목록 `GET /api/news/`뿐입니다. 계좌·주문·설정,
  포트폴리오, 관심종목, 채팅, AI/LLM 비용 작업, 백테스트와 봇 제어를 포함한 나머지 API는
  `require_admin_token` 경계를 통과합니다.
- React의 `AdminSessionGate`는 저장하거나 입력한 관리자 토큰을 `GET /api/admin/session`으로 검증한
  뒤에만 기존 layout과 query를 mount합니다. 따라서 앱 진입 때 여러 민감 query가 동시에 인증 실패하는
  것을 막습니다. 일반 API client뿐 아니라 raw chat SSE도 `X-Admin-Token`을 전송하며, `401/403`이면
  현재 요청 토큰과 저장 토큰이 같을 때만 저장 토큰을 폐기하고 전역 session invalidation을 발행합니다.
  Gate는 민감 화면을 즉시 unmount하고 수동 재인증 화면으로 돌아갑니다. 늦게 도착한 이전 요청의 거절은
  이미 교체된 새 토큰을 폐기하지 않습니다.
- FastAPI 자동 `/docs`, `/redoc`, `/openapi.json`과 OAuth redirect는 공개 allowlist 밖의 schema
  정찰 경로이므로 기본 비활성화합니다.
- `POST /api/slack/test`는 관리 API 경계에 포함됩니다. 대상 URL은 서버의 `SLACK_WEBHOOK_URL`로
  고정하며 요청 payload의 URL override와 알 수 없는 필드는 허용하지 않습니다. Slack 전송 오류는
  외부 응답 본문이나 webhook secret을 API 응답·로그에 전달하지 않습니다. 애플리케이션 logging은
  `httpx`·`httpcore`의 요청 URL·헤더 로그도 `WARNING` 이상으로 제한합니다.
- CORS는 `CORS_ALLOWED_ORIGINS`의 CSV allowlist만 사용합니다. wildcard, 비 HTTP(S) origin과 루트 `/`
  외 경로·query가 포함된 origin은 설정 단계에서 거부하고 `allow_credentials=false`를 유지합니다. 개발 Compose의
  frontend·backend·PostgreSQL·OpenSearch·Dashboards 포트와 native backend는 loopback에만 공개합니다.
- 모든 API route는 `HEALTH_EXEMPT`, 공개 market·뉴스, 관리자 DB·외부 조회, 고비용 작업, 상태 변경,
  안전 정지, 인증 실패 중 하나의 고정 policy로 분류됩니다. PostgreSQL `api_rate_limit_windows`는 서버
  시각 기준 fixed-window와 `ON CONFLICT` 원자 갱신으로 다중 worker의 결정을 공유합니다. policy별
  principal은 `public:global`, `admin:primary`, `auth-failure:global`로 고정하고 서버 secret과
  HMAC-SHA256한 subject hash만 저장합니다. raw 관리자 토큰·Telegram ID·IP·header·path·query는 요청
  제한 원장에 저장하지 않습니다.
- `GET /api/health`는 요청 제한을 적용하지 않아 PostgreSQL readiness를 계속 보고할 수 있습니다.
  `POST /api/bot/stop`, paper 전환, 주문 Gate 차단은 일반 상태 변경과 다른 `SAFETY_STOP` bucket을
  사용합니다. 분류되지 않은 route와 유효한 관리 요청의 요청 제한 DB 장애는 `503`으로 fail-closed합니다.
- 로컬 Compose backend healthcheck도 비활성화된 `/openapi.json`이 아니라 공개 `/api/health`를
  사용합니다.
- Telegram polling은 bot token, 허용 chat ID, `TELEGRAM_ALLOWED_USER_ID`가 모두 설정되어야
  활성화됩니다. update의 chat과 `message.from.id`가 각각 설정값과 일치해야 하며 bot sender,
  `sender_chat`, sender가 없는 update와 상태 변경 `edited_message`는 명령을 실행하지 않습니다. polling
  실패 로그에는 고정 event와 예외 타입만 남기고 예외 원문이나 traceback을 기록하지 않습니다.
- 현재 Caddy에는 shared-ingress rate-limit plugin을 추가하지 않았고 PostgreSQL limiter는 애플리케이션
  진입 뒤의 의미 기반 제한만 제공합니다. fixed-window는 AI·backtest 같은 장시간 작업의 분산 동시성
  lease를 제공하지 않으며, Telegram도 다중 poller lease와 durable update receipt가 없어 단일 backend
  poller 운영 전제를 유지합니다.
- P1-003C의 fixed-window migration·원자 경합과 전체 backend/frontend 회귀는 로컬 PostgreSQL 16.12에서
  완료했습니다. 현재 상태는 `로컬 PostgreSQL 16·전체 회귀 완료 / 원격 CI 미실행`입니다. 실제 Docker
  Compose 전체 기동은 실행하지 않았으며 상세 증거는
  [P1-003C 검증 보고서](reviews/2026-07-13-p1-003c-verification.md)에 기록합니다.
- React는 거래 모드 조회 실패·누락·불일치를 live로 보정하지 않고 `PAPER / UNAVAILABLE`로 표시하며, live 전환 때 저장된 관리 토큰을 재사용하지 않습니다.
- 실주문 제출 배리어가 사용하는 DB session의 수명은 최대 Upbit POST 시간과 정리 여유보다 길어야 하며, session lock을 임의로 끊는 pool·proxy timeout을 사용하지 않습니다.
