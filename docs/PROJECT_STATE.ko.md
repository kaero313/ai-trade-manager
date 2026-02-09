# 프로젝트 상태 요약 (Trading Bot v1)

이 문서는 작업을 다시 시작할 때 바로 이어서 진행하기 위한 **상태/결정/다음 할 일** 요약입니다.

## 1) 목적
- 업비트 KRW 현물 자동매매 봇 (로컬 실행)
- Python + FastAPI
- 1시간봉 기반 24시간 매매
- 웹 UI + 텔레그램 제어/알림

## 1.1) 실행 환경 전제
- OS: Windows (PowerShell)
- Python: 3.11+
- 실행: 로컬 머신

## 2) 확정된 요구사항
- 거래소: 업비트
- 마켓: 기본 KRW(명령에서 BTC만 입력 시 KRW-BTC로 인식, 필요 시 다른 베이스도 입력 가능)
- 매매 방식: 현물만
- 타임프레임: 1시간봉
- 봇 사용 최대 자본: 계좌 자산의 10%
- 일일 손실 한도: 5% (당일 시작 시점의 봇 할당 자본 기준)
- UI에서 설정 가능 항목: 종목/비중/전략 파라미터/리스크/스케줄
- 텔레그램: 명령 수신 + 잔고/수익률/체결 결과 메시지
- Slack: 알림 전송(웹훅, 선택)

## 3) 기본 전략 (v1 제안)
- EMA(12/26) 교차 + RSI(14) 필터 추세추종
- 진입: EMA fast > EMA slow & RSI > 50
- 청산: EMA fast < EMA slow 또는 트레일링 스탑(기본 3%)
- 모든 파라미터는 UI에서 변경 가능

## 4) 리스크 정책 (v1 기본값)
- 봇 사용 자본: 계좌 자산의 10% 이내
- 포지션 크기: 할당 자본 대비 20% (설정 가능)
- 동시 보유 최대 3개 (설정 가능)
- 연속 손절 2회 시 60분 쿨다운
- 일일 손실 한도 5%

## 5) 문서
- v1 스펙(영문): `docs/v1-spec.md`
- v1 스펙(국문): `docs/v1-spec.ko.md`
- API 레퍼런스(국문): `docs/API_REFERENCE.ko.md`
- 아키텍처(국문): `docs/ARCHITECTURE.ko.md`
- Slack 설정 가이드(국문): `docs/SLACK_SETUP.ko.md`

## 6) 현재 코드 상태 (스캐폴딩 완료)
### 주요 파일
- 앱 엔트리: `app/main.py`
- API 라우팅: `app/api/router.py`
- API 엔드포인트: `app/api/routes/*.py`
- 설정/상태: `app/core/config.py`, `app/core/state.py`
- 스키마: `app/models/schemas.py`
- 서비스: `app/services/upbit_client.py`(JWT 인증/주문·잔고/에러 변환), `app/services/telegram.py`(송수신), `app/services/telegram_bot.py`(폴링/명령 처리), `app/services/slack.py`(웹훅 알림)
- UI: `app/ui/routes.py`, `app/ui/templates/*.html`, `app/ui/static/style.css`
- 프로젝트 설정: `pyproject.toml`, `README.md`, `.env.example`, `.gitignore`

### 현재 동작하는 것
- FastAPI 서버 기동 가능
- `/api/health`, `/api/status`, `/api/config`, `/api/bot/start`, `/api/bot/stop` 등 기본 엔드포인트 존재
- UI 템플릿(대시보드/설정) 정적 화면 구성
- Upbit 개인 API 클라이언트(JWT 서명 + 주문/잔고 엔드포인트) 구현 완료
- Upbit 조회용 API 라우트 추가(`/api/upbit/*`)
- Upbit 오류를 HTTP 상태/메시지로 명확히 반환
- Telegram 폴링 기반 명령 처리 구현
  - /start, /stop, /status, /balance, /pnl, /positions, /setrisk, /help
  - /balance는 Upbit 계좌 조회 연동
  - /pnl, /positions는 아직 미구현 메시지
- Slack Incoming Webhook 알림 전송 + 테스트 API `/api/slack/test` 추가
- `pip install -e .` 동작을 위해 패키지 디스커버리 설정 추가(`logs/` 제외)
- Slack Socket Mode 연동을 위한 환경 변수 키 추가(xoxb/xapp)
- Slack Socket Mode 메시지 수신(앱 멘션/DM) + 잔고/상태/도움말 응답
  - 잔고 응답에 계좌 KRW, 보유 코인 평균단가/수량/추정금액, 총자산 포함
  - KRW 마켓 없는 자산은 추정금액에서 제외(표시만)
- Slack 매수/매도 명령(시장가/지정가) + 2단계 확인 + 1회 20% 상한 적용(매수)
  - 마켓은 `BTC`처럼 입력하면 기본 `KRW-BTC`로 인식
- Slack 오류 메시지 표준화(권한/형식/설정/잔고/업비트/토큰)
- Slack 최소 주문 금액 검증(베이스 통화 기준, Upbit 정책)
- Slack 호가 단위(틱 사이즈) 검증(지정가 기준, Upbit 정책)
- Slack 매도 수량 소수 자릿수 검증(최대 8자리)
- Slack 지정가 매수 수량 소수 8자리 내림 적용
- Slack 주문/체결/취소 내역 요약 + 상세 포맷 개선
- Slack 주문 조회/취소 명령 추가(2단계 확인)
- Slack Socket Mode 의존성 추가(`slack-sdk`, `aiohttp`)

### 실행 방법 (로컬)
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
uvicorn app.main:app --reload
```

### 최근 테스트 결과
- Upbit 조회 API 정상 응답 확인 (IP 제한 해결 후)
  - `/api/upbit/accounts`, `/api/upbit/orders/open`, `/api/upbit/orders/closed`
- Slack 알림 테스트 성공
  - `/api/slack/test`

### 테스트/운영 중 참고사항
- Upbit Open API는 IP 화이트리스트를 사용하는 경우가 있어, 등록된 공인 IP에서만 호출 가능
- IP 변경 시 401 `no_authorization_ip` 오류가 발생할 수 있음
- `.env`는 프로젝트 루트(`C:\\project\\trading_bot\\.env`) 기준으로 로딩되도록 고정됨

## 7) 보안/깃 관리
- 실제 키는 `.env`에만 저장 (깃 제외)
- `.gitignore`에 민감/로그/DB/키 파일 패턴 추가됨
- 현재 민감 정보 파일 없음

## 8) 다음 해야 할 일 (우선순위)
1) **텔레그램 기능 보강**
   - /buy, /sell, /config 등 확장
   - 체결/오류 알림 자동 발송
2) **Slack 알림/명령 확장**
   - 체결/오류/일일 요약 자동 발송 연결
   - 템플릿/포맷 통일
3) **전략/리스크 엔진**
   - EMA/RSI 계산, 진입/청산
   - 트레일링 스탑
   - 일일 손실 한도 체크
4) **UI 설정 저장/로드**
   - UI 폼 → `/api/config` 연동
   - 설정 값 유효성 검증
5) **주문/취소 연동 및 안전장치**
   - 주문 생성/취소 함수 실제 사용 경로 추가
   - 실매매 보호(확인, 최소 주문 금액, 슬리피지 제한)

## 9) 오픈 질문 (추후 확정 필요)
- 실제 운용 대상 종목 기본 리스트
- 초기 투자금 규모(절대값) 입력 방식
- 수익률 계산 기준 (실현/미실현 포함 여부)
- 주문 실패/부분체결 처리 정책

## 10) 참고: 현재 .env.example
```
APP_NAME=trading-bot
LOG_LEVEL=INFO

UPBIT_ACCESS_KEY=
UPBIT_SECRET_KEY=
UPBIT_BASE_URL=https://api.upbit.com
UPBIT_TIMEOUT=10

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

SLACK_WEBHOOK_URL=
SLACK_TIMEOUT=10
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
SLACK_SIGNING_SECRET=
SLACK_ALLOWED_USER_IDS=
SLACK_TRADE_CHANNEL_IDS=
```

---
마지막 업데이트: 2026-02-09
