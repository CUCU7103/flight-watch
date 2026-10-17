---
version: 1
slug: "web-src-app-tsx"
primary_target: "web/src/App.tsx"
related_targets: []
---

# 검색 화면 (web/src/App.tsx)

범위: 단일 페이지 도구. 방문자 모드: Operate.
사용자·일: 본인(로컬)과 데모 관람자. 출발일 범위×목적지를 정해 한 번 검색하고, 날짜별 왕복 최저가를 목표가와 비교해 Google Flights에서 확인할 표를 고른다.
제약: 첫 화면에 검색 폼이 바로 보인다(히어로 없음). 결과에서 가장 먼저 읽는 것은 날짜별 가격. 피할 것: 해커툴·터미널 느낌, 장난스럽고 가벼운 느낌.

## Direction contract

THESIS: 한국 탁상 달력이 결과 화면이다. 출발일 칸마다 노선별 가격이 적혀 목표가 이하인 날이 한눈에 보인다. 카테고리 기본값(파란 SaaS 검색 바 + 흰 결과 카드 목록)을 거부한다.

OWN-WORLD: 회색 책상 바탕(#E9E7E1) 위 흰 달력 용지, 먹색 잉크(#111), 일요일 빨강(#D62828)·토요일 파랑(#2B50C8), 행동과 펜 표시는 같은 빨강. Pretendard 한 서체, 날짜 숫자는 아주 크고 굵게, 나머지는 작게. 모서리 없음, 그림자 없음, 칸은 선이 아니라 2px 틈과 톤 차이로 나눈다. 판정은 인쇄 표식: 추천=먹색 채움, 검토=윤곽, 제외=회색 취소선.

STORY: 방문자는 폼을 바꾸는 즉시 달력에 가는 날·오는 날이 칠해지는 것을 보고 검색 범위를 이해하고, 10칸 예산이 채워지는 것을 보고 검색한다. 결과가 오면 달력 칸의 가격으로 싼 날을 고르고, 아래 상세 행에서 목표가 대비 차이를 확인한 뒤 Google Flights로 간다.

FIRST VIEWPORT: 상단 검정 바(워드마크, 한 줄 설명, 예약하지 않음). 왼쪽 380px 흰 폼 패널(출발·도착 칩·첫 출발일·출발일 범위/박 스테퍼·목표가·10칸 예산·빨간 검색 버튼, 버튼은 1440x900 첫 화면 안). 오른쪽 넓은 달력: 아주 큰 월 숫자와 '2026년 10월', 요일 머리, 날짜 칸. 가는 날은 칠한 칸, 오는 날은 빨간 펜 테두리.

FORM: 탁상 달력, 내 근거 목록 1위(IMPECCABLE’S PICK으로 사용자가 선택). seed:08c31f90ee2c25d9. 기여 규율: 길이가 곧 값(목표가 대비 막대), 인쇄 표식 판정, 10칸 용량, 고른 노선만 진하게(노선 필터), 데이터로만 그린다.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
