# flight-watch

출발 공항, 도착 공항, 날짜를 입력하면 Google Flights에서 왕복 항공권 최저가를 검색해 목록으로 보여 주는 웹앱입니다. 예약, 로그인, 결제는 하지 않습니다.

- 기본 노선은 인천(ICN)에서 후쿠오카(FUK), 도쿄 나리타(NRT)로 가는 왕복입니다. 다른 노선은 IATA 공항 코드와 목표가(원)를 직접 입력합니다.
- 검색 결과는 화면에만 표시하고 Slack 알림은 보내지 않습니다.
- 결과마다 확인한 조건(오는 편 일정, 수하물, 최대 경유 시간, 공항 변경)을 함께 보여 줍니다. 같은 노선·날짜의 네이버 항공권 검색 결과를 바로 열어 비교할 수도 있습니다. 네이버 화면은 수집하지 않고 링크만 엽니다.
- 항공권이 확인된 결과에서 "여행 코스 보기"를 누르면 도착 공항 주변 권역의 일자별 여행 코스를 만들어 보여 줍니다(Gemini, `GEMINI_API_KEY`가 있을 때만 버튼이 보입니다).

## 구성

| 경로 | 내용 |
|------|------|
| `backend/` | Python 3.12 스캐너와 FastAPI 서버. 헤드리스 Chrome으로 Google Flights 결과 페이지를 직접 열어 검증하고, 실패하면 TypeSafe Jev 모델이 검색 화면을 조작합니다 |
| `web/` | Vite + React 화면. 검색 폼, 진행 상태, 결과 목록 |

## 준비

- [uv](https://docs.astral.sh/uv/), Node.js 24, pnpm
- Google Chrome. 표준 위치가 아니면 `CHROME_PATH`를 지정합니다.
- 여행 코스에는 `GEMINI_API_KEY`가 필요합니다([Google AI Studio](https://aistudio.google.com/apikey)에서 무료 발급). 없으면 코스 기능만 꺼집니다.
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

fixture는 ICN → FUK, 2026-11-12 출발, 3박, 출발일 수 1로 저장돼 있습니다. 폼에도 같은 값을 넣어야 결과가 나옵니다. 다른 값을 넣으면 검증 실패로 표시됩니다. fixture 모드는 출발일 검증 기준일을 fixture 출발 전날로 고정하므로, 이 날짜가 지나도 재생할 수 있습니다. fixture 모드에서도 `GEMINI_API_KEY`를 직접 넣었을 때만 여행 코스가 Gemini를 호출합니다.

## 비용과 제한

- 검색 1건은 출발일 하나와 목적지 하나의 조합입니다. 보통은 검색 URL로 결과 페이지를 바로 열어 검증하고, 최저가 가는 편을 눌러 오는 편 일정과 경유까지 확인하므로 모델 호출이 없습니다(실측 약 2~5초). 수하물 포함 여부는 Google 결과 화면에 나오지 않아 확인하지 않습니다. 결과 페이지를 8초 안에 검증하지 못하면 빈 검색 폼에서 Jev 에이전트가 처음부터 조작합니다. 이때는 모델을 15~20회 호출하고, 기다린 시간까지 합쳐 약 20초 걸립니다.
- 목표가 이하이면서 조건(왕복 구간, 수하물, 경유, 공항 변경)이 모두 확인된 결과는 평가 모델을 한 번 호출합니다. 목표가 이하라도 경유가 8시간 이상이거나 공항이 바뀌는 항공권은 평가하지 않고 제외합니다.
- 한 번에 최대 30건(출발일 수 × 목적지 수)까지, 가장 늦은 귀국일이 오늘부터 330일 이내인 일정만 검색할 수 있습니다. 검색은 동시에 1회만 실행되고(3건씩 병렬), 건당 최대 2분에서 끊습니다. 30건은 실측 약 46초 걸렸습니다.
- 서버는 전용 Chrome을 검색 사이에 열어 두고(첫 검색만 기동 약 2초), 서버를 끄면 함께 정리합니다.
- 여행 코스는 누를 때만 Gemini(`gemini-3.5-flash-lite`, `GEMINI_MODEL`로 변경)를 호출하고(실패하면 SDK가 몇 번 재시도합니다), 같은 공항·날짜·도착 시각이면 서버 메모리의 결과를 다시 씁니다. 무료 등급은 하루 호출 한도가 있고 입력이 Google 제품 개선에 쓰일 수 있습니다. 모델에는 공항·날짜·도착 시각만 보내고 화면 원문은 보내지 않습니다. 가는 편 도착 시각은 결과 카드에서 읽고(못 읽거나 익일 도착이면 오후 도착으로 가정), 귀국편 시각은 저장하지 않아 마지막 날은 오전 일정만 넣습니다. 응답은 일자 수·시간대·글자 수를 코드가 검증하고, 맞지 않으면 버립니다.
- 검색 기록은 서버 메모리에만 있어서 서버를 다시 시작하면 사라집니다.
- Supabase 설정이 없으면 서버에 인증이 없습니다. 그래서 `127.0.0.1`에서만 열어 둡니다. 외부에 열려면 아래 "회원 전용 배포"를 따릅니다.
- 스캐너는 Chrome을 직접 실행하므로 Vercel 같은 서버리스 환경에는 배포할 수 없습니다. VPS나 컨테이너가 필요합니다. 화면(`web/`)만 Vercel에 올립니다.
- 결과는 Google Flights 화면이 왕복, 성인 1명, 이코노미, 요청한 노선과 날짜인지 검증한 뒤에만 표시합니다. 검증이 안 되면 "검증 실패"로 표시합니다.
- 오는 편은 최저가 가는 편을 눌러 나온 오는 편 목록에서 확인합니다. 다음 경우에는 결과는 그대로 두고 "오는 편 미확인"으로 표시합니다.
  - 오는 편 최저가가 가는 편에 표시된 왕복 가격과 다를 때
  - 별도 발권(편도 두 장을 따로 사는 조합)일 때. 한쪽이 지연·결항돼도 다른 쪽은 보호받지 못하므로 왕복으로 보지 않습니다.
  - Google이 오는 편 목록 대신 오류 화면을 띄울 때
- 최저가는 결과 화면에 보이는 항공권 중에서 고릅니다. Google Flights의 Cheapest 탭 가격이 더 낮으면 참고로 함께 표시합니다. 이 가격은 공항 변경이나 수하물 같은 조건을 확인하지 못한 값이라 판정에는 쓰지 않습니다.

## 회원 전용 배포 (Supabase + Vercel)

가입한 회원만 검색할 수 있게 하려면 로그인은 Supabase Auth, 화면은 Vercel, 스캐너는 Chrome이 도는 서버에 둡니다. 화면은 휴대폰 너비(375px)에서도 한 줄로 쌓여 보입니다.

1. Supabase 프로젝트를 만들고 Project URL과 publishable(anon) 키를 확인합니다. 회원은 초대제로 받습니다. Authentication 설정에서 공개 가입(Allow new users to sign up)을 끄고, Site URL과 Redirect URL에 Vercel 주소를 넣습니다(안 넣으면 초대·재설정 메일 링크가 localhost로 갑니다). 회원은 Authentication → Users → Invite user로 초대합니다.
2. 스캐너 서버(아래 "Oracle Cloud에 스캐너 올리기")에 `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `FLIGHT_WATCH_ALLOWED_HOSTS`(서버 공개 호스트), `FLIGHT_WATCH_CORS_ORIGINS`(Vercel 주소)를 줍니다(`backend/.env.example` 참고). Supabase 값 둘 중 하나라도 빠졌는데 다른 배포 값이 있으면 서버가 뜨지 않습니다. 하나도 없으면 127.0.0.1 전용·로그인 없음으로 뜹니다.
3. Vercel에서 Root Directory를 `web`으로 지정하고, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_BASE`(스캐너 서버 주소)를 환경변수로 넣어 배포합니다(`web/.env.example` 참고).

### Oracle Cloud에 스캐너 올리기

스캐너는 Chrome이 계속 떠 있어야 해서 Oracle Cloud Always Free의 Ampere(ARM) VM에 올립니다. `deploy/`는 스캐너 컨테이너와 HTTPS 프록시(Caddy)를 함께 띄웁니다. 도메인이 없으면 공인 IP로 만든 `sslip.io` 이름에 Let's Encrypt 인증서를 받습니다.

1. Oracle Cloud에서 인스턴스를 만듭니다. Shape는 `VM.Standard.A1.Flex`(예: 2 OCPU, 12GB), 이미지는 Ubuntu 24.04로 합니다. 리전은 홈 리전에서만 무료이므로 가입 때 고른 리전(서울 또는 춘천)을 씁니다.
2. 네트워크: 서브넷 Security List에 TCP 80, 443 인바운드를 추가합니다. Ubuntu 이미지는 iptables로도 막혀 있어서 VM에서 한 번 더 엽니다.
   ```bash
   sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443 -j ACCEPT
   sudo apt-get install -y iptables-persistent && sudo netfilter-persistent save
   ```
3. Docker를 설치하고 저장소를 받습니다.
   ```bash
   curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER   # 다시 로그인
   git clone https://github.com/CUCU7103/flight-watch.git && cd flight-watch/deploy
   cp .env.example .env   # SCANNER_HOST=<공인IP의 점을 하이픈으로>.sslip.io 와 나머지 값을 채운다
   docker compose up -d --build
   ```
4. `curl https://<SCANNER_HOST>/api/config`가 401이면 정상입니다(로그인이 필요하다는 뜻). Vercel의 `VITE_API_BASE`를 `https://<SCANNER_HOST>`로 둡니다.
5. 업데이트할 때는 `git pull && docker compose up -d --build`를 실행합니다.

컨테이너 참고:
- 이미지는 Google Chrome 대신 Debian Chromium을 씁니다. ARM용 Google Chrome 빌드가 없기 때문입니다.
- Docker 기본 seccomp가 Chromium 샌드박스를 막아서, 이 이미지에서만 `CHROME_NO_SANDBOX=1`로 샌드박스를 끕니다. 비root 사용자이고 추가 권한이 없는 컨테이너가 격리를 맡습니다.
- browser-harness 텔레메트리는 끕니다(`BH_TELEMETRY=0`).
- 데이터센터 IP는 가정용 IP보다 Google이 자동화로 의심할 가능성이 높습니다. 올린 뒤 1건만 검색해 결과가 "검증 실패" 없이 나오는지 먼저 확인합니다. 결과 페이지를 읽지 못하면 유료 에이전트 경로로 넘어갑니다.
- Oracle은 오래 쓰지 않는 Always Free 인스턴스를 회수할 수 있습니다.

동작:
- 모든 `/api` 요청에 `Authorization: Bearer <Supabase 액세스 토큰>`이 필요합니다. 서버는 Supabase `/auth/v1/user`로 토큰을 확인하고, 확인된 토큰은 60초 동안 메모리에 보관합니다(로그아웃하거나 만료된 토큰도 이 시간 동안은 통과합니다). Supabase에 연결하지 못하면 요청을 거절합니다(503).
- 검색은 시작한 회원에게만 보입니다. 다른 회원의 검색 id로 조회하면 404입니다.
- 검색은 서버 전체에서 동시에 1건이므로, 다른 회원이 검색 중이면 409를 받습니다.
- 화면에는 가입 버튼이 없습니다. 초대 메일 링크를 누르면 비밀번호 설정 화면이 열리고, 이후 이메일·비밀번호로 로그인합니다. "비밀번호를 잊었나요?"는 재설정 메일을 보내고 같은 화면으로 돌아옵니다.
- Supabase에서 공개 가입을 끄지 않으면 API로 직접 가입할 수 있으므로 반드시 끕니다.

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
