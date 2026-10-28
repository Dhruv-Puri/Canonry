# Canonry engine — FastAPI on $PORT (default 8000).
#
# Build from the repository root so the engine and its seed CSVs are both copied:
#   docker build -f engine/Dockerfile -t canonry-engine .
#   docker run -p 8000:8000 -v canonry-data:/app/db canonry-engine
#
# The volume keeps db/canonry.db AND the Ed25519 seed together — mount it (or
# attach a host disk) if signed approvals must survive a restart.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY engine/requirements.txt /app/engine/requirements.txt
RUN pip install --no-cache-dir -r /app/engine/requirements.txt

COPY engine /app/engine
COPY data /app/data

# Generated at first boot; the seed data lives outside the image in /app/data.
ENV CANONRY_DB_PATH=/app/db/canonry.db \
    CANONRY_SIGNING_KEY=/app/db/signing_seed.bin
RUN mkdir -p /app/db

WORKDIR /app/engine
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
