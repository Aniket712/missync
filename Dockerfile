FROM node:26-bookworm-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/missync backend/missync
# The built UI is packaged inside the installed package (missync/_static), so it is found after a non-editable install.
COPY --from=web /web/dist backend/missync/_static
RUN pip install --no-cache-dir "./backend[postgres,bigquery,snowflake,files]"
RUN useradd -m missync && mkdir /data && chown missync /data
USER missync
ENV MISSYNC_DATA_DIR=/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=4).status == 200 else 1)"
# Defaults to the locked-down public-demo mode; set MISSYNC_MODE=self-hosted (with MISSYNC_API_TOKEN) to connect your own databases.
CMD ["missync", "serve", "--host", "0.0.0.0", "--port", "8000"]
