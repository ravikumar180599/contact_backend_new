# llm/Dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LLM_PORT=5070

WORKDIR /app

# Install deps (cached layer)
COPY llm/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt

# Copy app code
COPY llm /app/llm

# Expose API port (default 5070)
EXPOSE 5070/tcp

# Start FastAPI app (port can be overridden via env LLM_PORT)
CMD ["sh", "-c", "uvicorn llm.main:app --host 0.0.0.0 --port ${LLM_PORT:-5070} --workers 1"]
