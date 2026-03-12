#!/bin/bash
# =============================================================
# BingeBear TV — Installation du monitoring
# A executer APRES setup-vps.sh et le deploiement du bot
# Usage: sudo bash setup-monitoring.sh
# =============================================================

set -euo pipefail

GREEN='\033[0;32m'
NC='\033[0m'
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }

DEPLOY_DIR="/home/bingebear/TelegramIPTVBot/deploy"
BOT_DIR="/home/bingebear/TelegramIPTVBot"

# Verification
if [ "$EUID" -ne 0 ]; then
    echo "Ce script doit etre execute en tant que root"
    exit 1
fi

if [ ! -d "$DEPLOY_DIR" ]; then
    echo "Dossier $DEPLOY_DIR introuvable. Deployer le bot d'abord."
    exit 1
fi

# =============================================================
# 1. Installer le script de monitoring
# =============================================================
log_info "Installation du script de monitoring..."
cp "${DEPLOY_DIR}/monitor.sh" /home/bingebear/monitor.sh
chmod +x /home/bingebear/monitor.sh
chown bingebear:bingebear /home/bingebear/monitor.sh

# =============================================================
# 2. Configurer le cron (monitoring toutes les 5 minutes)
# =============================================================
log_info "Configuration du cron..."

# Creer le crontab pour bingebear
CRON_CONTENT="# BingeBear TV - Monitoring et maintenance
# Monitoring toutes les 5 minutes
*/5 * * * * /home/bingebear/monitor.sh

# Nettoyage des fichiers temporaires (tous les jours a 3h)
0 3 * * * find ${BOT_DIR}/output/ -name '*.mp4' -mmin +60 -delete 2>/dev/null
0 3 * * * find ${BOT_DIR}/python-bot/ -name '*.jpg' -mmin +60 -delete 2>/dev/null
0 3 * * * find ${BOT_DIR}/python-bot/ -name '*.png' -mmin +60 -delete 2>/dev/null
"

echo "$CRON_CONTENT" | crontab -u bingebear -
log_info "Cron configure pour l'utilisateur bingebear"

# =============================================================
# 3. Installer logrotate
# =============================================================
log_info "Configuration de logrotate..."
cp "${DEPLOY_DIR}/logrotate-bingebear" /etc/logrotate.d/bingebear
chmod 644 /etc/logrotate.d/bingebear
log_info "Logrotate configure (rotation quotidienne, 14 jours de retention)"

# =============================================================
# 4. Verification
# =============================================================
log_info "Verification..."

echo ""
log_info "Crontab bingebear :"
crontab -u bingebear -l

echo ""
log_info "Logrotate :"
cat /etc/logrotate.d/bingebear

echo ""
log_info "Monitoring installe avec succes !"
log_info "Le script monitor.sh va :"
log_info "  - Verifier le service systemd toutes les 5 min"
log_info "  - Verifier le health check HTTP"
log_info "  - Envoyer une alerte Telegram si le bot est down"
log_info "  - Tenter un redemarrage automatique"
log_info "  - Nettoyer les fichiers temporaires chaque nuit"
