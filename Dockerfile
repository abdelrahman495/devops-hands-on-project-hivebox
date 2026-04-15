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

# Set shell to /bin/ash with pipefail enabled
SHELL ["/bin/ash", "-o", "pipefail", "-c"]

# Install uv
RUN wget -qO /tmp/uv.tar.gz https://releases.astral.sh/github/uv/releases/download/0.10.9/uv-x86_64-unknown-linux-musl.tar.gz && \
    echo "433e56874739e92c7cfd661ba9e5f287b376ca612c08c8194a41a98a13158aea /tmp/uv.tar.gz" | sha256sum -c - && \
    tar -xzf /tmp/uv.tar.gz -C /tmp && \
    mv /tmp/uv-x86_64-unknown-linux-musl/uv /usr/local/bin/ && \
    rm -rf /tmp/uv*


# ---------------------------------------------------------------------------
# Dependencies Stage
# ---------------------------------------------------------------------------

# Use base image
FROM base AS deps

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment
RUN uv sync --no-dev


# ---------------------------------------------------------------------------
# Runtime Stage
# ---------------------------------------------------------------------------

# Use base image
FROM base

# Copy installed packages from dependencies stage
COPY --from=deps /app/.venv .venv

# Add virtualenv to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code
COPY app.py sensebox_service.py temperature_utils.py ./

# Add non-root user
RUN adduser --disabled-password appuser

# Set non-root user
USER appuser

# Expose API port
EXPOSE 8000

# Specify default executable
ENTRYPOINT ["uvicorn", "app:app"]

# Provide default arguments
CMD ["--host", "0.0.0.0", "--port", "8000"]
