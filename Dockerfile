FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY .env .env
COPY server server

CMD gunicorn --bind 0.0.0.0:8000 server.app:app