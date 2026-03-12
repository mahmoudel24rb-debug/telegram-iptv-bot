#!/bin/bash
# =============================================================
# BingeBear TV — Script d'installation VPS
# A executer en tant que root sur un VPS Ubuntu 25.04 frais
# Usage: sudo bash setup-vps.sh
# =============================================================

set -euo pipefail

# Couleurs pour les logs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Verification root
if [ "$EUID" -ne 0 ]; then
    log_error "Ce script doit etre execute en tant que root (sudo bash setup-vps.sh)"
    exit 1
fi

BOT_USER="bingebear"
BOT_DIR="/home/${BOT_USER}/TelegramIPTVBot"
LOG_DIR="/var/log/bingebear"
SSH_PORT="${SSH_PORT:-2222}"

# =============================================================
# 1. Mise a jour systeme
# =============================================================
log_info "Mise a jour du systeme..."
apt update && apt upgrade -y

# =============================================================
# 2. Creer l'utilisateur dedie
# =============================================================
if id "$BOT_USER" &>/dev/null; then
    log_warn "Utilisateur $BOT_USER existe deja"
else
    log_info "Creation de l'utilisateur $BOT_USER..."
    adduser --disabled-password --gecos "BingeBear TV Bot" "$BOT_USER"
    usermod -aG sudo "$BOT_USER"
    log_info "Utilisateur $BOT_USER cree"
fi

# =============================================================
# 3. Installer les dependances systeme
# =============================================================
log_info "Installation des dependances systeme..."
apt install -y \
    software-properties-common \
    python3.11 python3.11-venv python3.11-dev \
    ffmpeg libavcodec-extra \
    git curl htop ufw

# Verifier les installations
log_info "Python: $(python3.11 --version 2>&1)"
log_info "FFmpeg: $(ffmpeg -version 2>&1 | head -1)"

# =============================================================
# 4. Configurer le firewall
# =============================================================
log_info "Configuration du firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ${SSH_PORT}/tcp comment 'SSH'
ufw allow 8080/tcp comment 'Health check BingeBear'
# Garder le port 22 ouvert aussi pendant la transition
ufw allow 22/tcp comment 'SSH standard'
echo "y" | ufw enable
log_info "Firewall actif (ports ${SSH_PORT}, 8080, 22)"

# =============================================================
# 5. Creer les dossiers
# =============================================================
log_info "Creation des dossiers..."
mkdir -p "$LOG_DIR"
chown "${BOT_USER}:${BOT_USER}" "$LOG_DIR"

# Dossier SSH pour l'utilisateur
sudo -u "$BOT_USER" mkdir -p "/home/${BOT_USER}/.ssh"
chmod 700 "/home/${BOT_USER}/.ssh"

# =============================================================
# 6. Securiser SSH
# =============================================================
log_info "Securisation SSH..."
SSHD_CONFIG="/etc/ssh/sshd_config"

# Backup de la config SSH
cp "$SSHD_CONFIG" "${SSHD_CONFIG}.backup.$(date +%Y%m%d)"

# Modifier le port SSH (si different de 22)
if [ "$SSH_PORT" != "22" ]; then
    sed -i "s/^#*Port .*/Port ${SSH_PORT}/" "$SSHD_CONFIG"
    log_info "Port SSH change vers $SSH_PORT"
fi

# Desactiver le login root (commenté par defaut, a activer manuellement)
# sed -i 's/^#*PermitRootLogin .*/PermitRootLogin no/' "$SSHD_CONFIG"
# sed -i 's/^#*PasswordAuthentication .*/PasswordAuthentication no/' "$SSHD_CONFIG"

log_warn "IMPORTANT: Avant de desactiver le login root/password :"
log_warn "  1. Copiez votre cle SSH : ssh-copy-id -p ${SSH_PORT} ${BOT_USER}@$(hostname -f)"
log_warn "  2. Testez la connexion par cle"
log_warn "  3. Puis decommentez les lignes dans $SSHD_CONFIG"
log_warn "  4. Et redemarrez sshd : systemctl restart sshd"

# =============================================================
# 7. Preparer le deploiement du bot
# =============================================================
log_info "Preparation du deploiement..."
cat << 'INSTRUCTIONS'

=============================================================
  INSTALLATION TERMINEE !
=============================================================

Prochaines etapes (en tant que l'utilisateur bingebear) :

  su - bingebear

  # 1. Cloner le depot
  git clone https://github.com/VOTRE_USER/TelegramIPTVBot.git
  cd TelegramIPTVBot/python-bot

  # 2. Creer le virtualenv
  python3.11 -m venv venv
  source venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt

  # 3. Configurer l'environnement
  nano .env    # Remplir toutes les variables
  chmod 600 .env

  # 4. Test manuel
  python run_all.py
  # Verifier que le bot repond, puis Ctrl+C

  # 5. Installer le service systemd
  sudo cp ~/TelegramIPTVBot/deploy/bingebear-bot.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable bingebear-bot
  sudo systemctl start bingebear-bot
  sudo systemctl status bingebear-bot

=============================================================
INSTRUCTIONS
