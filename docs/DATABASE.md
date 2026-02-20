# AI-Trade-Manager 데이터베이스 명세서 (Database Schema Specification)

본 문서는 **Phase 1**에서 확정된 핵심 도메인 모델 4가지의 설계 의도와 데이터베이스 운용 수칙을 기재합니다.
우리는 In-memory 구조에서 벗어나 **PostgreSQL + 비동기 SQLAlchemy 2.0** 스택으로 완벽히 이전했습니다.

---

## 1. DB 환경 구성 원칙
*   **Alembic Migration 필수:** 코드를 수정하여 새로운 테이블이나 컬럼을 만들었다면, **절대** 임의로 디비에 직접 들어가 수정하지 마세요. 무조건 `alembic revision --autogenerate`로 마이그레이션 스크립트를 생성하고, `alembic upgrade head`로 반영해야 합니다.
*   **비동기 세션 강제:** 쿼리는 반드시 `AsyncSession`과 `select(), insert()...` 등 SQLAlchemy 2.0 스타일 구문을 통해서만 실행해야 합니다. `Session.query()` 같은 동기 방식 1.x 스타일은 전면 금지합니다.

## 2. 테이블 설계 결정 사항 (Schema Decisions)
마이그레이션의 유연성과 빠른 속도를 확보하기 위해 아래와 같은 표준을 정의했습니다.
1.  **ID 타입:** 모든 PK(기본키)는 `Autoincrement Integer` 방식을 씁니다. (UUID 배제)
2.  **Enum 타입 배제:** 확장성을 위해 `status`나 `side` 같은 열거형 속성들은 DB 단의 빡빡한 Enum 대신 Pydantic/Python 단에서 검증하는 일반 `String` 속성으로 정의합니다.
3.  **날짜/시간 자동 생성:** 모든 `updated_at`, `executed_at` 등의 타임스탬프는 백엔드 시간과 꼬이는 것을 방지하기 위해 DB 고유 서버 시간인 `server_default=func.now()`에 100% 위임합니다.

---

## 3. 도메인 모델 정의 및 ERD (Phase 1 기준)

### 3.1. `assets` (자산 정보)
거래소에서 지원하는 종목 또는 내가 추적하려는 기초 자산의 메타데이터.
*   `id`: (PK) 고유 번호
*   `symbol`: (String, Unique, Index) 식별용 암호화폐 티커 또는 주식 단축코드 (예: `KRW-BTC`, `005930`)
*   `asset_type`: (String) 자산 종류 분류 값 (예: `CRYPTO`, `STOCK`, `US_STOCK`)
*   `base_currency`: (String) 매수하는 데 필요한 기축 통화 (예: `KRW`, `USD`)
*   `is_active`: (Boolean) 해당 자산의 거래 봇 감시/작동 여부 제어 스위치.

### 3.2. `positions` (보유 포지션 상태)
현재 진행 중이거나 보유 중인 실제 투자 진입 내역.
*   `id`: (PK) 고유 번호
*   `asset_id`: (FK) `assets` 참조 인덱스 키
*   `avg_entry_price`: (Float) 매수 평단가 (수수료 포함 계산)
*   `quantity`: (Float) 현재 들고 있는 보유 수량
*   `status`: (String) 포지션 상태 (예: `OPEN`, `CLOSED`, `HOLD`)
*   `updated_at`: (DateTime, AutoNow) 가격 변동이나 매매가 일어날 때 기록되는 타임스탬프

### 3.3. `order_history` (매매 체결 히스토리)
매수/매도할 때마다 찍히는 실제 주문 체결 로그 (손익 계산의 뼈대).
*   `id`: (PK) 고유 번호
*   `position_id`: (FK) 이 주문이 종속된 `positions` 스레드 번호 참조 키
*   `side`: (String) 주문 종류 (예: `BUY`, `SELL`)
*   `price`: (Float) 1주/1코인당 실제 체결 가격
*   `qty`: (Float) 체결 수량
*   `broker`: (String) 이 주문을 받아준 거래소 (예: `UPBIT`, `KIWOOM`)
*   `executed_at`: (DateTime, AutoNow) 거래소가 체결을 이행해준 시간

### 3.4. `bot_configs` (알고리즘 및 위험 설정)
사용자가 앱이나 슬랙에서 조정하는 매매 알고리즘의 변수값들 모음집.
*   `id`: (PK) 고유 번호
*   `config_json`: (JSON) 동적 설정들을 자유롭게 품을 수 있는 통(Container). 그리드 매매 기준 간격, 일일 최대 손실액 등을 JSON 형태로 자유롭게 삽입 가능.
*   `is_active`: (Boolean) 이 설정 프로필이 현재 작동 중인지 여부.
