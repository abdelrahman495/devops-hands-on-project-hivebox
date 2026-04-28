# ---------------------------------------------------------------------------
# Base Image
# ---------------------------------------------------------------------------

# Use official Python image
FROM python:3.14-alpine@sha256:01f125438100bb6b5770c0b1349e5200b23ca0ae20a976b5bd8628457af607ae AS base

# Prevent Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app


# ---------------------------------------------------------------------------
# Dependencies Stage
# ---------------------------------------------------------------------------

# Use base image
FROM base AS deps

# Install uv v0.10.9
COPY --from=ghcr.io/astral-sh/uv@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment
RUN uv sync --no-dev --locked --no-cache


# ---------------------------------------------------------------------------
# Runtime Stage
# ---------------------------------------------------------------------------

# Use base image
FROM base

# Add virtualenv to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Add non-root system user
RUN addgroup -g 1000 -S appgroup && \
    adduser -G appgroup -S -H -u 1000 appuser

# Copy installed packages from dependencies stage
COPY --chmod=755 --chown=root:root --from=deps /app/.venv .venv

# Copy application code
COPY --chmod=755 --chown=root:root src/ src/

# Set non-root user
USER appuser

# Check container health
HEALTHCHECK --timeout=5s --start-period=10s \
  CMD wget -qO- http://127.0.0.1:8000/ || exit 1

# Expose API port
EXPOSE 8000

# Specify default executable
ENTRYPOINT ["uvicorn", "src.app:app"]

# Provide default arguments
CMD ["--host", "0.0.0.0", "--port", "8000"]
