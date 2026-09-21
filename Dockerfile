FROM node:22-alpine AS web-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WAKETRACE_DB_PATH=/data/waketrace.db \
    WAKETRACE_WEB_DIST_PATH=/app/web/dist/client
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
COPY --from=web-build /build/web/dist/client ./web/dist/client
RUN useradd --create-home --uid 10001 waketrace \
    && mkdir -p /data \
    && chown -R waketrace:waketrace /app /data
USER waketrace
EXPOSE 8765
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=2)"
CMD ["waketrace", "start", "--host", "0.0.0.0", "--port", "8765"]
