"""
BingeBear TV - Validation de la configuration
Vérifie toutes les variables d'environnement requises au démarrage
"""

import os
import sys
from logger import setup_logger

logger = setup_logger('bingebear.config')

# Variables obligatoires — le bot ne peut pas démarrer sans elles
REQUIRED_VARS = [
    'API_ID',
    'API_HASH',
    'BOT_TOKEN',
    'CHAT_ID',
]

# Variables recommandees — le bot demarre sans elles mais avec des fonctions limitees
RECOMMENDED_VARS = [
    'SESSION_STRING',
    'IPTV_SERVER_URL',
    'IPTV_USERNAME',
    'IPTV_PASSWORD',
    'ANTHROPIC_API_KEY',
]

# Variables optionnelles avec valeurs par défaut
OPTIONAL_VARS = {
    'ADMIN_IDS': '',
    'ALLOWED_USERNAMES': 'DefiMack',
    'NEWS_SOURCE_CHANNEL': '-1001763758614',
    'NEWS_DEST_CHANNEL': '@bingebeartv_live',
    'LOG_DIR': os.path.join(os.path.dirname(__file__), 'logs'),
}


def validate_config():
    """Vérifie toutes les variables requises au démarrage. Quitte si une manque."""
    missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
    if missing:
        logger.critical(f"Variables d'environnement manquantes : {', '.join(missing)}")
        logger.critical("Verifiez votre fichier .env ou vos variables systeme.")
        sys.exit(1)
    logger.info("Configuration validee — toutes les variables requises sont presentes")

    # Avertir pour les variables recommandees manquantes
    missing_rec = [var for var in RECOMMENDED_VARS if not os.getenv(var)]
    if missing_rec:
        logger.warning(f"Variables recommandees manquantes : {', '.join(missing_rec)}")
        logger.warning("Certaines fonctions (streaming, IPTV) seront desactivees.")


def get_config(key, default=None):
    """Récupère une variable avec valeur par défaut optionnelle."""
    return os.getenv(key, OPTIONAL_VARS.get(key, default))
