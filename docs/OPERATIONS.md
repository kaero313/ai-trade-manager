# 로컬 Linux 상시 운영 가이드

AI-Trade-Manager는 공개 인터넷에 직접 노출하지 않고, 로컬 Linux PC와 Tailscale 사설망을 기준으로 운영합니다.

## 1. 운영 구조

| 구성 | 역할 |
|---|---|
| 웹 | 정적 웹 UI 제공, API 요청을 백엔드로 전달 |
| 백엔드 | FastAPI, 스케줄러, 매매 엔진, Slack/Telegram 실행 관리 |
| PostgreSQL | 운영 상태의 기준 저장소 |
| OpenSearch | RAG 뉴스 검색 캐시 |
| Tailscale | 외부 공개 없이 개인 기기 접근 |

backend는 단일 인스턴스로 운영합니다. 여러 개를 동시에 띄우면 스케줄러와 매매 루프가 중복 실행될 수 있습니다.

## 2. 최초 구성 체크리스트

1. Docker, Docker Compose, Tailscale, 방화벽 도구를 설치합니다.
2. 예제 환경 파일을 복사하고 실제 비밀값을 채웁니다.
3. 웹 UI용 기본 인증 계정과 관리 API 토큰을 설정합니다.
4. 컨테이너를 시작하고 데이터베이스 마이그레이션을 적용합니다.
5. 헬스체크로 web, backend, PostgreSQL, OpenSearch 상태를 확인합니다.

## 3. 접근 방식

- 웹 UI는 로컬 PC에서는 localhost 경로로 확인합니다.
- 원격 접속은 Tailscale 경로만 사용합니다.
- 일반 인터넷에 웹 UI, API, DB, OpenSearch 포트를 직접 열지 않습니다.

## 4. 인증 계층

| 계층 | 목적 |
|---|---|
| Caddy 기본 인증 | 웹 UI와 API 진입점 보호 |
| 관리자 API 토큰 | 설정 변경, 봇 제어, 수동 AI Cycle 같은 상태 변경 API 보호 |

관리자 API 토큰이 서버에 없으면 보호 API는 차단되어야 합니다.

## 5. 안전 기본값

- 모의 거래 모드로 시작합니다.
- 실거래 매수는 잠근 상태로 둡니다.
- 관측 모드에서 매수 후보와 차단 사유를 먼저 확인합니다.
- 며칠간 판단 로그, RAG 경고, 모의 거래 손익을 확인한 뒤 실거래 매수 잠금을 해제합니다.

## 6. 백업과 복구

- PostgreSQL 백업을 운영 복구 기준으로 봅니다.
- OpenSearch 뉴스 캐시는 재수집 가능한 데이터로 봅니다.
- 장애 시 주문 위험을 먼저 멈추고, 그 다음 로그와 저장소 상태를 확인합니다.

## 7. 운영 점검

| 항목 | 확인 기준 |
|---|---|
| 웹 UI | 로컬과 Tailscale 경로에서 접속 가능 |
| API | 프론트엔드에서 정상 호출 |
| DB | 마이그레이션 적용 완료, 백업 가능 |
| RAG | OpenSearch 상태와 RAG warning 확인 |
| 메신저 | Slack/Telegram 비상 정지와 알림 확인 |
| 네트워크 | 일반 외부망에서 DB/API/OpenSearch 미노출 |

## 8. AI Cycle 장애 판단

- 분석 로그의 commit·refresh·ID 확인이 실패하면 해당 종목의 주문 평가는 실행하지 않습니다.
- 자동 scheduler는 실패한 종목을 기록하고 다음 종목을 독립 cycle로 처리합니다.
- 수동 AI Cycle은 분석 저장 실패를 오류로 반환하고 주문 평가를 수행하지 않습니다.
- executor의 `analysis_id` 누락·미존재·종목 불일치는 fail-closed skip이며, 과거 BUY·SELL 또는 BUY 직전 검증 로그를 대신 실행하지 않습니다.
- 장애 조사 시 분석 저장 오류와 executor의 `analysis_id` 로그를 함께 확인합니다.
