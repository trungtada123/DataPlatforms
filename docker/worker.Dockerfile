FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend:/app/backend/src:/app/src

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /app/backend
COPY src /app/src

# Financial ingestion worker entrypoint.
CMD ["python", "-m", "ingestion.financial_reports.rabbitmq_consumer"]
