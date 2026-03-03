FROM astral/uv:python3.11-bookworm-slim AS builder

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project --no-dev

FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY sage_api/ sage_api/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PORT=8080

RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE ${PORT}

CMD ["sh", "-c", "exec uvicorn sage_api.main:app --host 0.0.0.0 --port $PORT"]
