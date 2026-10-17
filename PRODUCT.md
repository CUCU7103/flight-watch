# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

평소에는 만든 사람 본인이 로컬(127.0.0.1)에서 여행 항공권 시세를 확인하는 개인 도구로 쓴다. 공개 저장소(github.com/CUCU7103/flight-watch)와 데모로 다른 사람에게 보여 줄 때도 있어서, 처음 보는 사람도 무엇을 하는 도구인지 바로 알아야 한다.

## Product Purpose

출발일 범위 × 목적지 조합을 한 번에 검색해, 검증된 왕복 최저가만 목표가와 비교하고 코드 규칙으로 추천/검토 필요/제외를 판정한다. 성공은 "어느 날짜·노선이 목표가 이하인지"를 한 번의 검색으로 판단하고 Google Flights에서 바로 확인하는 것이다.

## Positioning

가격 비교 사이트처럼 표를 나열하지 않는다. 화면이 왕복·성인 1명·이코노미·요청 노선과 날짜인지 fail-closed로 검증한 결과만 보여 주고, 판정은 모델이 아니라 코드(목표가·경유 8시간·공항 변경 하드 룰)가 소유한다.

## Operating Context

- 검색 1건 = 출발일 하나 × 목적지 하나. 한 번에 최대 10건, 가장 늦은 귀국일이 오늘부터 330일 이내.
- 보통 건당 2~3초, 대체 경로(Jev 에이전트)로 넘어가면 약 20초, 건당 최대 2분. 진행률은 서버가 주지 않는다(전체 완료 후 한 번에 결과).
- 검색은 동시에 1회만(409). 기록은 서버 메모리라 재시작하면 사라진다.
- 결과는 Google Flights 검색 URL로 넘겨 사용자가 직접 확인한다.

## Capabilities and Constraints

- 기본 노선 ICN → FUK(목표가 180,000원), NRT(250,000원). 그 외 공항은 목표가 직접 입력 필수.
- 판정 라벨: 추천(SEND_URGENT_ALERT) / 검토 필요(SAVE_TO_DAILY_DIGEST) / 제외(DISCARD). 결과 상태: ERROR·TIMEOUT·BLOCKED·INVALID_RESULT.
- Cheapest 탭 가격은 조건 미확인 참고값이라 판정에 쓰지 않고 안내만 한다.
- 웹에서는 알림을 보내지 않는다(dry_run). 예약·로그인·결제를 하지 않는다.
- 유료 모델 API 호출 가능성(대체 경로, 목표가 이하 평가)을 사용자에게 알린다.
- 서버리스 배포 불가(로컬 Chrome 사용). 인증 없음.

## Brand Commitments

시각 자산(이름 표기, 루프 영상, 아이콘)은 모두 교체 가능하다고 확인했다(2026-10-17). 지도 타일을 쓰는 이미지·영상을 계속 쓰면 출처 표기("지도: Esri, HERE, Garmin, © OpenStreetMap contributors")가 보여야 한다.

## Evidence on Hand

- `web/public/hero-flights.mp4`, `hero-flights.jpg`: HyperFrames로 만든 세계 노선 루프 영상(지도 타일 출처 표기 필요).
- 실제 사용자 후기·사용자 수·벤치마크는 없다. 만들어 넣지 않는다.

## Product Principles

1. 검증된 것만 보여 준다. 확인 못 한 값은 참고값·실패로 분명히 구분한다.
2. 판정은 코드가 한다. 화면은 판정 이유(목표가 대비 차이)를 숫자로 드러낸다.
3. 할 수 없는 일(예약, 알림)과 비용(유료 API)을 숨기지 않는다.
4. 결정은 Google Flights에서 사용자가 직접 한다. 이 도구는 후보를 좁혀 준다.
