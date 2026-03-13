# ---------- Base Image ----------

# Use official Python image
FROM python:3.12-alpine AS base

# Prevent Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv==0.10.9


# ---------- Dependencies Stage ----------

# Use base image
FROM base AS deps

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment
RUN uv sync --no-dev


# ---------- Runtime Stage ----------

# Use base image
FROM base

# Copy installed packages from dependencies stage
COPY --from=deps /app/.venv .venv

# Add virtualenv to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code
COPY app.py sensebox_service.py ./

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
