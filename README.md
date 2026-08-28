# AI-Trade-Manager

AI 분석과 RAG 뉴스를 자산 관리 워크플로우에 넣은 개인용 트레이딩 운영 시스템.

<div align="center">
  <img src="docs/images/dashboard.png" alt="AI Trade Manager 대시보드" width="900">
</div>

> 중요한 건 매수 버튼을 누르는 게 아니라, 누르면 안 될 때를 막는 것이었다.

판단 근거와 주문 앞뒤 상태를 나중에 다시 확인할 수 있게 남기는 쪽에 무게를 뒀습니다.

- [개발 블로그](https://kaero313.github.io/AI-Trade-Manager/) — 만든 이유와 겪은 문제
- [운영 기록 허브](https://torpid-icon-d8a.notion.site/AI-Trade-Manager-3724054272b580d0b968f323059761da) — 설계 근거와 케이스별 상세

## 이렇게 돌아간다

시장 데이터, 기술 지표, 포트폴리오, RAG 뉴스, 과거 판단 피드백을 묶어 매수 / 매도 / 보류 분석을 만듭니다.
실행까지 가려면 아래를 다시 통과해야 합니다.

| 규칙 | 내용 |
| :--- | :--- |
| 불확실하면 멈춘다 | 리스크 판정이 불명확하거나 결과가 없으면 신규 매수 차단 |
| 막는 건 신규 진입뿐 | 매도, 비상청산, 정합성 복구와 AI 분석은 계속 동작 |
| 실거래는 3단계 분리 | live 전환 · 런타임 시작 · 주문 게이트 해제, 자동 연쇄 없음 |
| 같은 주문을 두 번 안 보낸다 | 주문 의도와 거래소 id를 먼저 확정, 재전송 대신 조회로 복구 |
| 성공은 증명해야 성공 | 미체결 0, 잔고 0, 원장 일치를 확인한 것만 완료 |
| 판단의 출처를 남긴다 | provider, model, 부모 분석, prompt 버전, context 해시 |
| 모르는 건 모른다고 | RAG 저하와 데이터 누락을 정상값으로 보정하지 않음 |

초기 상태는 `paper + inactive + BLOCK_ALL`입니다.

## 실행

```bash
cp .env.local.example .env.local   # 키 채우기
docker compose -f docker-compose.local.yml up -d
```

- 화면 <http://localhost:8080>
- 개발 중에는 `start_dev.bat` — DB와 OpenSearch만 컨테이너로 띄우고 백엔드(8000), 프론트(5173)는 로컬에서 실행
- 필요한 키와 운영 절차는 [운영 가이드](docs/OPERATIONS.md)

## 문서

- [아키텍처 노트](docs/ARCHITECTURE.md) — 구조, 안전장치, 실주문 제어
- [데이터 모델 노트](docs/DATABASE.md)
- [운영 가이드](docs/OPERATIONS.md)
- [개발 워크플로우](docs/DEVELOPMENT_WORKFLOW.md)

기능별 설계·구현 기록은 [`docs/plans`](docs/plans), 검증 기록은 [`docs/reviews`](docs/reviews)에 있습니다.

## 기술 스택

| 영역 | 스택 |
|---|---|
| Backend | FastAPI, Async SQLAlchemy 2.0, Alembic, APScheduler |
| Frontend | React, TypeScript, Vite, TanStack Query, Recharts, lightweight-charts |
| Data | PostgreSQL, OpenSearch |
| AI | LangGraph, Gemini, OpenAI, RAG, Embeddings |
| External | Upbit, Slack, Telegram, RSS / CryptoPanic |
| Infra | Docker, Docker Compose |
