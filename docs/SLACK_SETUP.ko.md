# Slack 로컬(Socket Mode) 설정 가이드

로컬 환경에서 Slack 메시지를 수신하려면 **Socket Mode**를 사용합니다.

## 1) Slack App 설정
1. Slack App 생성 → 워크스페이스에 설치
2. **Socket Mode 활성화**
   - App-Level Token 생성 → 권한: `connections:write`
3. **Bot Token Scopes 추가**
   - `chat:write` (응답 메시지 전송)
   - `app_mentions:read` (앱 멘션 수신)
   - `im:history` (DM 수신)
4. **Event Subscriptions 활성화**
   - Events에 `app_mention`, `message.im` 추가

## 2) 로컬 .env 설정
```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_ALLOWED_USER_IDS=U12345678
SLACK_TRADE_CHANNEL_IDS=C12345678
```

## 3) 실행
```
uvicorn app.main:app --reload
```

## 4) 사용 예시
- DM 또는 채널 멘션에서:
  - `잔고` / `balance`
  - `status`
  - `help`
  - `매수 KRW-BTC 100000`
  - `매수 KRW-BTC 10%`
  - `매수 KRW-BTC 100000 지정가 50000000`
  - `매도 KRW-BTC 0.01`
  - `매도 KRW-BTC 10%`
  - `매도 KRW-BTC 0.01 지정가 50000000`
  - `미체결 내역`
  - `미체결 내역 KRW-BTC`
  - `체결 내역`
  - `체결 내역 KRW-BTC`
  - `취소 내역`
  - `취소 내역 KRW-BTC`
  - `취소 <UUID>`
  - `확인 <토큰>`
  - 마켓 입력은 `BTC`처럼 입력하면 기본 `KRW-BTC`로 인식
  - 최소 주문 금액(Upbit 정책) 미만이면 오류 반환
  - 지정가 주문 가격이 호가 단위(Upbit 정책)에 맞지 않으면 오류 반환
  - 매도 수량 소수 자릿수는 최대 8자리
  - 지정가 매수 수량은 계산 후 소수 8자리로 내림
