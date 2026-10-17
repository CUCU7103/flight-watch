---
name: flight-watch
description: 날짜별 왕복 최저가를 탁상 달력 칸에 적어 목표가와 비교하는 검색 도구
colors:
  red: "#d62828"
  action: "#d62828"
  action-hover: "#b31f1f"
  on-action: "#ffffff"
  blue: "#2b50c8"
  desk: "#e9e7e1"
  paper: "#ffffff"
  paper-2: "#f5f4f0"
  ink: "#111111"
  ink-2: "#4a4945"
  ink-3: "#6b6862"
  faint: "#8f8b83"
  line: "#c9c6be"
  faint-number: "#878379"
  faint-sun: "#c86464"
  faint-sat: "#6a7fd0"
  bar: "#111111"
  on-bar: "#ffffff"
  on-bar-2: "#c9c6be"
  red-dark: "#ff6b6b"
  action-hover-dark: "#e33b3b"
  blue-dark: "#8ea8ff"
  desk-dark: "#121211"
  paper-dark: "#1c1c1b"
  paper-2-dark: "#252523"
  ink-dark: "#edece8"
  ink-2-dark: "#c6c4be"
  ink-3-dark: "#a3a09a"
  faint-dark: "#75726c"
  line-dark: "#45443f"
  faint-number-dark: "#7d7a73"
  faint-sun-dark: "#b06262"
  faint-sat-dark: "#6b7cb8"
  bar-dark: "#000000"
  on-bar-2-dark: "#a3a09a"
typography:
  display:
    fontFamily: "'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', system-ui, sans-serif"
    fontSize: "88px"
    fontWeight: 800
    lineHeight: 0.85
    letterSpacing: "-0.04em"
    fontFeature: "'tnum'"
  headline:
    fontFamily: "'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.02em"
    fontFeature: "'tnum'"
  title:
    fontFamily: "'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.5
    letterSpacing: "-0.01em"
    fontFeature: "'tnum'"
  body:
    fontFamily: "'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
    fontFeature: "'tnum'"
  label:
    fontFamily: "'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.5
    letterSpacing: "normal"
    fontFeature: "'tnum'"
rounded:
  none: "0px"
  pen-circle: "50%"
spacing:
  seam: "2px"
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  xxl: "40px"
components:
  topbar:
    backgroundColor: "{colors.bar}"
    textColor: "{colors.on-bar}"
    typography: "{typography.title}"
    padding: "14px 32px"
  panel:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "20px 24px 24px"
    width: "380px"
  board:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "24px 28px 28px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "0 14px"
    height: "46px"
  button-primary:
    backgroundColor: "{colors.action}"
    textColor: "{colors.on-action}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    height: "56px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
    textColor: "{colors.on-action}"
  button-primary-disabled:
    backgroundColor: "{colors.desk}"
    textColor: "{colors.ink-3}"
  link-button:
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0 16px"
    height: "44px"
  link-button-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  link-button-pick:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  link-button-pick-hover:
    backgroundColor: "{colors.action}"
    textColor: "{colors.on-action}"
  chip:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.none}"
    padding: "0 2px 0 12px"
    height: "36px"
  chip-needs-target:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.red}"
  stepper-button:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    size: "44px"
  stepper-button-hover:
    backgroundColor: "{colors.desk}"
  stepper-button-active:
    backgroundColor: "{colors.line}"
  route-filter:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "0 14px"
    height: "40px"
  route-filter-active:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  day-cell:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink}"
    typography: "{typography.headline}"
    rounded: "{rounded.none}"
    padding: "8px 10px 10px"
    height: "52px"
  day-cell-departure:
    backgroundColor: "{colors.paper}"
    height: "104px"
  fare-pick:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    padding: "2px 6px"
  fare-review:
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    padding: "2px 6px"
  fare-drop:
    textColor: "{colors.ink-3}"
    typography: "{typography.label}"
    padding: "2px 6px"
  mark-pick:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    padding: "0 9px"
    height: "26px"
  mark-review:
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    padding: "0 9px"
    height: "26px"
  mark-drop:
    textColor: "{colors.ink-3}"
    typography: "{typography.label}"
    padding: "0 9px"
    height: "26px"
  slot:
    backgroundColor: "{colors.desk}"
    height: "16px"
  slot-on:
    backgroundColor: "{colors.ink}"
  slot-over:
    backgroundColor: "{colors.red}"
  delta-bar:
    backgroundColor: "{colors.desk}"
    height: "8px"
    width: "220px"
  delta-bar-fill-under:
    backgroundColor: "{colors.ink}"
  delta-bar-fill-over:
    backgroundColor: "{colors.faint}"
  detail-row:
    backgroundColor: "{colors.paper-2}"
    rounded: "{rounded.none}"
    padding: "16px 20px"
---

# Design System: flight-watch

## Overview

**Creative North Star: "탁상 달력"**

결과 화면은 책상 위에 펼쳐 둔 한국식 탁상 달력이다. 회색 책상 바탕 위에 흰 달력 용지가 놓이고, 먹색 잉크로 날짜와 가격을 적는다. 일요일은 빨강, 토요일은 파랑이라는 달력의 오래된 약속을 그대로 따르고, 사람이 펜으로 표시하는 자리(오는 날 동그라미, 고른 결과 행, 목표가 눈금)와 행동(검색 버튼)에는 같은 빨강을 쓴다. 파란 SaaS 검색 바와 흰 결과 카드 목록이라는 항공권 검색 화면의 기본값은 의도적으로 버렸다.

밀도는 높지만 위계는 단순하다. 서체는 Pretendard 하나뿐이고, 월 숫자와 날짜 숫자는 아주 크고 굵게, 나머지는 작고 조용하게 둔다. 판정은 색이 아니라 인쇄 표식으로 읽힌다. 추천은 먹색 채움, 검토는 윤곽, 제외는 회색 취소선이다. 막대의 길이는 곧 값(가격 ÷ 목표가)이고, 화면의 장식은 모두 데이터에서 나온다.

모서리는 각지고 그림자는 없다. 면은 선보다 2px 틈과 종이 톤 차이로 나눈다. 해커툴이나 터미널 같은 인상, 장난스럽고 가벼운 인상은 피한다. 방향 계약은 가는 날을 "칠한 칸", 오는 날을 "빨간 펜 테두리 칸"으로 적었지만, 실제 빌드에서는 가는 날이 먹색 3px 윤곽을 두른 흰 용지 칸(주변 `paper-2`보다 한 톤 밝다)이고, 오는 날은 날짜 숫자에 두른 빨간 펜 동그라미다. 이 문서는 빌드를 기준으로 한다.

**Key Characteristics:**
- 회색 책상(`desk`) 위 흰 용지(`paper`), 먹색 잉크(`ink`) 한 벌
- 일요일 빨강·토요일 파랑은 달력 관례로만 쓴다
- Pretendard 단일 서체, 표 숫자(`tnum`), 아주 큰 월·날짜 숫자
- 모서리 0, 그림자 0, 칸은 2px 틈과 톤 차이로 구분
- 판정은 인쇄 표식(채움·윤곽·취소선), 길이는 곧 값
- 라이트·다크 모두 같은 구조, 다크에서는 책상과 용지가 먹지로 뒤집힌다

## Colors

종이와 잉크의 무채색 한 벌 위에, 달력 관례에서 온 빨강과 파랑 두 색만 얹는다.

### Primary
- **펜 빨강** (`red`): 일요일 날짜와 요일 머리, 오는 날 동그라미, 상세 행 `:target` 윤곽, 목표가 눈금, 오류·경고·`(필수)` 표시, 10칸 초과 시 건수와 슬롯, 포커스 링·캐럿·`accent-color`. 다크 모드에서는 어두운 종이 위에서 읽히도록 밝은 빨강(`red-dark`)으로 바뀐다.
- **도장 빨강** (`action`): 채운 행동 버튼(검색)과 텍스트 선택 배경, 추천 행 링크 버튼의 호버. 다크 모드에서도 바뀌지 않는다. 눌렀을 때는 한 단계 진한 빨강(`action-hover`, 다크 `action-hover-dark`).
- **도장 위 글자** (`on-action`): 빨간 버튼 위 흰 글자.

### Secondary
- **토요일 파랑** (`blue`): 토요일 요일 머리와 토요일 날짜 숫자에만 쓴다. 다크에서는 `blue-dark`.

### Neutral
- **책상 회색** (`desk`): 페이지 바탕, 빈 슬롯, 막대의 빈 트랙, 스테퍼·노선 필터 호버, 비활성 주 버튼 바탕.
- **달력 용지** (`paper`): 폼 패널, 달력 판, 상세 영역, 가는 날 칸, 입력칸 바탕.
- **바랜 용지** (`paper-2`): 날짜 칸 기본 톤, 상세 행, 제출 영역, 스테퍼 버튼, 노선 필터, 실패 안내, 검색 중 자리표시.
- **먹** (`ink`): 본문 글자, 칩, 추천 표식 채움, 가는 날 윤곽, 켜진 슬롯, 목표가 이하 막대.
- **옅은 먹** (`ink-2`): 보조 라벨(서브라벨, 범례), 목표가 초과 차이 문구, 문제 사유.
- **회먹** (`ink-3`): 보조 설명·힌트, 제외 가격 취소선, 비활성 버튼 글자.
- **흐린 먹** (`faint`): 비활성 스테퍼 기호, 목표가 초과 막대, 스크롤바.
- **괘선** (`line`): 입력칸·칩 묶음·스테퍼의 1.5px 테두리, 제외 표식 윤곽, 스테퍼 눌림.
- **범위 밖 숫자** (`faint-number`, `faint-sun`, `faint-sat`): 검색 범위 밖 날짜 숫자. 큰 글자 3:1 이상을 지키는 흐린 먹·흐린 빨강·흐린 파랑.
- **상단 띠** (`bar`, `on-bar`, `on-bar-2`): 맨 위 검정 띠와 그 위 워드마크·한 줄 설명.

다크 모드는 `-dark` 접미사 토큰으로 16개 값을 다시 정의한다. 책상은 거의 검정, 용지는 짙은 먹지가 되고 잉크는 밝은 종이색이 된다. `action`, `on-action`, `on-bar`는 다크에서도 그대로다.

### Named Rules
**The Calendar Convention Rule.** 파랑은 토요일에만 쓴다. 링크, 강조, 상태에 파랑을 쓰지 않는다. 일요일 빨강과 토요일 파랑은 달력의 약속이지 브랜드 액센트가 아니다.

**The Pen and Stamp Rule.** 빨강은 두 갈래다. 표시하는 빨강(`red`)은 다크에서 밝아져 읽히고, 누르는 빨강(`action`)은 다크에서도 진한 도장색을 유지해 흰 글자 대비를 지킨다. 둘을 섞어 쓰지 않는다.

**The Verdict Is Not a Color Rule.** 추천·검토·제외를 초록·노랑·빨강으로 칠하지 않는다. 판정은 먹색 채움·먹색 윤곽·회색 취소선으로만 구분한다.

## Typography

**Display Font:** Pretendard Variable (Pretendard, Apple SD Gothic Neo, system-ui 폴백)
**Body Font:** Pretendard Variable (같은 스택)

**Character:** 한 서체의 굵기와 크기 대비만으로 달력의 위계를 만든다. 숫자는 모두 표 숫자(`tnum`)라 가격과 날짜가 세로로 정렬되고, 한국어는 `word-break: keep-all`로 어절 단위로 줄을 바꾼다.

### Hierarchy
- **Display** (800, 88px, 0.85): 월 숫자 하나. 좁은 달력(컨테이너 640px 이하)에서는 64px.
- **Headline** (800, 24px, 1): 날짜 숫자, 상세 행 가격, 10칸 예산 건수. 좁은 달력에서 날짜 숫자는 16px.
- **Title** (700, 20px): 섹션 제목(h2), 월 이름("2026년 10월"), 스테퍼 값. 상단 워드마크는 같은 20px을 800으로 쓴다.
- **Body** (400, 16px, 1.5): 입력값, 날짜 범위, 설명 문단(최대 70ch). 필드 라벨과 범례 머리는 같은 크기를 700으로 쓴다.
- **Label** (600–700, 14px): 칸 안 가격, 판정 표식, 범례, 보조 설명, 힌트, 링크 버튼, 요일 머리.

### Named Rules
**The Big Number Rule.** 큰 글씨는 숫자에게만 준다. 월 숫자와 날짜 숫자가 화면에서 가장 크고, 문장은 20px을 넘지 않는다.

**The One Face Rule.** Pretendard 하나만 쓴다. 공항 코드는 별도 서체가 아니라 700 굵기와 0.02em 자간으로 구분한다.

## Layout

넓은 화면은 두 단이다. 왼쪽에 380px 폼 패널, 오른쪽에 나머지 폭을 쓰는 달력 판이 있고, 상세 결과는 달력 아래에 이어진다. 전체 폭은 최대 1600px, 바깥 여백 32px, 단 사이 24px이다. 검색 버튼은 1440×900 첫 화면 안에 들어온다.

달력은 7열 그리드이며 칸 사이는 2px 틈(`seam`)이다. 상세 행도 2px 틈으로 쌓이고, 10칸 예산 슬롯은 3px 틈이다. 여백 리듬은 4·8·16·24·32·40px을 기본으로 하고, 패널 안쪽은 20–24px, 달력 판과 상세 영역 안쪽은 24–28px, 월과 월 사이는 40px이다.

반응형은 두 층이다. 창 너비 900px 이하에서 폼·달력·상세가 한 단으로 쌓이고(여백 16px), 560px 이하에서 패널 안쪽 여백이 16px로 줄어든다. 넓은 화면(901px 이상)에서는 달력이 가는 날·오는 날을 보여 주므로 폼 안 날짜 요약을 숨긴다. 달력과 상세는 창이 아니라 자기 영역 폭(container query)에 반응한다. 달력은 640px 이하에서 칸을 줄이고 가격을 만 원 단위로 바꾸며, 상세 행은 900px 이하에서 두 단, 520px 이하에서 한 단이 된다.

## Elevation & Depth

그림자는 하나도 없다. 깊이는 종이 톤의 층으로만 만든다. 책상(`desk`) 위에 용지(`paper`)가 놓이고, 용지 안의 칸·행·제출 영역은 바랜 용지(`paper-2`)로 한 단 가라앉는다. 가는 날 칸만 다시 `paper`로 올라와 먹색 윤곽을 두른다. 강조가 필요할 때는 그림자 대신 안쪽 윤곽(`outline-offset`을 음수로)을 그어 레이아웃을 흔들지 않는다.

### Named Rules
**The Flat Paper Rule.** `box-shadow`를 쓰지 않는다. 떠 보여야 하는 것은 톤을 한 단 바꾸거나 안쪽 윤곽을 긋는다.

## Shapes

모든 면과 버튼은 각진 직사각형(`rounded.none`, 0px)이다. 유일한 곡선은 펜 동그라미(`rounded.pen-circle`, 50%)로, 오는 날 날짜 숫자와 범례의 오는 날 표식에만 쓴다.

선은 역할이 정해져 있다. 날짜 칸, 상세 행, 슬롯은 선 없이 2px 틈과 톤으로 나눈다. 입력칸·칩 묶음·스테퍼는 1.5px 괘선(`line`) 테두리를 두르고, 호버하면 테두리가 `ink-3`로 짙어진다. 가는 날 칸(3px), 검토 표식·링크 버튼(1.5px), 목표가 없는 칩(2px 빨강), 고른 상세 행(3px 빨강)은 안쪽 윤곽을 쓴다.

### Named Rules
**The Square Except the Pen Rule.** 모서리는 0이다. 둥근 것은 사람이 펜으로 그린 동그라미뿐이다.

**The Seam Not Line Rule.** 달력 칸과 결과 행은 2px 틈과 톤 차이로만 나눈다. 칸 사이에 구분선을 긋지 않는다.

## Components

### Buttons
- **Shape:** 각진 직사각형(0px).
- **Primary (검색):** 도장 빨강 바탕에 흰 글자, 높이 56px, 16px 700, 돋보기 아이콘(SVG 18px)과 10px 간격. 폼 아래 `paper-2` 제출 영역의 맨 아래에 놓인다.
- **Hover / Focus / Active:** 호버하면 `action-hover`로 0.15s 바뀌고, 누르면 1px 내려간다(0.1s). 포커스는 2px 빨간 윤곽, 2px 띄움.
- **Disabled:** 책상 회색 바탕에 `ink-3` 글자, `not-allowed` 커서.
- **Link button (Google Flights에서 확인):** 1.5px 먹색 안쪽 윤곽, 높이 44px, 14px 700, 바깥 화살표 SVG 14px. 호버하면 먹색으로 채워진다. 추천 행에서는 처음부터 먹색으로 채워져 있고, 호버하면 도장 빨강이 된다.

### Chips
- **Style:** 도착 공항 칩은 먹색 활자 조각이다. 먹 바탕, 용지색 글자, 높이 36px, 공항 코드(700) 뒤에 기본 목표가 메모(14px)와 36px 삭제 버튼(× SVG 16px).
- **State:** 기본 목표가가 없는 공항은 흰 바탕에 빨간 글자와 2px 빨간 안쪽 윤곽으로 "목표가 필요"를 알린다. 삭제 버튼은 호버하면 빨개진다. 칩 묶음은 1.5px 괘선 테두리 안에 6px 틈으로 놓이고, 묶음에 포커스가 들어오면 2px 빨간 윤곽이 생긴다.
- **Route filter:** 결과 노선이 둘 이상일 때 나오는 토글 버튼 줄. `paper-2` 바탕, 높이 40px, 700, 4px 틈. 호버는 책상 회색, 선택된 것(`aria-pressed`)은 먹색 채움이다. 선택하지 않은 노선의 칸 가격은 35% 투명도로 물러난다.

### Cards / Containers
- **Corner Style:** 0px.
- **Background:** 폼 패널·달력 판·상세 영역은 `paper`, 안쪽 행과 제출 영역은 `paper-2`.
- **Shadow Strategy:** 없음(Elevation & Depth 참고).
- **Border:** 없음. 면은 책상과의 톤 차이로 떨어진다.
- **Internal Padding:** 패널 20/24px, 달력 판·상세 24/28px, 상세 행 16/20px.

### Inputs / Fields
- **Style:** 높이 46px, 1.5px 괘선 테두리, 용지 바탕, 좌우 14px. 단위가 붙는 입력(목표가 "원")은 테두리 안에 입력과 단위를 한 줄로 둔다.
- **Focus:** 2px 빨간 윤곽, 2px 띄움. 단위 입력과 칩 묶음은 안쪽 입력 대신 바깥 테두리 상자에 윤곽을 그린다(`:focus-within`).
- **Hover:** 테두리가 `ink-3`로 짙어진다.
- **Error:** 빨간 600 글자의 경고·오류 문구(`role="alert"`). 필수 표시 `(필수)`도 같은 빨강.
- **Stepper (출발일 범위·박 수):** 1.5px 괘선 테두리 안에 44px 정사각 −/+ 버튼(`paper-2`)과 가운데 20px 700 값. 호버 `desk`, 누름 `line`, 끝에 닿으면 `faint` 기호로 비활성.

### Navigation
- **Top bar:** 맨 위 검정 띠(`bar`). 왼쪽에 20px 800 워드마크, 이어서 14px `on-bar-2` 한 줄 설명. 메뉴나 링크는 없다. 좁은 화면에서는 안쪽 여백이 16px로 줄고 줄바꿈된다.

### Calendar Day Cell
- **기본:** `paper-2` 칸, 최소 높이 52px, 왼쪽 위에 24px 800 날짜 숫자. 일요일 숫자는 빨강, 토요일은 파랑, 검색 범위 밖 날짜는 흐린 숫자(`faint-number`/`faint-sun`/`faint-sat`).
- **가는 날:** `paper` 칸으로 올라와 3px 먹색 안쪽 윤곽을 두르고 최소 높이 104px로 커진다. 칸 안에 노선별 가격이 적힌다.
- **오는 날:** 날짜 숫자에 2px 빨간 펜 동그라미.
- **빈 칸:** 월 시작 전 칸은 투명.
- **검색 중:** 가는 날 칸마다 가격 자리에 70% 폭, 14px 높이의 `paper-2` 자리표시가 1.6s 주기로 숨쉬듯 흐려진다(칸 순서대로 120ms씩 늦게).

### Fare Print Marks
- **칸 안 가격:** 14px 600, 노선 코드(800) 뒤에 가격. 판정에 따라 추천은 먹색 채움, 검토는 1.5px 먹색 안쪽 윤곽, 제외는 `ink-3` 취소선, 검증 실패·시간 초과는 `ink-3` 사유 문구.
- **등장:** 결과가 오면 가격이 0.45s 동안 6px 아래에서 올라오며 잉크가 스미듯 나타난다. 가는 날 순서대로 60ms씩 늦게.
- **호버:** 가격에 밑줄. 누르면 해당 상세 행으로 이동하고 그 행에 3px 빨간 펜 윤곽이 그려진다.

### Verdict Marks
- **Style:** 높이 26px, 좌우 9px, 14px 700. 추천은 먹색 채움, 검토 필요는 1.5px 먹색 윤곽, 제외는 `ink-3` 글자에 1.5px 괘선 윤곽.
- **Usage:** 달력 판 머리의 판정별 개수와 상세 행의 노선 옆에 같은 표식을 쓴다. 제외 행의 가격은 2px 두께 회색 취소선.

### Delta Bar
- **Style:** 최대 220px, 높이 8px의 책상 회색 트랙. 채움 길이는 가격 ÷ 목표가 × 50%(최대 100%)이므로 가운데가 목표가다. 가운데에 위아래로 4px 삐져나온 2px 빨간 눈금이 목표가를 표시한다.
- **State:** 목표가 이하는 먹색 채움, 초과는 `faint` 채움. 막대 아래 차이 문구는 이하일 때 `ink`, 초과일 때 `ink-2`.

### Budget Slots
- **Style:** 최대 검색 건수만큼 3px 틈으로 나란한 16px 높이 칸. 빈 칸은 `desk`, 채워진 칸은 `ink`, 0.2s로 바뀐다.
- **Over:** 한도를 넘으면 모든 칸과 건수 숫자가 빨강이 되고 검색 버튼이 비활성된다.

### Progress
- 검색 중에는 서버가 진행 건수를 주지 않으므로 4px `paper-2` 트랙 위로 30% 길이의 먹색 막대가 1.6s 주기로 왼쪽에서 오른쪽으로 지나가는 미확정 막대를 쓴다.

## Do's and Don'ts

### Do:
- **Do** 새 화면도 회색 책상(`desk`) 위 흰 용지(`paper`) 면으로 시작하고, 안쪽 묶음은 `paper-2`로 한 단 가라앉힌다.
- **Do** 판정은 먹색 채움(추천)·먹색 1.5px 윤곽(검토)·회색 취소선(제외) 세 표식으로만 나타낸다.
- **Do** 강조 테두리는 음수 `outline-offset`의 안쪽 윤곽으로 그어 레이아웃을 흔들지 않는다.
- **Do** 값의 크기는 길이로 보여 준다. 목표가 대비 막대처럼 기준점을 빨간 눈금으로 표시한다.
- **Do** 포커스는 모든 컨트롤에서 2px 빨간 윤곽, 2px 띄움으로 통일한다.
- **Do** 움직임은 `prefers-reduced-motion: reduce`에서 애니메이션과 전환을 모두 끈다.
- **Do** 숫자에는 표 숫자(`tnum`)를 유지하고, 가장 큰 글자는 숫자에게 준다.

### Don't:
- **Don't** `box-shadow`를 쓰지 않는다.
- **Don't** 펜 동그라미(오는 날) 외에는 모서리를 둥글게 하지 않는다.
- **Don't** 파랑을 토요일 밖에서 쓰지 않는다. 링크·버튼·상태색으로 파랑을 쓰면 달력 관례가 깨진다.
- **Don't** 판정을 초록·노랑·빨강 신호등 색으로 칠하지 않는다.
- **Don't** 달력 칸이나 결과 행 사이에 구분선을 긋지 않는다. 2px 틈과 톤 차이로 나눈다.
- **Don't** 다크 모드에서 `action`을 펜 빨강(`red-dark`)으로 바꾸지 않는다. 채운 버튼은 진한 도장 빨강을 유지한다.
- **Don't** 두 번째 서체를 들이지 않는다.
