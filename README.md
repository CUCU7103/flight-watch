# flight-watch

출발 공항, 도착 공항, 날짜를 입력하면 Google Flights에서 왕복 항공권 최저가를 검색해 목록으로 보여 주는 웹앱입니다. 예약, 로그인, 결제는 하지 않습니다.

- 기본 노선은 인천(ICN)에서 후쿠오카(FUK), 도쿄 나리타(NRT)로 가는 왕복입니다. 다른 노선은 IATA 공항 코드와 목표가(원)를 직접 입력합니다.
- 검색 결과는 화면에만 표시하고 Slack 알림은 보내지 않습니다.

## 구성

| 경로 | 내용 |
|------|------|
| `backend/` | Python 3.12 스캐너와 FastAPI 서버. 헤드리스 Chrome으로 Google Flights 결과 페이지를 직접 열어 검증하고, 실패하면 TypeSafe Jev 모델이 검색 화면을 조작합니다 |
| `web/` | Vite + React 화면. 검색 폼, 진행 상태, 결과 목록 |

## 준비

- [uv](https://docs.astral.sh/uv/), Node.js 24, pnpm
- Google Chrome. 표준 위치가 아니면 `CHROME_PATH`를 지정합니다.
- 실검색에는 `TYPESAFE_API_KEY` 환경변수가 필요합니다. 서버는 `.env` 파일을 자동으로 읽지 않습니다. 셸에서 export하거나, `backend/.env.example`을 복사해 `backend/.env`를 만든 뒤 `uv run --env-file .env uvicorn ...`으로 실행하세요.

```bash
(cd backend && uv sync)
(cd web && pnpm install)
```

## 실행

터미널 두 개를 씁니다.

```bash
# 1) API 서버 (127.0.0.1:8000)
cd backend
TYPESAFE_API_KEY=... uv run uvicorn flight_scanner.api:app --host 127.0.0.1

# 2) 화면 (http://localhost:5173, /api는 8000으로 프록시)
cd web
pnpm dev
```

### 비용 없이 화면만 확인하기

`FLIGHT_WATCH_FIXTURE`를 주면 브라우저와 유료 API 없이 저장된 검색 결과를 재생합니다.

```bash
cd backend
FLIGHT_WATCH_FIXTURE=tests/fixtures/verified_roundtrip.json uv run uvicorn flight_scanner.api:app --host 127.0.0.1
```

fixture는 ICN → FUK, 2026-11-12 출발, 3박, 출발일 수 1로 저장돼 있습니다. 폼에도 같은 값을 넣어야 결과가 나옵니다. 다른 값을 넣으면 검증 실패로 표시됩니다. fixture 모드는 출발일 검증 기준일을 fixture 출발 전날로 고정하므로, 이 날짜가 지나도 재생할 수 있습니다.

## 비용과 제한

- 검색 1건은 출발일 하나와 목적지 하나의 조합입니다. 보통은 검색 URL로 결과 페이지를 바로 열어 검증하므로 모델 호출이 없습니다(실측 약 2~3초). 결과 페이지를 8초 안에 검증하지 못하면 빈 검색 폼에서 Jev 에이전트가 처음부터 조작합니다. 이때는 모델을 15~20회 호출하고, 기다린 시간까지 합쳐 약 20초 걸립니다.
- 목표가 이하이면서 조건(왕복 구간, 수하물, 경유, 공항 변경)이 모두 확인된 결과는 평가 모델을 한 번 호출합니다.
- 한 번에 최대 10건(출발일 수 × 목적지 수)까지, 가장 늦은 귀국일이 오늘부터 330일 이내인 일정만 검색할 수 있습니다. 검색은 동시에 1회만 실행되고, 건당 최대 2분에서 끊습니다.
- 서버는 전용 Chrome을 검색 사이에 열어 두고(첫 검색만 기동 약 2초), 서버를 끄면 함께 정리합니다.
- 검색 기록은 서버 메모리에만 있어서 서버를 다시 시작하면 사라집니다.
- 서버에는 인증이 없습니다. 그래서 `127.0.0.1`에서만 열어 둡니다.
- Chrome을 직접 실행하므로 Vercel 같은 서버리스 환경에는 배포할 수 없습니다. VPS나 컨테이너가 필요합니다.
- 결과는 Google Flights 화면이 왕복, 성인 1명, 이코노미, 요청한 노선과 날짜인지 검증한 뒤에만 표시합니다. 검증이 안 되면 "검증 실패"로 표시합니다.

## CLI

웹 없이 스캐너만 쓸 수도 있습니다. 예를 들어 작업 목록만 만들려면 다음처럼 실행합니다.

```bash
cd backend
uv run flight-scanner --plan-only
```

CLI는 Slack 알림과 Redis 중복 방지도 지원합니다. 옵션은 `uv run flight-scanner --help`로 확인하세요.

## 개발

```bash
(cd backend && uv run pytest && uv run ruff check . && uv run mypy)
(cd web && pnpm build && pnpm lint)
```

## 라이선스

스캐너와 `backend/jev_ultrafast/`는 [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)(MIT)를 기반으로 합니다. 자세한 내용은 [NOTICE](NOTICE)와 [backend/LICENSE](backend/LICENSE)를 참고하세요.
