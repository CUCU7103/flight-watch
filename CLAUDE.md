# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 저장소 구성

- `backend/` — 스캐너와 FastAPI 서버. Python 3.12+, `uv` 기반(`uv.lock`). 백엔드 명령은 `backend/`에서 실행한다.
- `web/` — Vite + React + TypeScript 화면(pnpm). 개발 서버가 `/api`를 `127.0.0.1:8000`으로 프록시한다.
- `backend/jev_ultrafast/` 는 `browser-use/jev-ultrafast`(MIT, `NOTICE` 참고)에서 가져온 업스트림 코드다. 스캐너(`src/flight_scanner/`)가 이를 라이브러리로 import 한다. 업스트림 데모는 삭제했다.

## 명령어 (`backend/`에서)

```bash
uv sync                                   # 의존성 설치 (dev 그룹 포함)
uv run pytest                             # 전체 테스트
uv run pytest tests/test_cli.py::test_name  # 단일 테스트
uv run ruff check .                       # line-length 120, 규칙 E/F/I (업스트림 파일은 ruff format 미적용 상태라 format --check는 실패한다)
uv run mypy                               # src/flight_scanner 만 대상

# 웹 API (알림 없음). FLIGHT_WATCH_FIXTURE를 주면 브라우저·유료 API 없이 fixture 재생
uv run uvicorn flight_scanner.api:app --host 127.0.0.1
FLIGHT_WATCH_FIXTURE=tests/fixtures/verified_roundtrip.json uv run uvicorn flight_scanner.api:app --host 127.0.0.1

# 스캐너 (flight-scanner = flight_scanner.cli:main)
uv run flight-scanner --plan-only                       # 작업 목록만 생성, 브라우저/API 미사용
uv run flight-scanner --fixture tests/fixtures/captured_fuk_20261014.json --dry-run   # 오프라인 재생
uv run flight-scanner --dry-run                         # 실제 스캔 + Jev 호출, Slack/Redis 미사용
```

- 실제 스캔에는 `TYPESAFE_API_KEY`와 Chrome이 필요하다(`.env.example` 참고, 비표준 경로는 `CHROME_PATH`). 결과는 `artifacts/scans/latest.json`에 원자적으로 쓰인다.
- `tests/test_redis_integration.py`는 `REDIS_TEST_URL`(일회용 서버)이 있을 때만 실행된다. 키를 flush/열거하지 않는다.
- `FLIGHT_WATCH_CHROME_TEST=1`이면 실제 headless Chrome으로 `dedicated_browser()` 재진입 테스트를 돌린다(임시 프로필, 외부 사이트·유료 API 없음). browser_harness는 import 시점에 `BH_*` 경로를 고정하므로 같은 프로세스에서 harness 모듈을 직접 import해 데몬을 확인하면 안 된다(`browser.daemon_ready` 참고).
- `scripts/check_guards.py`는 로컬 브라우저(browser-harness 기본 데몬)가 필요한 수동 점검 도구이며 pytest에 포함되지 않는다.
- 웹(`web/`에서): `pnpm dev`(http://localhost:5173), `pnpm build`(tsc 포함), `pnpm lint`(oxlint).
- `--destination`이 FUK/NRT가 아니면 `--target-price`가 필수다(기본 목표가는 `models.DEFAULT_TARGETS_KRW`).

## 아키텍처 (`src/flight_scanner/`)

파이프라인: **작업 생성 → 격리 스캔 → 결정론적 필터 → 평가 → 알림**. `cli.py`의 `run_jobs`/`process_results`가 전체를 엮는다.

1. `models.py` — `ScanJob`(검증된 불변 작업), `FlightOption`, `Evaluation`, `ScanResult`와 `generate_jobs`(날짜×목적지 조합).
2. `browser.py` — `dedicated_browser()`가 임시 프로필의 헤드리스 Chrome과 browser-harness 데몬을 직접 띄운다(사용자의 Chrome에 절대 붙지 않음). 작업마다 `spawn` 프로세스(`_run_job`)에서 `jev_ultrafast.Agent`를 `extract.search_url(job)`(결과 페이지 직행 URL)로 연다. `wait_for_direct_results`가 옵션을 검증하고 `STABLE_OBSERVATIONS`(3)번 연속 같으면 모델 호출 없이 끝내고, `DIRECT_RESULTS_TIMEOUT`(8s) 안에 실패하면 `open_search_form`으로 같은 탭을 빈 폼으로 옮겨 원래 에이전트 흐름을 돈다(채워진 결과 페이지에서 에이전트를 시작하면 입력할 값이 없어 막힌다). 넘어간 이유는 `ScanResult.fallback_reason`에 경로·개수만 남긴다(`left_results:<path>`/`search_unverified`/`no_options`/`unstable:<n>`). 폼을 열지 못하면 모델을 부르지 않고 `ERROR`로 끝낸다. 결과가 검증되면(두 경로 모두) `check_return`이 최저가 가는 편 카드를 코드로 직접 눌러 오는 편 목록을 열고, 오는 편 최저가가 가는 편 "From" 가격과 같을 때만 `return_verified`와 경유 시간(`extract.layover_hours`)을 채운다. 공항 변경은 양쪽 직항일 때만 `False`로 확정한다. 확인하지 못해도 결과는 그대로 두고 `ScanResult.return_reason`에 사유만 남긴다(`outbound_unverified`/`outbound_stale`/`outbound_click_failed`/`return_unverified`/`return_unstable:<n>`/`return_price_mismatch`/`separate_tickets`(별도 발권은 왕복으로 확정하지 않음)/`return_error`(Google 오류 화면)/`left_results:<path>`/`no_time`/`error:<Type>`, `RETURN_RESULTS_TIMEOUT`=8s). 에이전트 경로에서는 `JOB_TIMEOUT`까지 여유가 없으면 확인을 건너뛴다(`no_time`). 수하물은 결과 화면에 없어 실검색에서는 늘 미확인이므로 `conditions_complete`가 참이 되지 않는다. 타임아웃(`JOB_TIMEOUT`=120s, `MAX_STEPS`=50) 시 종료한다. 대체 경로는 에이전트 시작 전에 최대 약 38초(초기화 15 + 직접 대기 8 + 폼 15)를 쓸 수 있다. 환경변수(`BU_*`, `BH_*`)로 네임스페이스를 격리하므로 `scan()`은 그 컨텍스트 밖에서 호출하면 거부된다.
3. `extract.py` — 페이지 스냅샷에서 가격/일정을 **fail-closed**로 검증해 `FlightOption`을 만든다(검색 URL protobuf 파싱 포함). 검증 실패 시 옵션을 만들지 않는다(`INVALID_RESULT`). `cheapest_tab_price`는 Cheapest 탭 라벨의 가격을 `ScanResult.cheapest_tab_krw`에 참고값으로만 남긴다(조건 미확인이라 판정에 쓰지 않음).
4. `evaluate.py` — TypeSafe System One(`/v1/systemone`)에 noul/score/choice 질문을 보내 `Evaluation`을 얻고, `route()`가 코드로 최종 액션(`SEND_URGENT_ALERT`/`SAVE_TO_DAILY_DIGEST`/`DISCARD`)을 결정한다. 모델은 조언만 하고 임계값·하드 룰(`violates_hard_rules`: 경유 8시간 이상, 공항 변경, 목표가 초과 → DISCARD)은 코드가 소유한다. 하드 룰은 `process_results`가 평가 전에 먼저 적용하므로 평가를 못 한 결과에도 걸린다.
5. `notify.py` — Redis 클레임(`flight_alert:<fingerprint>`)으로 동시 중복 전송을 막고 Slack 웹훅(`hooks.slack.com`만 허용)으로 보낸다. 상태: `SENT/DUPLICATE/DRY_RUN/FAILED/UNCERTAIN/DEFERRED/NOT_CONFIGURED`. Slack은 exactly-once가 없으므로 전송 후 불확실하면 클레임을 풀지 않고 `uncertain`으로 TTL 보관한다.
6. `api.py` — 웹 진입점. `POST /api/scans` → 백그라운드 스레드에서 runner 실행 → `GET /api/scans/{id}`(상태)·`/results`(`process_results` 행에서 `usage`만 뺀 것, `public_row`). `POST /api/itineraries`(`scan_id`+결과 `index`)는 서버가 가진 행에서 여행 조건을 꺼내 주입된 `planner`(`itinerary.gemini_planner`, `GEMINI_API_KEY`가 없으면 None → 503, `/api/config`의 `itinerary_enabled`=false)로 코스를 만들고 `Trip` 단위로 메모리 캐시한다. 스캔 잠금과 무관하다. runner는 주입식(`live_runner` 또는 `fixture_runner`)이고 항상 `dry_run=True`라 웹에서는 알림을 보내지 않는다. `dedicated_browser()`가 전역 `os.environ`을 바꾸므로 스캔은 Lock으로 1건만 돌리고(409), 작업 수는 `MAX_JOBS`=30으로 제한한다. 라이브 앱은 `WarmBrowser`로 Chrome을 검색 사이에 재사용하고(`daemon_ready`로 생존 확인 후 재기동) lifespan 종료 때 정리한다. 상태는 메모리 보관이다.
7. `itinerary.py` — 여행 코스. `outbound_arrival`이 가는 편 카드 텍스트에서 도착 시각만 코드로 뽑고(익일·불명이면 None), Gemini(`client.interactions.create`, JSON 스키마)에는 공항·날짜·시각 같은 구조화 값만 보낸다(evidence 원문 금지). `parse_itinerary`가 스키마(시간대 Literal, 길이 상한, 추가 필드 거절)와 일자 수(`nights+1`)를 검증하고 실패하면 ValueError(→ 502). 429는 무료 한도 초과로 구분한다. 귀국편 시각은 저장하지 않으므로 마지막 날은 오전만 계획한다.

## 설계 원칙 (변경 시 유지해야 함)

- **모델이 선택하고 코드가 실행한다.** Jev가 고른 액션도 `browser.validate_action`이 관측된 액션인지, 허용 목록(검색 컨트롤만)에 있는지, 예약/로그인/결제 라벨이 아닌지, 링크가 `www.google.com/travel/flights` 안인지 검증한 뒤에만 실행한다. 항목을 완화할 때는 이 allowlist 구조를 유지한다. 예외는 `check_return`의 가는 편 카드 클릭 하나뿐이다. 모델이 아니라 코드가 검증된 결과 페이지에서 고른 카드만 누르고, 오는 편 카드(누르면 예약 옵션·항공사 외부 링크로 넘어감)는 누르지 않는다.
- 예약·로그인·결제·외부 사이트 방문은 금지다. 에러/실패 사유에는 예외 타입명만 남기고 공급자 응답 본문이나 자격증명을 저장하지 않는다.
- `--fixture`는 `--dry-run` 전용 오프라인 재생이며 알림을 보낼 수 없다(`process_results(offline=True)`).
- 모든 조건(`conditions_complete`: 왕복 구간·수하물·경유시간·공항변경)이 확인된 경우에만 평가/긴급 알림 대상이 된다.
- 종료 코드: `status != DONE`, `evaluation_error`, 알림 상태가 `FAILED/UNCERTAIN/DEFERRED/NOT_CONFIGURED`면 1.

## 언어 규칙

사용자 전역 규칙에 따라 응답·코드 주석·커밋 메시지·문서는 한국어, 식별자는 영어로 쓴다.
