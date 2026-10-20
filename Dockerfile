# Autotracker image. Same image for standalone use and (once published) the HA add-on.
# Build from the repository root:  docker build -t autotracker .
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AUTOTRACKER_MODE=standalone \
    DATA_DIR=/data
COPY --from=build /app/.venv /app/.venv
COPY docker/entrypoint.sh /usr/local/bin/autotracker-entrypoint
RUN useradd --uid 1000 --no-create-home autotracker \
    && mkdir /data && chown autotracker /data
# Non-root for standalone. The HA add-on image (addon/autotracker/Dockerfile) runs as root
# because Supervisor mounts /data as root-owned.
USER autotracker
VOLUME /data
EXPOSE 8080
ENTRYPOINT ["autotracker-entrypoint"]
