# ATM-UI-001 Stitch 기반 전면 디자인 개편 계획·구현 기록

> 작성일: 2026-07-15
> 상태: Phase 0·UI 구현·로컬 회귀 완료 / viewport screenshot matrix·원격 CI 미실행
> 기준 브랜치: 로컬 `main` (`d2cc0b1`)
> DB·공개 API 변경: 없음
> 커밋·push·PR: 수행하지 않음

## 1. 목표와 기준 자료

Google Stitch가 생성한 다크 사이버-코퍼레이트 디자인을 현재 React/Vite 화면 전체에 적용하되,
기존 인증·설정 CAS·주문·청산·멱등성·fail-closed 계약은 그대로 보존합니다. Stitch HTML을 제품 코드로
복사하지 않고 색상, 정보 계층, 레이아웃과 컴포넌트 언어를 추출해 현재 기능 위에 재구현합니다.

- Stitch 프로젝트: <https://stitch.withgoogle.com/projects/15333337659015559377>
- 원본 파일: `stitch_modern_ai_trade_manager.zip`
- SHA-256: `31497F0A568A65F8834AF72A91D1CE827351CC30026073CC691B847747235D23`
- 포함 화면: Dashboard, Portfolio, Backtest, AI Banker, Settings
- 포함 명세: `DESIGN.md`, 화면별 `code.html`, 화면별 `screen.png`

원본 ZIP은 구현 중에도 읽기 전용 기준으로 사용하며 현재 저장소에 복사하거나 `frontend/src`에 압축
해제하지 않습니다.

## 2. 소스 판정과 적용 원칙

Stitch 산출물은 디자인 기준으로 충분하지만 완성된 애플리케이션 소스는 아닙니다.

- HTML은 Tailwind CDN 기반 정적 목업이며 React 컴포넌트, 라우팅, API, query 상태와 mutation이 없습니다.
- 차트는 실제 Recharts/Lightweight Charts가 아니라 SVG·HTML 도형입니다.
- Google Fonts, Material Symbols와 `lh3.googleusercontent.com` 이미지에 의존합니다.
- 모든 캡처가 데스크톱 기준이며 고정 240px 사이드바 때문에 모바일 구현은 보완이 필요합니다.
- 화면마다 상단바, 로고 줄바꿈과 콘텐츠 폭이 조금씩 달라 하나의 공통 AppShell로 정규화해야 합니다.
- USD, Binance, 주식·채권·입금·Pro 계정 등 현재 제품과 다른 예시 데이터가 포함돼 있습니다.

구현 기본값은 다음과 같이 확정합니다.

- 현재 한국어 UI와 KRW/Upbit 도메인을 유지합니다.
- Inter는 영문·숫자 목표 글꼴, `Noto Sans KR`는 한국어 목표 글꼴로 삼되 로컬 번들에 포함된 경우에만
  사용합니다. 로컬 글꼴과 라이선스가 준비되기 전에는 OS/system fallback으로 렌더링합니다.
- 기술 데이터의 목표 글꼴은 `JetBrains Mono`이며 로컬 번들이 없으면 `ui-monospace`를 사용합니다.
  아이콘은 기존 `lucide-react`를 유지합니다.
- Tailwind CDN, Material Symbols, 원격 이미지와 새 UI 라이브러리를 production에 추가하지 않습니다.
- 현재 `@tanstack/react-query`, Headless UI, Recharts, Lightweight Charts와 API client를 유지합니다.
- Stitch의 동작 없는 장식은 실제 데이터와 상태가 있을 때만 제품 컴포넌트로 만듭니다.
- 다크 디자인을 1차 시각 기준으로 사용합니다. 기존 ThemeContext와 light mode를 제거하지 않으며 같은
  semantic token의 dark/light 매핑과 양쪽 테마의 기능·가독성을 함께 검증합니다. dark-only 전환은 이
  계획 범위가 아니며 필요하면 별도 승인을 받습니다.

## 3. 전체 화면 매핑

| Stitch 화면 | 현재 진입점 | 채택할 구조 | 실제 기능으로 치환할 내용 | 구현 금지·제외 |
|---|---|---|---|---|
| Dashboard | `pages/DashboardPage.tsx` | 좌측 내비게이션, 상단 상태바, 지표 카드, 중앙 차트, AI 패널, watchlist·history | 시장 검색, 실제 KRW 캔들, AI 분석 상태, portfolio 사실성, 주문 상태, 기존 Bot/청산 제어; 수동 cycle은 기존 분석만 수행·PAPER·LIVE 평가를 분리 | 무조건 `Execute AI Recommendation`, 가짜 계좌·수익, 지원하지 않는 미국 주식 주문 |
| Portfolio | `pages/PortfolioPage.tsx` | 순자산·배분·성과·보유자산의 명확한 계층 | P1-005의 `live/snapshot/empty`, `is_stale`, `error`, `updated_at`; 실제 KRW 현금·코인; AI 조언은 읽기 전용으로 표시 | 입금 버튼, 자동 `Apply Strategy`, 주식·채권 데이터, 오류를 0원으로 표시 |
| Backtest | `pages/LaboratoryPage.tsx` | 좌측 설정, 결과 KPI, equity/drawdown, 거래 로그 | 실제 EMA/RSI/TP/SL/cooldown과 현재 API 응답; 규칙 기반 참고 전략 경고 | Sentiment Sweep·Whale Signal Pro 같은 미구현 지표, 운영 LLM 전략 재현 주장 |
| AI Banker | `pages/AIChatPage.tsx` | portfolio context와 넓은 대화 영역, 제안 카드, quick action | 기존 SSE activity·proposal·approval, `current_value`와 `expected_version`, 실제 provider 상태; quick action은 새 API 없이 prompt 입력만 보조 | 음성·파일 첨부, GPT-4 고정 표기, 무검증 리밸런싱·주문 실행 |
| Settings | `pages/SettingsPage.tsx` | 섹션 내비게이션, form surface, 상태 카드, 하단 저장 영역 | SystemConfig 운영 대상·한도·스케줄·provider·RAG·Slack·persona와 전용 reset; API key는 환경변수 관리 안내만 표시 | 웹 API key 저장·노출·삭제, 계정 프로필·2FA·비밀번호 기능, 보호 키 일반 저장 |

### 공통 셸 치환

Stitch의 `Upgrade to Pro`, Support, Log Out, 사용자 레벨과 임의 아바타는 실제 기능이 없으므로 그대로
구현하지 않습니다. 해당 공간은 다음 실제 운영 정보에 사용합니다.

- 관리자 세션 상태
- PAPER/LIVE/상태 확인 불가
- runtime RUNNING/STOPPED/UNKNOWN
- Order Gate `BLOCK_ALL/EXIT_ONLY/ARMED/UNAVAILABLE`
- portfolio `LIVE/SNAPSHOT/EMPTY/STALE`

기존 경로 `/`, `/portfolio`, `/chat`, `/laboratory`, `/settings`와 Dashboard의 `?symbol=` deep link는
변경하지 않습니다.

## 4. 디자인 시스템 계약

### 색상 토큰

`DESIGN.md`를 시각 SSOT로 삼고 화면별 HTML의 미세한 값 차이는 다음 semantic token으로 정규화합니다.

| 토큰 역할 | 기준값 | 용도 |
|---|---:|---|
| background | `#0b1326` | 앱 전체 배경 |
| surface-lowest | `#060e20` | 입력·깊은 레이어 |
| surface-low | `#131b2e` | 사이드바·보조 영역 |
| surface | `#171f33` | 기본 카드 |
| surface-high | `#222a3d` | hover·강조 surface |
| surface-highest | `#2d3449` | 선택·상위 레이어 |
| text-primary | `#dae2fd` | 본문·제목 |
| text-secondary | `#b9cacb` | 설명·metadata |
| accent-primary | `#00dbe9` | 주요 정보·focus |
| accent-bright | `#7df4ff` | 활성 상태 |
| accent-secondary | `#d0bcff` | AI·예측 보조 강조 |
| market-positive | `#4edea3` | 시장 상승·이익 |
| market-negative | `#ffb4ab` | 시장 하락·손실 |
| status-success | `#16a67a` | 검증된 정상 종결 |
| status-danger | `#d92d20` | 실패·차단 상태 |
| action-destructive | `#ef4444` | 삭제·중단 등 파괴적 조작 |
| warning | 기존 `#ffe179` 계열 | PAPER·주의·미확정 |

거래 안전 상태는 시장 상승/하락 색과 분리합니다. LIVE, UNKNOWN, PARTIAL, VERIFIED 의미를 색만으로
전달하지 않고 항상 텍스트·아이콘·설명을 같이 표시합니다.

light mode는 컴포넌트별 색상 예외를 만들지 않고 같은 semantic token을 다음 기준으로 매핑합니다.

| 토큰 역할 | light 기준값 |
|---|---:|
| background | `#f4f7fb` |
| surface-lowest | `#ffffff` |
| surface-low | `#edf3f7` |
| surface | `#ffffff` |
| surface-high | `#e3edf2` |
| surface-highest | `#d7e4ea` |
| text-primary | `#17232c` |
| text-secondary | `#50656b` |
| accent-primary | `#007f89` |
| accent-bright | `#00666f` |
| accent-secondary | `#6d45b5` |
| market-positive | `#087f5b` |
| market-negative | `#b42318` |
| status-success | `#067647` |
| status-danger | `#b42318` |
| action-destructive | `#c4320a` |
| warning | `#7a5b00` |

구현 시 실제 배경 조합별 WCAG AA 대비를 측정해 토큰값을 미세 조정할 수 있지만, 토큰 역할이나 상태
의미를 바꾸지는 않습니다.

### 타이포·간격·형태

- 기본: `Inter`, `Noto Sans KR`, sans-serif
- 데이터: `JetBrains Mono`, ui-monospace
- 4px spacing baseline, desktop gutter 24px, mobile margin 16px
- desktop content max 1440px, desktop sidebar 240px
- 기본 radius 8px, compact 4px, panel 12~16px, pill 9999px
- card border 1px, `backdrop-filter: blur(16px)`는 성능 저하가 없는 surface에서만 적용
- 애니메이션은 장식에 한정하고 `prefers-reduced-motion`을 지원

### 공통 표현 컴포넌트

다음 컴포넌트는 API나 business state를 소유하지 않는 표현 계층으로 만듭니다. 전부를 선행 구현하지
않고 각 화면에서 처음 소비되는 primitive만 JIT 방식으로 추가합니다.

- `AppShell`, `SidebarNav`, `TopStatusBar`, `MobileNavDrawer`
- `Surface`, `Card`, `MetricCard`, `ChartFrame`, `SectionHeader`
- `StatusBadge`, `ModeBanner`, `DataStateBanner`, `InlineNotice`
- `Button`, `IconButton`, `Tabs`, `SegmentedControl`, `FormField`, `Toggle`
- `Dialog`, `ConfirmDialog`, `Drawer`
- `DataTable`, `Skeleton`, `EmptyState`, `ErrorState`
- `AIInsightCard`, `OrderStateCard`, `OperationProgress`

컴포넌트는 domain service, API client, React Query mutation, sessionStorage를 직접 호출하지 않습니다.
기존 page/controller가 계산한 명시적 props만 받습니다.

## 5. 절대 보존할 기능·안전 계약

### 인증·전역 셸

- `AdminAuthProvider → AdminSessionGate → ThemeProvider → Router → Layout` 경계를 유지합니다.
- 인증 확인 전이나 401/403/503/network/사용자 취소 상태에서 private children을 mount하지 않습니다.
- 세션 무효화 시 민감 화면을 즉시 닫고 live reauth proof는 브라우저에 영구 저장하지 않습니다.
- `persistent=false`인 one-time 관리자 token 자체도 localStorage, sessionStorage, IndexedDB에 저장하지
  않습니다.
- 관리자 인증 prompt는 동시에 하나만 열고, prompt가 진행 중일 때 들어온 추가 요청은 합치거나 대기열에
  넣지 않고 현재 계약대로 거절합니다.
- trading mode를 조회하지 못하면 LIVE가 아니라 `UNAVAILABLE`로 표시하고 실주문 동작을 차단합니다.

### 봇·실주문 제어

- bot start/stop, paper/live 전환, Gate block/arm을 서로 다른 작업으로 유지합니다.
- 상태 unavailable, mirror 불일치, generation/version 누락이면 live 전환·재무장을 fail-closed로 차단합니다.
- 불명 응답 재시도 중 UUID, payload, expected version과 generation을 바꾸지 않습니다.
- pending 요청을 가진 `BotControlPanel`은 drawer·tab·반응형 전환으로 unmount하지 않습니다.
- `PREPARED/SUBMITTING/UNKNOWN/ACCEPTED`를 체결 성공으로 표시하지 않습니다.

### 전량청산

- operation UUID와 snapshot을 terminal 결과를 사용자가 닫을 때까지 sessionStorage에 보존합니다.
- 응답 불명은 동일 key·payload로만 재시도하고 정확한 확인 문구를 유지합니다.
- 조회 장애 중에도 기존 pending operation의 상태 재조회는 가능해야 합니다.
- `COMPLETED + VERIFIED`일 때만 성공색과 성공 문구를 사용합니다.
- `PARTIAL`, `FAILED`, `LEGACY_UNVERIFIED`, dust·locked·ledger mismatch를 성공으로 축약하지 않습니다.

### Settings·AI Banker

- Settings는 키별 최초 편집 version을 저장 기준으로 고정합니다.
- query version 변화는 API 0회, draft 폐기, refetch로 처리하고 새 version으로 자동 재기반하지 않습니다.
- `409`는 충돌, `503 + saved=true`는 저장 성공·runtime reload 실패로 서로 다르게 표시합니다.
- provider 상태 reset과 P0 보호 키는 일반 SystemConfig 저장 payload에 포함하지 않습니다.
- AI Banker 승인은 SSE 제안의 exact `current_value + expected_version`만 사용하고 누락 시 fail-closed합니다.

### Portfolio·Backtest

- portfolio는 `live/snapshot/empty`, stale, error, 갱신 시각을 화면 본문에 표시합니다.
- 초기 오류·empty 상태는 정상 0원 포트폴리오로 렌더링하지 않습니다.
- Navbar, Dashboard, Portfolio와 AI Banker가 같은 순수 `PortfolioDataState` 판정 helper를 사용합니다.
- cached data를 가진 refetch 오류는 수치를 유지하면서 stale 경고를 표시하고, cache가 없는 오류는 수치를
  숨긴 채 인증·IP·키·일반 조회 오류를 구분합니다.
- portfolio가 empty/error이면 AI briefing과 chat context에 정상 0원 값을 사실처럼 전달하지 않습니다.
- UI-001의 구현 경계는 frontend gating입니다. portfolio가 unavailable이면 briefing 요청과 mini chat·AI
  Banker 전송을 막고 unavailable 상태를 표시합니다. backend `app/services/chat/tools.py`의 오류 시 0원
  context 보정은 별도 승인 Delta로 분리하며, 이 Delta가 해결되기 전에는 unavailable 상태에서 우회
  전송을 허용하지 않습니다.
- 백테스트는 EMA/RSI/TP/SL/cooldown 기반 규칙 참고 전략이며 운영 LLM 전략 재현이 아님을 명시합니다.

## 6. 반응형·접근성 기준

- 기준 viewport: 320px, 390px, 768px, 1024px, 1440px, Stitch 원본 폭
- desktop: 240px sidebar + 12열 content grid
- tablet: 축소 sidebar 또는 drawer + 8열 content grid
- mobile: top app bar + drawer + 4열/단일 column, 고정 sidebar 금지
- 표는 의미를 유지한 horizontal scroll 또는 요약 카드로 전환합니다.
- dialog는 focus trap, 최초 focus, Escape 취소, 닫은 뒤 focus 복귀를 제공합니다.
- dialog는 `role="dialog"`, `aria-modal="true"`를 사용하고 열린 동안 배경을 inert 처리합니다.
- loading·error·success는 `role`, `aria-live`, accessible name을 사용합니다.
- 모든 조작은 키보드로 가능해야 하며 focus ring과 WCAG AA 수준 대비를 확보합니다.
- 모바일 조작 영역은 최소 44×44px로 하고 파괴적 작업을 의미 없는 아이콘만으로 축약하지 않습니다.
- 200% 확대와 reflow에서도 정보·조작 손실이 없어야 합니다.
- 차트의 핵심 수치와 결론은 텍스트 요약이나 접근 가능한 표로도 제공합니다.
- 상태는 색상 이외에 텍스트·아이콘·패턴 중 하나 이상을 함께 제공합니다.

## 7. 구현 순서와 의존 관계

### Phase 0 — 기준선 보호

> 완료: PostgreSQL 16.12에서 79개 marker를 migration 왕복 전후 두 번 통과했고, 저장소 밖 snapshot을
> 실제 HEAD의 임시 clone에 복원해 staged 165개·unstaged 42개·untracked 15개와 184개 경로 hash가
> 모두 일치함을 확인했습니다. 이후 추가된 Phase 0 테스트·문서는 다음 구현 snapshot에 포함합니다.

1. P1-004/006 PostgreSQL 16 migration 왕복·다중 세션 CAS 검증을 끝냅니다.
2. 현재 staged·unstaged binary patch, untracked 파일과 SHA-256 manifest를 저장소 밖에 보관합니다.
3. 복구 snapshot에 `.env`, API key, 관리자 token과 운영 secret을 포함하지 않습니다.
4. 정확한 HEAD의 폐기 가능한 별도 복구 공간에서 staged patch → unstaged patch → untracked 파일 순으로
   복원하고, 파일별 hash와 staged·unstaged·untracked count가 manifest와 일치하는지 리허설합니다.
5. 준비 문서 작성 직전 기록은 staged 165개·unstaged 42개·untracked 14개였으며, 이 계획 문서가
   untracked 1개를 추가했습니다. 구현 시작 직전에 현재 값을 다시 manifest의 기준값으로 확정합니다.
6. 커밋하지 않는 작업 조건을 유지하는 동안 각 phase 종료 시 저장소 밖에 새 snapshot과 manifest를
   만들고 다음 phase 전에 복원 가능성을 점검합니다.
7. 기준 count/hash가 달라지거나 알 수 없는 변경이 발견되면 디자인 구현을 중단합니다.

### Phase 1 — 토큰과 순수 UI primitive

> 완료: remote font 의존성을 제거하고 dark/light semantic token, focus·motion·상태 표현 기반을
> 적용했습니다.

- semantic CSS/Tailwind v4 dark/light token
- typography, spacing, border, focus, motion
- 현재 `frontend/index.html`의 Google Fonts link를 제거합니다. OFL 라이선스와 함께 승인된 로컬 WOFF2가
  있으면 번들링하고, 없으면 system font stack을 사용해 runtime CDN 요청을 0건으로 만듭니다.
- 다음 화면에서 실제 사용하는 Button/Card/Status/Notice/Form/Dialog/Table/Skeleton만 순차 구현
- 실제 page state와 API mutation 변경 없음

### Phase 2 — AppShell

> 완료: 접을 수 있는 fixed desktop sidebar, top status bar, 확장형 mobile drawer와 compact sticky
> ModeBanner를 공통 셸로 적용했습니다. 접힘 시 세 콘텐츠 컨테이너가 `1440px → 1600px`로 함께 확장됩니다.

- 공통 sidebar, top status bar, mobile drawer
- 기존 route와 provider/auth 순서 유지
- 전역 PAPER/LIVE/UNAVAILABLE 경고와 관리자 session 상태 이식

### Phase 3 — Portfolio + ATM-P1-005

> 완료: 공통 `PortfolioDataState`와 live/snapshot/cached/error/empty/loading 표현을 적용하고
> unavailable portfolio의 AI 요청을 frontend에서 차단했습니다.

- Stitch Portfolio 시각 구조 적용
- 공통 `PortfolioDataState` view-model과 금액 표시 가능 여부를 순수 함수로 정의
- live/snapshot/empty/stale/error/updated_at 상태 완성
- unavailable portfolio의 AI briefing·mini chat context 오인 차단
- unsupported deposit/apply strategy 제거

### Phase 4 — Laboratory + 규칙 기반 참고 전략 표시

> 완료: 실제 백테스트 payload와 결과는 유지하면서 규칙 기반 참고 전략과 운영 LLM 전략의 차이를
> 화면에 명시했습니다.

- 실제 backtest 설정·KPI·차트·거래 로그 이식
- 운영 LLM 전략과 동일하지 않다는 경고를 UI와 문서에 표시
- API meta 추가는 공개 API 변경이므로 이번 디자인 범위에서 제외하고 별도 승인 Delta로 기록
- `검증할 규칙 기반 정책`, `결정론적 지표`, `결과 AI 해설` 용어를 사용하고 AI provider/model은 결과
  해설 출처로만 표시
- schema·실거래 로직은 변경하지 않음

### Phase 5 — Dashboard 조회 영역

> 완료: 조회 영역을 새 정보 계층으로 이식하고 안전 controller는 화면 상태와 무관하게 계속
> mount하도록 유지했습니다.

- 시장 차트, sentiment/news, watchlist, portfolio, performance, orders 이식
- 기존 Bot/청산 제어는 안전한 기존 controller를 계속 mount한 채 외형 교체를 뒤로 미룸
- 조회 영역 tab·반응형 전환이 Bot/청산 controller를 unmount하지 않도록 shell 구조를 고정
- 1024~1535px는 중앙 차트 전체 폭 + 보조 영역 2열, 1536px 이상은 3열로 구성하고 Bot/청산 제어는
  1024px부터 넓은 하단 2열에 각각 한 번만 mount
- `LIVE FLOW`를 `AI ACTIVITY`로 바꾸고 상단 Runtime과 중복되는 ENGINE 항목 제거

### Phase 6 — AI Banker

> 완료: 대화·activity·proposal·approval을 새 셸에 이식하고 portfolio unavailable·SSE error를
> fail-closed로 처리했습니다.

- 채팅 목록·대화·activity·proposal·approval 상태를 새 shell에 이식
- 공통 `PortfolioDataState`가 unavailable이면 frontend에서 새 메시지 전송을 차단하고 원인과 재시도 동작을
  표시하며, 정상 0원 context로 대체하지 않음
- unsupported voice/file/GPT branding 제거

### Phase 7 — Settings

> 완료: 실제 SystemConfig 소비 영역을 섹션 구조로 이식하고 CAS·409·`503 + saved=true`·전용 reset
> 계약과 환경변수 기반 secret 안내를 유지했습니다.

- 실제 SystemConfig section을 Stitch 설정 구조에 배치
- CAS·409·503·전용 reset characterization test를 그대로 유지
- 웹 secret 관리 UI는 만들지 않음

### Phase 8 — 안전 제어 패널

> 완료: 봇·청산·수동 AI 패널을 semantic 상태 표현과 접근 가능한 dialog로 교체하고 pending 요청의
> exact retry identity, terminal truth와 P0/P1 경계를 보존했습니다.

- `BotControlPanel`, 전량청산 `ControlPanel`, 수동 AI cycle의 외형만 교체
- pending request 중 mount와 exact retry identity 유지
- 수동 AI cycle은 live `BLOCK_ALL`, `EXIT_ONLY`, mode unavailable 또는 stale이면 분석만 수행하고 주문을
  0회 실행하는 기존 fail-closed 계약을 유지
- paper cycle의 기존 시뮬레이션 동작을 유지하고 runtime start를 Gate arm으로 해석하거나 연결하지 않음
- 접수·미확정 주문 상태를 체결 성공으로 표시하지 않음
- 마지막 단계에서 독립 Reviewer가 P0/P1 계약 회귀를 확인

### Phase 9 — 통합 QA와 문서

> 진행 상태: frontend·backend 회귀, Ruff·ESLint, production build와 문서 동기화는 완료했습니다.
> browser viewport screenshot matrix는 플러그인 런타임 오류로 별도 잔여 검증입니다.

- 모든 viewport의 시각 비교·overflow·keyboard·focus·contrast 확인
- README, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, 안전성 리뷰 동기화
- DB schema가 바뀌지 않으면 `docs/DATABASE.md`는 변경하지 않음

## 8. 테스트와 수용 기준

각 phase마다 다음을 통과해야 다음 phase로 진행합니다.

- 기존 frontend 66개 테스트 전체
- 해당 화면의 신규 loading/ready/empty/stale/error/unknown 테스트
- 관리자 gate, Settings CAS, AIChat 승인, Bot/Gate, 청산 멱등성 테스트 유지
- ESLint
- TypeScript production build
- `git diff --check`
- 외부 CDN과 원격 이미지 없이 렌더링 가능
- dark/light 양쪽에서 320/390/768/1024/1440과 Stitch 기준 폭의 overflow·가독성 확인
- 200% 확대/reflow, 44×44px touch target, 키보드 탐색, dialog focus·modal·inert, `aria-live`, 색상
  독립 상태와 차트 텍스트·표 대체 확인
- Stitch screenshot과 시각 비교하되 실제 기능·한국어·안전 경계 차이는 의도된 Delta로 기록
- 관리자 locked, PAPER/LIVE/UNAVAILABLE, `BLOCK_ALL/EXIT_ONLY/ARMED`, 청산 진행·PARTIAL·
  `LEGACY_UNVERIFIED`·`COMPLETED + VERIFIED`, `NO_ASSETS + VERIFIED`, Settings conflict·runtime failure,
  AI 승인 conflict를 viewport별 screenshot matrix로 보존. `NO_ASSETS + VERIFIED`는 성공색이 아닌 검증된
  무자산 경고 상태로 표시

최종 통합 시 backend 공개 API·DB·P0 경계 변경이 0건인지 architecture test와 전체 비-PostgreSQL 회귀로
확인합니다. 실제 Upbit·AI API와 운영 DB는 사용하지 않습니다.

## 9. 명시적 제외 범위

- Stitch HTML의 직접 복사 또는 iframe embedding
- 프로필·구독·Support·Log Out·입금·주식·채권 기능 추가
- 웹 API key·관리자 secret 저장 기능
- 음성·파일 첨부·가짜 provider/model 표기
- AI 추천의 원클릭 실주문 실행
- 주문·청산·설정·인증 state machine 재작성
- 백엔드 API, DB schema, broker와 중앙 주문 서비스 변경
- P1-004/006 PostgreSQL 검증을 생략한 채 안전 제어 UI부터 교체

## 10. 구현 완료 판정

다음 조건을 만족해 Stitch 시안을 기반으로 한 제품 UI 이식을 완료했습니다.

- 5개 화면이 현재 5개 route와 매핑됨
- 디자인 token과 공통 component 경계가 정의됨
- 가짜 기능·외부 의존성·모바일 공백이 식별됨
- P0/P1 불변 계약과 중단 조건이 명시됨
- P1-005와 백테스트 사실성 작업이 중복 없이 phase에 통합됨
- Dashboard, Portfolio, AI Banker, Laboratory, Settings와 안전 패널이 공통 semantic 상태 언어를 사용함
- 기존 Git index는 건드리지 않았고 commit·push·PR과 원격 저장소 변경을 수행하지 않음

## 11. 로컬 검증 결과와 남은 Delta

2026-07-15 로컬 검증 결과는 다음과 같습니다.

- 격리된 PostgreSQL 16.12에서 marker 79개를 migration 왕복 전후 두 차례 통과, skip 0건
- Phase 0 외부 snapshot을 실제 기준 HEAD의 임시 clone에 복원해 staged·unstaged·untracked 경로와
  hash 일치 확인
- frontend `26 files / 125 tests`와 ESLint 통과
- backend 비-PostgreSQL `627 passed`와 Ruff 통과
- TypeScript production build 통과. 단일 JS 청크 약 1.30MB의 기존 계열 크기 경고는 후속 최적화 Delta
- DB model·schema·Alembic·공개 API·broker·중앙 실주문 경계 변경 없음
- 실제 Upbit·Gemini·OpenAI API, 운영 DB, 원격 CI, commit·push·PR 미실행

production build는 2,734개 모듈 변환과 산출물 생성을 완료했습니다. 2026-07-16 후속 headless browser
QA에서 mock API만 사용해 390/1024/1279/1280/1535/1536/1920px의 가로 overflow, sticky 좌표와 접힘
폭을 측정했습니다. 모든 viewport에서 가로 overflow가 없었고, ModeBanner는 scrollTop 0/600 모두
Navbar 아래 `y=64px`, 1920px 본문은 `1440px → 1600px`로 확장됐습니다. 전체 screenshot matrix와
200% reflow 자동화 증거는 여전히 후속 QA로 유지합니다.

또한 UI-001은 portfolio unavailable 상태의 frontend 전송만 차단합니다. backend
`app/services/chat/tools.py`가 직접 호출될 때 portfolio 조회 오류를 0원 context로 서술할 수 있는 기존
동작은 별도 승인 Delta이며, 이번 UI 개편에서 임의 변경하지 않았습니다.
