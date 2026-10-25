FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Zuerst nur die Abhängigkeiten installieren: Diese Schicht wird gecacht,
# solange sich pyproject.toml und uv.lock nicht ändern.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Beim Start: Datenbank auf den neuesten Stand bringen, dann den Server starten
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
