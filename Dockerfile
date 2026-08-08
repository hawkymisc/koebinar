FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data
COPY remotion ./remotion
COPY prompts ./prompts

RUN pip install --no-cache-dir -e .

ENV KOEBINAR_DATA_DIR=/data/storage \
    KOEBINAR_ARTIFACTS_DIR=/data/artifacts \
    KOEBINAR_DB_PATH=/data/storage/koebinar.db \
    KOEBINAR_SYNC_PIPELINE=false

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "koebinar.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
