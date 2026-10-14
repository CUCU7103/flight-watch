# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 저장소 구성

- `backend/` — 실제 코드 전부. Python 3.12+, `uv` 기반(`uv.lock`). 모든 명령은 `backend/`에서 실행한다.
- `web/` — 비어 있음(아직 미구현).
- `backend/jev_ultrafast/` 는 `browser-use/jev-ultrafast`(MIT, `NOTICE` 참고)에서 가져온 업스트림 코드다. 스캐너(`src/flight_scanner/`)가 이를 라이브러리로 import 한다. 업스트림 데모(`jev` 스크립트, `static/`, `demo.py`)는 스캐너와 무관하다.

## 명령어 (`backend/`에서)

```bash
uv sync                                   # 의존성 설치 (dev 그룹 포함)
uv run pytest                             # 전체 테스트
uv run pytest tests/test_cli.py::test_name  # 단일 테스트
uv run ruff check . && uv run ruff format --check .   # line-length 120, 규칙 E/F/I
uv run mypy                               # src/flight_scanner 만 대상

# 스캐너 (flight-scanner = flight_scanner.cli:main)
uv run flight-scanner --plan-only                       # 작업 목록만 생성, 브라우저/API 미사용
uv run flight-scanner --fixture tests/fixtures/captured_fuk_20261014.json --dry-run   # 오프라인 재생
uv run flight-scanner --dry-run                         # 실제 스캔 + Jev 호출, Slack/Redis 미사용
```

- 실제 스캔에는 `TYPESAFE_API_KEY`와 Chrome이 필요하다(`.env.example` 참고, 비표준 경로는 `CHROME_PATH`). 결과는 `artifacts/scans/latest.json`에 원자적으로 쓰인다.
- `tests/test_redis_integration.py`는 `REDIS_TEST_URL`(일회용 서버)이 있을 때만 실행된다. 키를 flush/열거하지 않는다.
- `scripts/`의 `smoke.py`, `measure_flights.py`, `record_flights.py` 등은 유료 모델 API나 라이브 사이트를 쓰는 수동 도구이며 pytest에 포함되지 않는다.
- `--destination`이 FUK/NRT가 아니면 `--target-price`가 필수다(기본 목표가는 `models.DEFAULT_TARGETS_KRW`).

## 아키텍처 (`src/flight_scanner/`)

파이프라인: **작업 생성 → 격리 스캔 → 결정론적 필터 → 평가 → 알림**. `cli.py`의 `run_jobs`/`process_results`가 전체를 엮는다.

1. `models.py` — `ScanJob`(검증된 불변 작업), `FlightOption`, `Evaluation`, `ScanResult`와 `generate_jobs`(날짜×목적지 조합).
2. `browser.py` — `dedicated_browser()`가 임시 프로필의 헤드리스 Chrome과 browser-harness 데몬을 직접 띄운다(사용자의 Chrome에 절대 붙지 않음). 작업마다 `spawn` 프로세스(`_run_job`)에서 `jev_ultrafast.Agent`를 돌리고, 타임아웃(`JOB_TIMEOUT`=120s, `MAX_STEPS`=50) 시 종료한다. 환경변수(`BU_*`, `BH_*`)로 네임스페이스를 격리하므로 `scan()`은 그 컨텍스트 밖에서 호출하면 거부된다.
3. `extract.py` — 페이지 스냅샷에서 가격/일정을 **fail-closed**로 검증해 `FlightOption`을 만든다(검색 URL protobuf 파싱 포함). 검증 실패 시 옵션을 만들지 않는다(`INVALID_RESULT`).
4. `evaluate.py` — TypeSafe System One(`/v1/systemone`)에 noul/score/choice 질문을 보내 `Evaluation`을 얻고, `route()`가 코드로 최종 액션(`SEND_URGENT_ALERT`/`SAVE_TO_DAILY_DIGEST`/`DISCARD`)을 결정한다. 모델은 조언만 하고 임계값·하드 룰(경유 8시간 이상, 공항 변경, 목표가 초과 → DISCARD)은 코드가 소유한다.
5. `notify.py` — Redis 클레임(`flight_alert:<fingerprint>`)으로 동시 중복 전송을 막고 Slack 웹훅(`hooks.slack.com`만 허용)으로 보낸다. 상태: `SENT/DUPLICATE/DRY_RUN/FAILED/UNCERTAIN/DEFERRED/NOT_CONFIGURED`. Slack은 exactly-once가 없으므로 전송 후 불확실하면 클레임을 풀지 않고 `uncertain`으로 TTL 보관한다.

## 설계 원칙 (변경 시 유지해야 함)

- **모델이 선택하고 코드가 실행한다.** Jev가 고른 액션도 `browser.validate_action`이 관측된 액션인지, 허용 목록(검색 컨트롤만)에 있는지, 예약/로그인/결제 라벨이 아닌지, 링크가 `www.google.com/travel/flights` 안인지 검증한 뒤에만 실행한다. 항목을 완화할 때는 이 allowlist 구조를 유지한다.
- 예약·로그인·결제·외부 사이트 방문은 금지다. 에러/실패 사유에는 예외 타입명만 남기고 공급자 응답 본문이나 자격증명을 저장하지 않는다.
- `--fixture`는 `--dry-run` 전용 오프라인 재생이며 알림을 보낼 수 없다(`process_results(offline=True)`).
- 모든 조건(`conditions_complete`: 왕복 구간·수하물·경유시간·공항변경)이 확인된 경우에만 평가/긴급 알림 대상이 된다.
- 종료 코드: `status != DONE`, `evaluation_error`, 알림 상태가 `FAILED/UNCERTAIN/DEFERRED/NOT_CONFIGURED`면 1.

## 언어 규칙

사용자 전역 규칙에 따라 응답·코드 주석·커밋 메시지·문서는 한국어, 식별자는 영어로 쓴다.
