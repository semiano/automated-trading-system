FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY config.yaml ./config.yaml

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && chown -R appuser:appuser /app

USER appuser

ENV MDTAS_CONFIG_PATH=/app/config.yaml

CMD ["python", "-m", "services.ingestion_main"]
