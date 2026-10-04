# 제3자 스킬 출처 표기

이 디렉터리의 스킬 중 아래 두 개는 [obra/superpowers](https://github.com/obra/superpowers)(MIT License)에서 유래했다.
원본 저장소의 최신 파일과 한 줄씩 대조하지는 않았다.

- `systematic-debugging/` — SKILL.md, root-cause-tracing.md, defense-in-depth.md, condition-based-waiting.md,
  condition-based-waiting-example.ts, find-polluter.sh
- `verification-before-completion/` — SKILL.md

바꾼 곳은 `systematic-debugging/SKILL.md`의 스킬 이름 두 곳뿐이다. 이 프로젝트에 없는
`superpowers:test-driven-development`는 `surgical-patch`로, `superpowers:verification-before-completion`은
`verification-before-completion`으로 바꿨다. 원본에 있던 스킬 작성 기록과 스킬 시험 시나리오
(CREATION-LOG.md, test-academic.md, test-pressure-1~3.md)는 이 프로젝트에서 쓰지 않아 뺐다.

`verify-and-stop`, `surgical-patch`, `safe-refactor`는 이 프로젝트가 한국어로 작성한 자체 스킬이다.

## GitNexus 스킬 (PolyForm Noncommercial 1.0.0)

`gitnexus-cli/`, `gitnexus-debugging/`, `gitnexus-exploring/`, `gitnexus-guide/`, `gitnexus-impact-analysis/`, `gitnexus-refactoring/`의 `SKILL.md`는 npm 패키지 `gitnexus@1.6.12`의 `skills/gitnexus-*.md`를 수정 없이 복사했다.

- 저작자: Abhigyan Patwari
- 원본: https://github.com/abhigyanpatwari/GitNexus
- 라이선스: PolyForm Noncommercial License 1.0.0, https://polyformproject.org/licenses/noncommercial/1.0.0

이 라이선스는 비상업적 목적의 사용과 배포만 허용한다. 이 파일들을 받는 사람도 위 라이선스 조건을 따라야 한다.

## MIT License (obra/superpowers)

Copyright (c) 2025 Jesse Vincent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
