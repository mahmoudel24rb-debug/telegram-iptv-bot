FROM python:3.11-slim

# Installer FFmpeg et curl (requis par pytgcalls et health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libavcodec-extra \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Définir le répertoire de travail
WORKDIR /app

# Copier les requirements et installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY . .

# Creer le dossier de logs
RUN mkdir -p /var/log/bingebear

# Port pour le health check HTTP
EXPOSE 8080

# Lancer le bot combine (streaming + news forwarder)
CMD ["python", "run_all.py"]
