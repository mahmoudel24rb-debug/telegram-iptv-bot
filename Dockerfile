FROM python:3.11-slim

# Installer FFmpeg et dépendances système
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libavcodec-extra \
    && rm -rf /var/lib/apt/lists/*

# Définir le répertoire de travail
WORKDIR /app

# Copier les requirements et installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY . .

# Lancer le bot
CMD ["python", "bot.py"]
