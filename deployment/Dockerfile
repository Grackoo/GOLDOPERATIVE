# ==============================================================================
# AUREUS-SMC Institutional Trading Engine
# Production Dockerfile for Ubuntu 22.04 / 24.04 (Equinix NY4 VPS)
# ==============================================================================

FROM python:3.11-slim-bullseye AS base

# Prevent Python from writing .pyc files & enable unbuffered standard I/O
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies (build-essential, curl, tzdata)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set canonical New York timezone
ENV TZ=America/New_York
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure storage directory exists with proper permissions
RUN mkdir -p /app/storage && chmod 777 /app/storage

# Create non-root dedicated trading user
RUN useradd -m -u 1000 trader && chown -R trader:trader /app
USER trader

# Expose web dashboard port
EXPOSE 8000

# Healthcheck for FastAPI WebSockets
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/status || exit 1

# Launch production engine
CMD ["python", "scripts/run_live.py"]
