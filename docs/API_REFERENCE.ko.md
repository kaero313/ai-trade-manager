# API 레퍼런스 (Trading Bot v1)

본 문서는 현재 구현된 API와 응답 형식을 **상세하게** 설명합니다.
기본 URL은 로컬 기준 `http://127.0.0.1:8000` 입니다.

## 공통 사항
- 인증: 현재 없음(로컬 전용). 운영 시 인증/권한 추가 필요.
- 응답 형식: JSON 또는 HTML(UI)
- 에러 형식: 기본적으로 FastAPI 표준 `{"detail": ...}`
- Upbit API 에러는 `detail` 안에 `status_code`, `error_name`, `message`가 포함됩니다.

예시(Upbit 에러):
```json
{
  "detail": {
    "status_code": 401,
    "error_name": "no_authorization_ip",
    "message": "This is not a verified IP.",
    "detail": {
      "error": {
        "name": "no_authorization_ip",
        "message": "This is not a verified IP."
      }
    }
  }
}
```

---

# 1) UI (HTML)

## GET /
- 설명: 대시보드 화면 반환
- 응답: HTML

## GET /settings
- 설명: 설정 화면 반환
- 응답: HTML

## GET /static/*
- 설명: CSS 등 정적 자원
- 응답: 정적 파일

## GET /docs
- 설명: Swagger UI (자동 API 문서)
- 응답: HTML

---

# 2) Core API

## GET /api/health
- 설명: 헬스 체크
- 응답 예시:
```json
{"status": "ok"}
```

## GET /api/status
- 설명: 봇 런타임 상태
- 응답 스키마(BotStatus):
  - `running` (bool): 봇 실행 여부
  - `last_heartbeat` (str|null): 마지막 heartbeat (UTC ISO 문자열)
  - `last_error` (str|null): 최근 오류 메시지

응답 예시:
```json
{
  "running": false,
  "last_heartbeat": "2026-01-18T12:00:00+00:00",
  "last_error": null
}
```

## GET /api/config
- 설명: 현재 봇 설정 반환
- 응답 스키마(BotConfig):
  - `symbols` (list[str]): 거래 종목 목록 (예: ["KRW-BTC"])
  - `allocation_pct_per_symbol` (list[float]): 종목별 비중 (예: [1.0])
  - `strategy` (StrategyParams)
    - `ema_fast` (int)
    - `ema_slow` (int)
    - `rsi` (int)
    - `rsi_min` (int)
    - `trailing_stop_pct` (float)
  - `risk` (RiskParams)
    - `max_capital_pct` (float) — 계좌 대비 봇 사용 최대 비율 (기본 0.10)
    - `max_daily_loss_pct` (float) — 일일 손실 한도(기본 0.05)
    - `position_size_pct` (float) — 1회 포지션 비중 (기본 0.20)
    - `max_concurrent_positions` (int)
    - `cooldown_minutes` (int)
  - `schedule` (ScheduleParams)
    - `enabled` (bool)
    - `start_hour` (int|null)
    - `end_hour` (int|null)

## POST /api/config
- 설명: 봇 설정 저장
- 요청 바디: BotConfig (GET /api/config과 동일 스키마)
- 응답: 저장된 BotConfig
- 참고: 현재는 타입 검증만 수행 (세부 값 범위 체크는 추후 추가)

## POST /api/bot/start
- 설명: 봇 시작(상태 플래그만 변경)
- 응답: BotStatus

## POST /api/bot/stop
- 설명: 봇 정지(상태 플래그만 변경)
- 응답: BotStatus

## GET /api/positions
- 설명: 현재 보유 포지션 목록
- 현재 동작: 빈 배열 반환(미구현)
- 응답 예시:
```json
[]
```

## GET /api/orders
- 설명: 주문 목록
- 현재 동작: 빈 배열 반환(미구현)
- 응답 예시:
```json
[]
```

---

# 3) Upbit 테스트 API (개발용)

## 공통
- `.env`에 `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY` 필요
- 키가 없으면 400
- Upbit 에러 시 HTTP 상태코드 + 상세 메시지 반환

## GET /api/upbit/accounts
- 설명: 업비트 계좌 목록 조회
- 응답: Upbit 원본 JSON 배열

## GET /api/upbit/order
- 설명: 단일 주문 조회
- 쿼리 파라미터:
  - `uuid` 또는 `identifier` 중 하나 필수
- 응답: Upbit 원본 JSON

## GET /api/upbit/orders/open
- 설명: 미체결/진행 주문 조회
- 쿼리 파라미터:
  - `market` (옵션)
  - `states` (옵션, CSV: 예 "wait,watch")
  - `page`, `limit`, `order_by` (옵션)
- 응답: Upbit 원본 JSON 배열

## GET /api/upbit/orders/closed
- 설명: 체결/취소 완료 주문 조회
- 쿼리 파라미터: `/orders/open`과 동일
- 응답: Upbit 원본 JSON 배열

## GET /api/upbit/orders/uuids
- 설명: 복수 UUID로 주문 조회
- 쿼리 파라미터:
  - `uuids` (필수, CSV)
  - `states` (옵션, CSV)
  - `order_by` (옵션)
- 응답: Upbit 원본 JSON 배열

---

# 4) Slack 알림 테스트 API

## POST /api/slack/test
- 설명: Slack Incoming Webhook으로 테스트 메시지 전송
- 필요 설정: `.env`의 `SLACK_WEBHOOK_URL` 또는 요청 바디 `webhook_url`
- Swagger에서 테스트 시 `webhook_url`을 비우거나 `null`로 두면 `.env` 값이 사용됨
- 요청 바디:
  - `text` (str, optional): 보낼 메시지 (기본값 있음)
  - `webhook_url` (str, optional): 요청별 웹훅 URL
  - `username` (str, optional): 표시 이름
  - `icon_emoji` (str, optional): 이모지 아이콘 (예: `:robot_face:`)
- 응답 예시:
```json
{"ok": true}
```

---

# 5) Slack Socket Mode (로컬)
- 목적: Slack 메시지 수신(앱 멘션/DM) → Upbit 연동 응답
- 필요 설정: `.env`의 `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`
- 지원 명령(기본):
  - `잔고` / `balance` : 업비트 잔고 요약
  - `status` : 봇 상태
  - `help` : 도움말
  - `매수 KRW-BTC 100000` : 시장가 매수
  - `매수 KRW-BTC 10%` : 잔고 비율로 시장가 매수
  - `매수 KRW-BTC 100000 지정가 50000000` : 지정가 매수
  - `확인 <토큰>` : 매수 주문 확정

---

# 6) 실행/테스트 예시

```powershell
# 서버 실행
uvicorn app.main:app --reload

# 계좌 조회
Invoke-RestMethod http://127.0.0.1:8000/api/upbit/accounts

# Slack 테스트
Invoke-RestMethod http://127.0.0.1:8000/api/slack/test -Method Post -ContentType "application/json" -Body '{"text":"Slack 연동 테스트"}'
```

---

# 7) 텔레그램 명령 (봇)

텔레그램 봇 토큰/채팅 ID 설정 시, 아래 명령을 받을 수 있습니다.

- `/start` : 봇 시작
- `/stop` : 봇 중지
- `/status` : 봇 상태 확인
- `/balance` : Upbit 계좌 잔고 조회
- `/pnl` : 수익률(현재 미구현 안내)
- `/positions` : 포지션(현재 미구현 안내)
- `/setrisk daily_loss=5 max_capital=10 position=20 max_positions=3 cooldown=60`
- `/help` : 도움말
