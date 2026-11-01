# Canonry demo CMS — a separate publisher service (Render free tier).
# Build from the repository root:
#   docker build -f cms/Dockerfile -t canonry-cms .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY cms/requirements.txt /app/cms/requirements.txt
RUN pip install --no-cache-dir -r /app/cms/requirements.txt

COPY cms /app/cms
RUN mkdir -p /app/db

WORKDIR /app/cms
EXPOSE 8100
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8100}"]
