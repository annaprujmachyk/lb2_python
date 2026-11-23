# Етап складання: встановлюємо лише потрібні залежності.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python .

# Запуск без прав root; корпус індексуємо всередині контейнера, аби шляхи збігалися.
FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 INDEX_PATH=/app/data/demo.json
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY data/demo /app/data/demo
RUN python -c "from pathlib import Path; from findex.index import build_index; from findex.store import save; save(build_index(Path('/app/data/demo')), Path('/app/data/demo.json'))" \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1
CMD ["uvicorn", "findex.web:app", "--host", "0.0.0.0", "--port", "8000"]
