# sip_receiver/Dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt

# Copy the SIP Receiver package
COPY sip_receiver /app/sip_receiver

# Expose FastAPI (TCP), SIP (UDP), and RTP (UDP range)
EXPOSE 5065/tcp
EXPOSE 5060/udp
EXPOSE 11000-12000/udp

# IMPORTANT: keep a single Uvicorn worker so the SIP UDP port (5060) binds cleanly
CMD ["sh", "-c", "uvicorn sip_receiver.receiver:app --host 0.0.0.0 --port ${SERVICE_PORT:-5065} --workers 1"]
