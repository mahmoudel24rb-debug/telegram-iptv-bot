"""
BingeBear TV - Logging structuré
Fournit un logger avec sortie console + fichier avec rotation
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(name='bingebear'):
    """Configurer et retourner un logger avec console + fichier rotatif."""
    logger = logging.getLogger(name)

    # Éviter d'ajouter des handlers en double si appelé plusieurs fois
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Format console : lisible, niveau + nom + message
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    # Format fichier : plus détaillé avec nom de fichier et numéro de ligne
    log_dir = os.getenv('LOG_DIR', os.path.join(os.path.dirname(__file__), 'logs'))
    os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, f'{name}.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
