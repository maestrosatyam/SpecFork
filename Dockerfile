# syntax=docker/dockerfile:1
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /srv
COPY pyproject.toml README.md LICENSE ./
COPY specfork/ ./specfork/
RUN pip install --no-cache-dir ".[server]"
COPY --from=web /web/dist ./web/dist
RUN useradd --create-home --uid 10001 specfork
USER specfork
ENV SPECFORK_DB=/home/specfork/specfork.db
EXPOSE 8080
# exec form: the server is PID 1 and non-dumpable, no shell keeps the API key in its environment
CMD ["uvicorn", "specfork.server.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-server-header", "--app-dir", "/srv"]
