# AI-Trade-Manager

AI 분석, RAG 뉴스, 포트폴리오, 백테스트, 자동매매 안전장치를 묶은 개인용 트레이딩 운영 시스템

핵심은 “AI가 매수 버튼을 누르게 하는 것”이 아니라, AI 판단이 어떤 데이터와 안전장치를 통과했는지 추적하고, 주문 실행 전후의 상태를 운영 가능한 형태로 남기는 것입니다.

## 개발 일지

- [개발 블로그](https://kaero313.github.io/AI-Trade-Manager/)
- [전체 운영 기록 허브](https://torpid-icon-d8a.notion.site/AI-Trade-Manager-3724054272b580d0b968f323059761da)

## 상세 문서

- [아키텍처 노트](docs/ARCHITECTURE.md)
- [데이터 모델 노트](docs/DATABASE.md)

## 핵심 설계

- **AI 판단 파이프라인:** 시장 데이터, 기술 지표, 포트폴리오, RAG 뉴스, 과거 판단 피드백을 종합해 `BUY / SELL / HOLD` 분석 로그를 생성합니다.
- **자동 매매 실행:** AI 분석 결과를 기반으로 매수/매도 후보를 생성하고, 안전 조건을 통과한 주문만 paper 또는 live 모드에서 실행합니다.
- **주문 실행 제어:** paper/live 모드, shadow mode, live BUY 안전락, Entry Gate, BUY 직전 2차 검증으로 실거래 진입을 제한합니다.
- **운영 관측성:** AI 판단 로그, 주문 이력, 포지션, 포트폴리오 스냅샷, RAG/provider warning을 PostgreSQL과 OpenSearch에 남깁니다.
- **AI Banker:** LangGraph 기반 멀티에이전트가 포트폴리오, 시장 뉴스, 기술 지표를 나눠 분석하고 Reviewer가 응답을 검토합니다.
- **정책 검증:** Strategy Laboratory에서 전략 파라미터와 리스크 성향을 과거 데이터로 검증합니다.

## 운영 안전 기준

- **판단과 실행 분리:** AI 응답은 주문 명령이 아니라 검증 대상이며, 실행 단계에서 별도의 안전 조건을 다시 통과해야 합니다.
- **실거래 기본 차단:** 신규 BUY는 기본적으로 잠겨 있고, 검증 전에는 paper/shadow 흐름에서만 관측합니다.
- **단일 거래 모드:** paper와 live를 동시에 실행하지 않아 운영 상태와 주문 책임을 명확히 분리합니다.
- **근거 기반 진입:** 시장 심리, 기술 지표, 뉴스 품질, 포트폴리오 상태, 과거 판단 성과를 함께 통과해야 매매 후보가 됩니다.
- **장애 노출 우선:** RAG 품질 저하, provider fallback, 데이터 누락은 숨기지 않고 화면과 로그에 남깁니다.

## 기술 스택

| 영역 | 스택 |
|---|---|
| Backend | FastAPI, Async SQLAlchemy 2.0, Alembic, APScheduler |
| Frontend | React, TypeScript, Vite, TanStack Query, Recharts, lightweight-charts |
| Data | PostgreSQL, OpenSearch |
| AI | LangGraph, Gemini, OpenAI, RAG, Embeddings |
| Infra | Docker, Docker Compose |
