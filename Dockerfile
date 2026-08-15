FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates ffmpeg gnupg fonts-noto-cjk \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcairo2 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libnss3 libpango-1.0-0 \
    libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data
COPY prompts ./prompts
COPY remotion/package.json remotion/package-lock.json ./remotion/

RUN pip install --no-cache-dir -e .
RUN cd remotion && npm ci && npx remotion browser ensure

COPY remotion/src ./remotion/src
COPY remotion/render.mjs remotion/tsconfig.json ./remotion/

ENV KOEBINAR_DATA_DIR=/data/storage \
    KOEBINAR_ARTIFACTS_DIR=/data/artifacts \
    KOEBINAR_DB_PATH=/data/storage/koebinar.db \
    KOEBINAR_REMOTION_BROWSER_EXECUTABLE=/app/remotion/node_modules/.remotion/chrome-headless-shell/linux64/chrome-headless-shell-linux64/chrome-headless-shell \
    KOEBINAR_SYNC_PIPELINE=false

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "koebinar.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
