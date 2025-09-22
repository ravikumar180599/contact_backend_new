# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# OS deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# Install deps
# If your requirements.txt is elsewhere, adjust the COPY path below.
COPY socket/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt

# Copy app code
COPY socket /app

# API port and the WS TCP range (distinct from RTP)
EXPOSE 8002/tcp
EXPOSE 12100-13000/tcp

# Reasonable defaults (override via env at runtime)
ENV WS_HOST=0.0.0.0 \
    WS_PORT_MIN=12100 \
    WS_PORT_MAX=13000

# Start FastAPI app
CMD ["uvicorn", "main:api", "--host", "0.0.0.0", "--port", "8002"]
