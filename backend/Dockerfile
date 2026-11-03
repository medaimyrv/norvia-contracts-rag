# Imagen única para API y worker: cambia solo el comando (ver docker-compose.yml).

# --- builder: resuelve dependencias desde uv.lock ---
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
# Primero solo los manifiestos: esta capa se cachea mientras no cambien las dependencias
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# --- runtime: sin uv ni herramientas de build ---
FROM python:3.12-slim AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/uploads && chown app:app /data/uploads
COPY --from=builder /opt/venv /opt/venv
WORKDIR /srv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
