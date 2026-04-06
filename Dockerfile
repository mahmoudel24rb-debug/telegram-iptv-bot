FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libavcodec-extra \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY python-bot/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY python-bot/ .

RUN mkdir -p /var/log/bingebear

EXPOSE 8080

CMD ["python", "run_all.py"]
