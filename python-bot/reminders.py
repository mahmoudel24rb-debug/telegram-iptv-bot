"""
BingeBear TV - Gestionnaire de rappels recurrents
Persistance JSON + fonctions de gestion
"""

import os
import json
import time
import uuid
import re

REMINDERS_FILE = os.getenv("REMINDERS_FILE", "./reminders.json")


def load_reminders() -> dict:
    """Charger les rappels depuis le fichier JSON"""
    try:
        with open(REMINDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_reminders(reminders: dict) -> None:
    """Sauvegarder les rappels dans le fichier JSON"""
    with open(REMINDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(reminders, f, ensure_ascii=False, indent=2)


def add_reminder(message: str, interval_seconds: int) -> str:
    """Ajouter un rappel recurrent, retourne l'ID"""
    reminders = load_reminders()
    rid = str(uuid.uuid4())[:8]
    reminders[rid] = {
        "message": message,
        "interval": interval_seconds,
        "last_sent": 0,
        "created_at": time.time()
    }
    save_reminders(reminders)
    return rid


def delete_reminder(reminder_id: str) -> bool:
    """Supprimer un rappel, retourne True si trouve"""
    reminders = load_reminders()
    if reminder_id in reminders:
        del reminders[reminder_id]
        save_reminders(reminders)
        return True
    return False


def get_due_reminders() -> list:
    """Retourner les rappels dont l'intervalle est ecoule"""
    reminders = load_reminders()
    now = time.time()
    due = []
    for rid, data in reminders.items():
        if now - data["last_sent"] >= data["interval"]:
            due.append((rid, data))
    return due


def mark_sent(reminder_id: str) -> None:
    """Marquer un rappel comme envoye (met a jour last_sent)"""
    reminders = load_reminders()
    if reminder_id in reminders:
        reminders[reminder_id]["last_sent"] = time.time()
        save_reminders(reminders)


def parse_interval(text: str):
    """Parser un intervalle (30m, 12h, 36h, 2d) en secondes"""
    match = re.match(r'^(\d+)([mhd])$', text.lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    multipliers = {'m': 60, 'h': 3600, 'd': 86400}
    return value * multipliers[unit]


def format_interval(seconds: int) -> str:
    """Formater un intervalle en texte lisible"""
    if seconds >= 86400 and seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds // 60}m"
