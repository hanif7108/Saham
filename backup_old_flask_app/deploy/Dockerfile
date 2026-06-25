# Sharia Trading Assistant — Docker Image
# Build:  docker build -t sharia-ta -f deploy/Dockerfile .
# Run:    docker run -d -p 8000:8000 --name sharia-ta -v $(pwd)/cache:/app/cache -v $(pwd)/logs:/app/logs sharia-ta

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system deps untuk reportlab (Pillow needs libjpeg/zlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    zlib1g \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cache layer)
COPY deploy/requirements.txt /app/
RUN pip install -r /app/requirements.txt

# Copy source
COPY . /app/

# Create non-root user
RUN groupadd -r app && useradd -r -g app app && \
    chown -R app:app /app && \
    mkdir -p /app/cache /app/logs /app/exports && \
    chown -R app:app /app/cache /app/logs /app/exports

USER app

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s \
    CMD curl -f http://localhost:8000/api/cache/stats || exit 1

CMD ["gunicorn", "-c", "deploy/gunicorn_config.py", "app:app"]
