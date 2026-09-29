FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

RUN apt-get update && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md* ./
COPY app ./app
COPY tests ./tests
COPY scripts ./scripts
RUN pip install --no-cache-dir .

# `data` исключён .dockerignore, а лог Xvfb пишем именно туда: при запуске без
# тома (docker run --rm poldoma-xvfb) каталога в образе может не быть, и без
# mkdir редирект упал бы, не дав Xvfb стартовать вовсе.
RUN mkdir -p /app/data

# Виртуальный дисплей: headed-Chromium (обязателен для pravocaptcha) рисуется в
# Xvfb :99. DISPLAY задаём на уровне образа, а не только внутри shell CMD, иначе
# `docker compose exec app python scripts/kad_smoke.py` падает с
# "Missing X server or $DISPLAY" (приходилось дописывать -e DISPLAY=:99).
ENV DISPLAY=:99

# NB: xvfb-run зависает в контейнере (сигнальный протокол USR1), поэтому Xvfb
# запускаем вручную.
# - Вывод Xvfb уводим в файл ./data/xvfb.log: xkbcomp в Ubuntu 24.04 ругается на
#   keysym'ы из xkb-data (`Could not resolve keysym XF86CameraAccess*`, ...),
#   которых нет в таблице X-сервера. Шум безвредный («Errors from xkbcomp are
#   not fatal to the X server»), но он засорял `docker compose logs`; в файле
#   остаются и реальные ошибки Xvfb. `>` (не `>>`): файл на томе ./data
#   переживает пересоздание контейнера, поэтому пишем лог текущего запуска.
# - -noreset: без сброса X-сервера при выходе последнего клиента (Chromium)
#   раскладка не компилируется заново на каждом пересоздании сессии.
#
# Ровно один воркер (--workers 1) — обязательное условие: APScheduler и
# asyncio.Lock мониторинга живут в процессе, несколько воркеров = несколько
# планировщиков = дубли писем (запись в notifications идёт после отправки,
# окно гонки есть). Масштабировать контейнер app по репликам нельзя.
# Ручной smoke-тест КАД: docker compose exec app python scripts/kad_smoke.py
CMD ["sh", "-c", "Xvfb :99 -screen 0 1600x900x24 -nolisten tcp -noreset >/app/data/xvfb.log 2>&1 & sleep 2; exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
