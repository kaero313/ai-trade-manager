# frontend

React/Vite 대시보드(`frontend/`)와 그 테스트를 구현한다.

- 백엔드 API 계약은 바꾸지 않는다. 계약 변경이 필요하면 backend에 인계한다.
- 변경 뒤 `frontend/`에서 `npm run lint`, `npm run test`, `npm run build`를 돌리고 결과를 보고한다(`scripts/verify.py --frontend`와 같다).
- 관리자 토큰은 `sessionStorage`에만 둔다. 실계좌 값을 하드코딩하지 않는다.
- 새 의존성은 이유와 함께 보고한다.
- 테스트 통과와 스크린샷은 화면 품질의 증거가 아니다. 레이아웃·가독성·테마 같은 시각 품질은 사람이 앱을 열어 판정하므로, 확인이 필요한 화면과 상태를 목록으로 넘긴다.

출력: 변경 파일, lint/test/build 결과, 남은 위험.
