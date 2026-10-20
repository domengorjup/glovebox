# HA add-on build. The Supervisor uses this folder as the build context, so the
# application source is fetched from the repository instead of copied.
# Standalone users should build the Dockerfile at the repository root instead.
FROM python:3.12-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
ARG SOURCE_REPO=https://github.com/domengorjup/autotracker_app.git
ARG SOURCE_REF=main
RUN git clone --depth 1 --branch "${SOURCE_REF}" "${SOURCE_REPO}" /app
WORKDIR /app
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AUTOTRACKER_MODE=addon
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/docker/entrypoint.sh /usr/local/bin/autotracker-entrypoint
# Root: Supervisor mounts /data root-owned.
ENTRYPOINT ["autotracker-entrypoint"]
