#!/bin/bash
# =============================================================
# BingeBear TV — Script de monitoring
# Verifie que le bot tourne et envoie une alerte Telegram si down
# Usage: Ajouter au cron toutes les 5 minutes
# =============================================================

SERVICE="bingebear-bot"
HEALTH_URL="http://localhost:8080/health"

# Charger les variables depuis le .env du bot
ENV_FILE="/home/bingebear/TelegramIPTVBot/python-bot/.env"
if [ -f "$ENV_FILE" ]; then
    BOT_TOKEN=$(grep -E "^BOT_TOKEN=" "$ENV_FILE" | cut -d'=' -f2-)
    ADMIN_CHAT_ID=$(grep -E "^ADMIN_IDS=" "$ENV_FILE" | cut -d'=' -f2- | cut -d',' -f1)
fi

# Fallback si les variables ne sont pas trouvees
BOT_TOKEN="${BOT_TOKEN:-}"
ADMIN_CHAT_ID="${ADMIN_CHAT_ID:-}"

LOG_FILE="/var/log/bingebear/monitor.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Fonction d'envoi d'alerte Telegram
send_alert() {
    local msg="$1"
    if [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_CHAT_ID" ]; then
        curl -s -X POST \
            "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d chat_id="${ADMIN_CHAT_ID}" \
            -d text="${msg}" > /dev/null 2>&1
    fi
    echo "[$TIMESTAMP] ALERTE: $msg" >> "$LOG_FILE"
}

# Verification 1 : Le service systemd tourne-t-il ?
if ! systemctl is-active --quiet "$SERVICE"; then
    send_alert "⚠️ [DOWN] BingeBear Bot est arrete sur $(hostname) a $(date '+%H:%M %d/%m'). Tentative de redemarrage..."

    # Tenter un redemarrage
    systemctl restart "$SERVICE"
    sleep 5

    if systemctl is-active --quiet "$SERVICE"; then
        send_alert "✅ [RECOVERED] BingeBear Bot redemarre avec succes"
    else
        send_alert "❌ [CRITICAL] Echec du redemarrage de BingeBear Bot !"
    fi
    exit 1
fi

# Verification 2 : Le health check HTTP repond-il ?
HTTP_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")

if [ "$HTTP_STATUS" != "200" ]; then
    send_alert "⚠️ [HEALTH] Health check echoue (HTTP $HTTP_STATUS) sur $(hostname). Le service tourne mais ne repond pas."

    # Redemarrer si le health check echoue
    systemctl restart "$SERVICE"
    sleep 5

    NEW_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")
    if [ "$NEW_STATUS" = "200" ]; then
        send_alert "✅ [RECOVERED] Health check OK apres redemarrage"
    fi
    exit 1
fi

# Tout va bien — log silencieux
echo "[$TIMESTAMP] OK - service actif, health check 200" >> "$LOG_FILE"
