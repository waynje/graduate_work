FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src:/app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY ugc_service /app/ugc_service
COPY ugc_etl /app/ugc_etl
COPY tests /app/tests

CMD ["pytest", "-q", "tests/functional", "tests/ugc"]

