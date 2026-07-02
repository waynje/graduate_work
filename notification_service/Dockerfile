FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY notification_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY notification_service /app/notification_service
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

EXPOSE 8010

CMD ["uvicorn", "notification_service.app:app", "--host", "0.0.0.0", "--port", "8010"]
