# 프로젝트 상태 요약 (Trading Bot v1)

이 문서는 작업을 다시 시작할 때 바로 이어서 진행하기 위한 **상태/결정/다음 할 일** 요약입니다.

## 1) 목적
- 업비트 KRW 현물 자동매매 봇 (로컬 실행)
- Python + FastAPI
- 1시간봉 기반 24시간 매매
- 웹 UI + 텔레그램 제어/알림

## 2) 확정된 요구사항
- 거래소: 업비트
- 마켓: KRW만
- 매매 방식: 현물만
- 타임프레임: 1시간봉
- 봇 사용 최대 자본: 계좌 자산의 10%
- 일일 손실 한도: 5% (당일 시작 시점의 봇 할당 자본 기준)
- UI에서 설정 가능 항목: 종목/비중/전략 파라미터/리스크/스케줄
- 텔레그램: 명령 수신 + 잔고/수익률/체결 결과 메시지

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

## 6) 현재 코드 상태 (스캐폴딩 완료)
### 주요 파일
- 앱 엔트리: `app/main.py`
- API 라우팅: `app/api/router.py`
- API 엔드포인트: `app/api/routes/*.py`
- 설정/상태: `app/core/config.py`, `app/core/state.py`
- 스키마: `app/models/schemas.py`
- 서비스: `app/services/upbit_client.py`(JWT 인증 포함), `app/services/telegram.py`(스텁)
- UI: `app/ui/routes.py`, `app/ui/templates/*.html`, `app/ui/static/style.css`
- 프로젝트 설정: `pyproject.toml`, `README.md`, `.env.example`, `.gitignore`

### 현재 동작하는 것
- FastAPI 서버 기동 가능
- `/api/health`, `/api/status`, `/api/config`, `/api/bot/start`, `/api/bot/stop` 등 기본 엔드포인트 존재
- UI 템플릿(대시보드/설정) 정적 화면 구성
- Upbit 개인 API 클라이언트(JWT 서명 + 주문/잔고 엔드포인트) 구현 완료
- Upbit 조회용 API 라우트 추가(`/api/upbit/*`)
- Telegram은 아직 수신/제어 로직 없음

### 실행 방법 (로컬)
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
uvicorn app.main:app --reload
```

## 7) 보안/깃 관리
- 실제 키는 `.env`에만 저장 (깃 제외)
- `.gitignore`에 민감/로그/DB/키 파일 패턴 추가됨
- 현재 민감 정보 파일 없음

## 8) 다음 해야 할 일 (우선순위)
1) **Upbit API 실제 연동/검증**
   - 실제 키로 테스트 호출(잔고/주문 조회)
   - 레이트리밋/에러 처리 강화
2) **텔레그램 제어/알림 구현**
   - 롱폴링 수신 (getUpdates)
   - 명령 파서 (/start, /stop, /status, /balance, /pnl, /buy, /sell, /setrisk)
3) **전략/리스크 엔진**
   - EMA/RSI 계산, 진입/청산
   - 트레일링 스탑
   - 일일 손실 한도 체크
4) **UI 설정 저장/로드**
   - UI 폼 → `/api/config` 연동
   - 설정 값 유효성 검증

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
```

---
마지막 업데이트: 2026-01-18
