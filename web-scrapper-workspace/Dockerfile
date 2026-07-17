# # --- STAGE 1: The Builder ---
# FROM python:3.12-slim AS builder

# COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# ENV UV_COMPILE_BYTECODE=1 \
#     UV_LINK_MODE=copy \
#     UV_PYTHON_DOWNLOADS=never

# WORKDIR /app

# # Workspace manifests
# COPY pyproject.toml uv.lock* ./
# COPY libs/shared/pyproject.toml libs/shared/
# COPY libs/database/pyproject.toml libs/database/
# COPY libs/crawler-core/pyproject.toml libs/crawler-core/
# COPY libs/scrapper-core/pyproject.toml libs/scrapper-core/
# COPY apps/api/pyproject.toml apps/api/
# COPY apps/worker/pyproject.toml apps/worker/
# COPY apps/cli/pyproject.toml apps/cli/

# # Install external dependencies only
# RUN --mount=type=cache,target=/root/.cache/uv \
#     uv sync --frozen --no-dev --no-install-workspace --package api --package worker --package cli

# # Copy source for all workspace members required by api + worker
# COPY libs/shared/src libs/shared/src
# COPY libs/database/src libs/database/src
# COPY libs/database/alembic libs/database/alembic
# COPY libs/database/alembic.ini libs/database/alembic.ini
# COPY libs/crawler-core/src libs/crawler-core/src
# COPY libs/scrapper-core/src libs/scrapper-core/src
# COPY apps/api/src apps/api/src
# COPY apps/worker/src apps/worker/src
# COPY apps/cli/src apps/cli/src
# COPY scripts scripts

# # Install workspace packages (non-editable so runtime image only needs .venv)
# RUN --mount=type=cache,target=/root/.cache/uv \
#     uv sync --frozen --no-dev --no-editable --package api --package worker --package cli


# # --- STAGE 2: The Clean Runtime ---
# FROM python:3.12-slim

# WORKDIR /app

# # 1. Copy everything from builder
# COPY --from=builder /app/.venv /app/.venv
# COPY --from=builder /app/libs/database/src /app/libs/database/src
# COPY --from=builder /app/libs/database/alembic /app/libs/database/alembic
# COPY --from=builder /app/libs/database/alembic.ini /app/libs/database/alembic.ini
# COPY --from=builder /app/scripts /app/scripts

# # 2. Set Environment Variables
# ENV PATH="/app/.venv/bin:$PATH" \
#     PLAYWRIGHT_BROWSERS_PATH="/app/.playwright-browsers"

# # 3. Install OS deps, Chromium binaries, and clean up (All as root)
# RUN apt-get update && \
#     apt-get install -y --no-install-recommends ca-certificates && \
#     # First: Install the OS system library dependencies for chromium
#     playwright install-deps chromium && \
#     # Second: Download the actual chromium browser binaries
#     playwright install chromium && \
#     # Third: Clean up apt metadata lists to keep the image small
#     rm -rf /var/lib/apt/lists/*

# # 4. Create user, directories, and fix permissions globally
# RUN groupadd --system appgroup \
#     && useradd --system --gid appgroup --create-home --home-dir /home/appuser --shell /usr/sbin/nologin appuser \
#     && mkdir -p /app/data/crawls /app/data/scrapes /app/.playwright-browsers \
#     && chmod +x /app/scripts/*.sh \
#     # Fix ALL permissions globally so appuser owns the code and the downloaded browsers
#     && chown -R appuser:appgroup /app /home/appuser

# # 5. Drop down to the unprivileged user permanently
# USER appuser

# EXPOSE 8000

# syntax=docker/dockerfile:1


# --- STAGE 1: The Builder ---
# (Still uses uv to build the workspace logic out-of-band)
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Build with monorepo root as context:
#   docker build -f web-scrapper-workspace/Dockerfile <repo-root>
COPY shared-libs/platform-common /shared-libs/platform-common
COPY web-scrapper-workspace/pyproject.toml web-scrapper-workspace/uv.lock* ./
COPY web-scrapper-workspace/libs/shared/pyproject.toml libs/shared/
COPY web-scrapper-workspace/libs/database/pyproject.toml libs/database/
COPY web-scrapper-workspace/libs/crawler-core/pyproject.toml libs/crawler-core/
COPY web-scrapper-workspace/libs/scrapper-core/pyproject.toml libs/scrapper-core/
COPY web-scrapper-workspace/apps/api/pyproject.toml apps/api/
COPY web-scrapper-workspace/apps/worker/pyproject.toml apps/worker/
COPY web-scrapper-workspace/apps/cli/pyproject.toml apps/cli/

# Cache layer 1: Install external dependencies only
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-workspace --package api --package worker --package cli

# Copy updated local source code for all workspace members
COPY web-scrapper-workspace/libs/shared/src libs/shared/src
COPY web-scrapper-workspace/libs/database/src libs/database/src
COPY web-scrapper-workspace/libs/database/alembic libs/database/alembic
COPY web-scrapper-workspace/libs/database/alembic.ini libs/database/alembic.ini
COPY web-scrapper-workspace/libs/crawler-core/src libs/crawler-core/src
COPY web-scrapper-workspace/libs/scrapper-core/src libs/scrapper-core/src
COPY web-scrapper-workspace/apps/api/src apps/api/src
COPY web-scrapper-workspace/apps/worker/src apps/worker/src
COPY web-scrapper-workspace/apps/cli/src apps/cli/src
COPY web-scrapper-workspace/scripts scripts

# Cache layer 2: Re-sync workspace local changes into the .venv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-editable --package api --package worker --package cli \
    && .venv/bin/pip install --no-cache-dir /shared-libs/platform-common


# --- STAGE 2: Pre-Baked Base Environment ---
# Pull your existing environment that already contains apt-get packages and chromium
FROM tharun0511/web-scrapper-wokspace:latest AS production-base


# --- STAGE 3: Final Fast Assembly ---
FROM python:3.12-slim

WORKDIR /app

# 1. Copy the heavy pre-baked system folders directly out of your old image
COPY --from=production-base /usr/lib /usr/lib
COPY --from=production-base /usr/share /usr/share
COPY --from=production-base /lib /lib
COPY --from=production-base /app/.playwright-browsers /app/.playwright-browsers

# 2. Copy your newly compiled code and dependency wheels from the fresh builder stage
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/libs/database/src /app/libs/database/src
COPY --from=builder /app/libs/database/alembic /app/libs/database/alembic
COPY --from=builder /app/libs/database/alembic.ini /app/libs/database/alembic.ini
COPY --from=builder /app/scripts /app/scripts

# 3. Environment matching configuration
ENV PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH="/app/.playwright-browsers"

# 4. Standard secure user configuration (Runs 100% locally from disk cache)
RUN groupadd --system appgroup || true \
    && useradd --system --gid appgroup --create-home --home-dir /home/appuser --shell /usr/sbin/nologin appuser || true \
    && mkdir -p /app/data/crawls /app/data/scrapes \
    && chmod +x /app/scripts/*.sh \
    && chown -R appuser:appgroup /app /home/appuser

USER appuser
EXPOSE 8000