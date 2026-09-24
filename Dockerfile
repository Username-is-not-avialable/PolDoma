FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

RUN apt-get update && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md* ./
COPY app ./app
COPY tests ./tests
COPY scripts ./scripts
RUN pip install --no-cache-dir .

# NB: xvfb-run зависает в контейнере (сигнальный протокол USR1), поэтому Xvfb
# запускаем вручную. Окно Chromium рисуется в виртуальный дисплей :99.
CMD ["sh", "-c", "Xvfb :99 -screen 0 1600x900x24 -nolisten tcp & sleep 2; export DISPLAY=:99; exec python -u scripts/kad_smoke.py"]
