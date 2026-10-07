FROM node:22-bookworm-slim AS web
WORKDIR /build
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" AGENTCOMMONS_DB=/data/agentcommons.db AGENTCOMMONS_WEB_DIR=/app/web/dist
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable && groupadd --gid 10001 commons && useradd --uid 10001 --gid commons commons && mkdir /data && chown commons:commons /data
COPY --from=web /build/dist/ web/dist/
USER commons
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["agentcommons", "serve", "--host", "0.0.0.0"]
