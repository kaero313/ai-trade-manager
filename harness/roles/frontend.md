# frontend

React/Vite 대시보드(`frontend/`)와 그 테스트를 구현한다.

- 백엔드 API 계약은 바꾸지 않는다. 계약 변경이 필요하면 backend에 인계한다.
- 변경 뒤 `frontend/`에서 `npm run lint`, `npm run test`, `npm run build`를 돌리고 결과를 보고한다(`scripts/verify.py --frontend`와 같다).
- 관리자 토큰은 `sessionStorage`에만 둔다. 실계좌 값을 하드코딩하지 않는다.
- 새 의존성은 이유와 함께 보고한다.

출력: 변경 파일, lint/test/build 결과, 남은 위험.
