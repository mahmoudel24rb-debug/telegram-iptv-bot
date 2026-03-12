#!/bin/bash
# =============================================================
# BingeBear TV — Script de mise a jour du bot
# Usage: bash update-bot.sh
# A executer depuis n'importe ou en tant que bingebear
# =============================================================

set -euo pipefail

BOT_DIR="/home/bingebear/TelegramIPTVBot"
SERVICE="bingebear-bot"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# Aller dans le dossier du bot
cd "$BOT_DIR"

# Sauvegarder la branche actuelle
BRANCH=$(git rev-parse --abbrev-ref HEAD)
CURRENT_COMMIT=$(git rev-parse --short HEAD)
log_info "Branche: $BRANCH (commit: $CURRENT_COMMIT)"

# Pull les dernieres modifications
log_info "Recuperation des mises a jour..."
git pull origin "$BRANCH"

NEW_COMMIT=$(git rev-parse --short HEAD)
if [ "$CURRENT_COMMIT" = "$NEW_COMMIT" ]; then
    log_info "Deja a jour (commit: $CURRENT_COMMIT)"
    exit 0
fi

log_info "Mise a jour: $CURRENT_COMMIT -> $NEW_COMMIT"

# Mettre a jour les dependances Python
cd python-bot
log_info "Mise a jour des dependances Python..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Redemarrer le service
log_info "Redemarrage du service $SERVICE..."
sudo systemctl restart "$SERVICE"

# Attendre 3 secondes et verifier le statut
sleep 3
if systemctl is-active --quiet "$SERVICE"; then
    log_info "Service $SERVICE actif et fonctionnel"
else
    log_warn "ATTENTION: Le service $SERVICE ne semble pas actif !"
    log_warn "Verifiez avec: sudo journalctl -u $SERVICE -n 50"
fi

# Verifier le health check
sleep 2
if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    log_info "Health check OK"
else
    log_warn "Health check pas encore disponible (peut prendre quelques secondes)"
fi

log_info "Mise a jour terminee !"
