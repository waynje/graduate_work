FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY shortlink_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shortlink_service /app/shortlink_service

EXPOSE 8020

CMD ["uvicorn", "shortlink_service.app:app", "--host", "0.0.0.0", "--port", "8020"]
