FROM python:3.12-alpine

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    MASTOSKY_DATA_DIR=/data

COPY app.py index.html manifest.json ./
COPY brand/ ./brand/
COPY vendor/ ./vendor/

RUN mkdir -p /data

VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/version', timeout=3)" || exit 1

CMD ["sh", "-c", "if [ -f /data/app_update/app.py ]; then cp -rf /data/app_update/. /app/; fi && exec python3 app.py --lan --port 8000"]

