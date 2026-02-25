# Use Python 3.12 slim base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install uv for dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY sage-api/pyproject.toml ./
COPY sage-api/uv.lock* ./

# Copy application code
COPY sage-api/sage_api/ sage_api/
COPY sage-api/agents/ agents/

# Install core dependencies that don't require private index
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    redis \
    sse-starlette \
    pydantic \
    pydantic-settings \
    watchfiles \
    structlog \
    httpx \
    aiofiles \
    aiosqlite \
    python-dotenv \
    markdownify

# Note: sage package installation is skipped due to private dependencies
# In production, either:
# 1. Provide Azure DevOps credentials during build
# 2. Use a multi-stage build with pre-installed dependencies
# 3. Use a private base image with sage pre-installed

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check using Python
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live', timeout=5)" || exit 1

# Start uvicorn server
CMD ["uvicorn", "sage_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
