# 스캐너 API 컨테이너. Oracle Cloud Ampere(ARM)에서도 돌도록 Google Chrome 대신 Debian Chromium을 쓴다.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv

WORKDIR /app
# 의존성 레이어를 먼저 만들어 코드만 바뀌면 다시 받지 않는다.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY LICENSE ./
COPY jev_ultrafast ./jev_ultrafast
COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --create-home scanner
USER scanner
ENV PATH=/app/.venv/bin:$PATH \
    CHROME_PATH=/usr/bin/chromium \
    CHROME_NO_SANDBOX=1 \
    BH_TELEMETRY=0 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "flight_scanner.api:app", "--host", "0.0.0.0", "--port", "8000"]
