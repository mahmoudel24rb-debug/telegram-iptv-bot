"""
BingeBear TV - Systeme de campagnes promotionnelles
Gestion des promos avec planification intelligente (intervalle, weekends, jours specifiques)
Persistance JSON + templates pre-configures
"""

import os
import json
import time
import uuid
import re
from datetime import datetime, timedelta

PROMOS_FILE = os.getenv("PROMOS_FILE", os.path.join(os.path.dirname(__file__), "promotions.json"))

# ── Timezone offset (heures) — configurable via .env ──
# BingeBear cible UK/Ireland → UTC+0 en hiver, UTC+1 en ete
# On utilise un offset simple plutot qu'une dep lourde (pytz)
TZ_OFFSET = int(os.getenv("TZ_OFFSET_HOURS", "0"))


def _now_local() -> datetime:
    """Retourne l'heure courante avec l'offset timezone configure."""
    return datetime.utcnow() + timedelta(hours=TZ_OFFSET)


# ── Templates pre-configures ──
# Chaque template est un dict pret a etre utilise avec add_promo()
TEMPLATES = {
    "free_trial": {
        "name": "Free Trial",
        "message": (
            "🎬 Haven't tried BingeBear TV yet?\n\n"
            "Get a FREE 24-hour trial — full access to 20,000+ channels, "
            "movies, and series!\n\n"
            "👉 Contact @DefiMack to start your trial now!\n\n"
            "— Team BingeBearTV"
        ),
        "schedule_type": "interval",
        "interval_seconds": 172800,  # 48h
        "weekdays": [],
        "send_hour": 11,
    },
    "renewal": {
        "name": "Renewal Reminder",
        "message": (
            "🔔 Reminder: Don't let your subscription expire!\n\n"
            "Renew now and keep enjoying:\n"
            "✅ 20,000+ live channels\n"
            "✅ 80,000+ movies & series\n"
            "✅ Premium sports & PPV\n\n"
            "👉 Contact @DefiMack to renew\n\n"
            "— Team BingeBearTV"
        ),
        "schedule_type": "interval",
        "interval_seconds": 259200,  # 3 days
        "weekdays": [],
        "send_hour": 18,
    },
    "weekend_deal": {
        "name": "Weekend Special",
        "message": (
            "🏖️ Weekend vibes + BingeBear TV = perfection!\n\n"
            "Grab our weekend deal:\n"
            "📺 1 month — Only £9.99\n"
            "📺 3 months — Only £19.99\n"
            "📺 12 months — Only £39.99\n\n"
            "👉 DM @DefiMack to order\n\n"
            "— Team BingeBearTV"
        ),
        "schedule_type": "weekdays",
        "interval_seconds": 0,
        "weekdays": [4, 5],  # Friday + Saturday (0=Monday)
        "send_hour": 12,
    },
    "sport_promo": {
        "name": "Sport Package",
        "message": (
            "⚽ Big match this weekend?\n\n"
            "Watch EVERY game live on BingeBear TV!\n"
            "Premier League, Champions League, La Liga, Serie A, "
            "UFC, Boxing — all included.\n\n"
            "🏟️ Start your trial: @DefiMack\n\n"
            "— Team BingeBearTV"
        ),
        "schedule_type": "weekdays",
        "interval_seconds": 0,
        "weekdays": [3, 4],  # Thursday + Friday (before weekend matches)
        "send_hour": 17,
    },
    "new_user": {
        "name": "New User Welcome",
        "message": (
            "👋 New to BingeBear TV?\n\n"
            "Here's what you get:\n"
            "🔹 20,000+ live channels worldwide\n"
            "🔹 80,000+ movies & TV series (VOD)\n"
            "🔹 Works on any device (Firestick, Smart TV, Phone, PC)\n"
            "🔹 24/7 support\n\n"
            "Try it FREE for 24h — no commitment!\n"
            "👉 @DefiMack\n\n"
            "— Team BingeBearTV"
        ),
        "schedule_type": "interval",
        "interval_seconds": 345600,  # 4 days
        "weekdays": [],
        "send_hour": 10,
    },
}


# ── Persistence ──

def load_promos() -> dict:
    """Charger les promotions depuis le fichier JSON."""
    try:
        with open(PROMOS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_promos(promos: dict) -> None:
    """Sauvegarder les promotions dans le fichier JSON."""
    with open(PROMOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(promos, f, ensure_ascii=False, indent=2)


# ── CRUD ──

def add_promo(
    name: str,
    message: str,
    schedule_type: str,
    interval_seconds: int = 0,
    weekdays: list = None,
    send_hour: int = 10,
    created_by: int = 0,
) -> str:
    """
    Creer une nouvelle campagne promo.

    Args:
        name: Nom court de la promo (ex: "Free Trial")
        message: Texte complet du message a envoyer
        schedule_type: "interval" ou "weekdays"
        interval_seconds: Pour type "interval" — delai entre envois (ex: 172800 = 48h)
        weekdays: Pour type "weekdays" — liste de jours (0=Lundi, 6=Dimanche)
        send_hour: Heure d'envoi preferee (0-23, heure locale)
        created_by: Telegram user ID de l'admin qui a cree la promo

    Returns:
        L'ID de la promo cree (8 caracteres)
    """
    promos = load_promos()
    pid = str(uuid.uuid4())[:8]

    promos[pid] = {
        "name": name,
        "message": message,
        "schedule_type": schedule_type,
        "interval_seconds": interval_seconds,
        "weekdays": weekdays or [],
        "send_hour": send_hour,
        "active": True,
        "last_sent": 0,
        "times_sent": 0,
        "created_at": time.time(),
        "created_by": created_by,
    }
    save_promos(promos)
    return pid


def delete_promo(promo_id: str) -> bool:
    """Supprimer une promo. Retourne True si trouvee."""
    promos = load_promos()
    if promo_id in promos:
        del promos[promo_id]
        save_promos(promos)
        return True
    return False


def toggle_promo(promo_id: str) -> str | None:
    """Basculer active/paused. Retourne le nouvel etat ou None si introuvable."""
    promos = load_promos()
    if promo_id not in promos:
        return None
    promos[promo_id]["active"] = not promos[promo_id]["active"]
    save_promos(promos)
    return "active" if promos[promo_id]["active"] else "paused"


def update_promo_message(promo_id: str, new_message: str) -> bool:
    """Modifier le message d'une promo existante."""
    promos = load_promos()
    if promo_id not in promos:
        return False
    promos[promo_id]["message"] = new_message
    save_promos(promos)
    return True


def update_promo_schedule(
    promo_id: str,
    schedule_type: str = None,
    interval_seconds: int = None,
    weekdays: list = None,
    send_hour: int = None,
) -> bool:
    """Modifier la planification d'une promo existante."""
    promos = load_promos()
    if promo_id not in promos:
        return False
    if schedule_type is not None:
        promos[promo_id]["schedule_type"] = schedule_type
    if interval_seconds is not None:
        promos[promo_id]["interval_seconds"] = interval_seconds
    if weekdays is not None:
        promos[promo_id]["weekdays"] = weekdays
    if send_hour is not None:
        promos[promo_id]["send_hour"] = send_hour
    save_promos(promos)
    return True


def get_promo(promo_id: str) -> dict | None:
    """Recuperer une promo par son ID."""
    promos = load_promos()
    return promos.get(promo_id)


# ── Scheduling logic ──

def get_due_promos() -> list:
    """
    Retourner les promos qui doivent etre envoyees maintenant.

    Logique:
    - Type "interval": envoyer si (now - last_sent) >= interval_seconds
      ET si l'heure actuelle est dans la fenetre [send_hour, send_hour+2]
    - Type "weekdays": envoyer si le jour actuel est dans la liste
      ET si l'heure actuelle est dans la fenetre [send_hour, send_hour+1]
      ET si on n'a pas deja envoye aujourd'hui
    """
    promos = load_promos()
    now = _now_local()
    now_ts = time.time()
    current_hour = now.hour
    current_weekday = now.weekday()  # 0=Monday, 6=Sunday
    today_start_ts = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() - (TZ_OFFSET * 3600)

    due = []

    for pid, data in promos.items():
        if not data.get("active", True):
            continue

        send_hour = data.get("send_hour", 10)
        schedule_type = data.get("schedule_type", "interval")

        if schedule_type == "interval":
            interval = data.get("interval_seconds", 0)
            if interval <= 0:
                continue

            # Verifier que l'intervalle est ecoule
            if (now_ts - data.get("last_sent", 0)) < interval:
                continue

            # Fenetre d'envoi: send_hour a send_hour+2 (2h de marge)
            if not (send_hour <= current_hour < send_hour + 2):
                continue

            due.append((pid, data))

        elif schedule_type == "weekdays":
            weekdays = data.get("weekdays", [])
            if not weekdays:
                continue

            # Verifier que c'est le bon jour
            if current_weekday not in weekdays:
                continue

            # Fenetre d'envoi: send_hour a send_hour+1 (1h de marge)
            if not (send_hour <= current_hour < send_hour + 1):
                continue

            # Verifier qu'on n'a pas deja envoye aujourd'hui
            if data.get("last_sent", 0) > today_start_ts:
                continue

            due.append((pid, data))

    return due


def mark_promo_sent(promo_id: str) -> None:
    """Marquer une promo comme envoyee (met a jour last_sent et times_sent)."""
    promos = load_promos()
    if promo_id in promos:
        promos[promo_id]["last_sent"] = time.time()
        promos[promo_id]["times_sent"] = promos[promo_id].get("times_sent", 0) + 1
        save_promos(promos)


# ── Helpers de formatage ──

WEEKDAY_NAMES = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
    4: "Fri", 5: "Sat", 6: "Sun",
}

WEEKDAY_NAMES_FR = {
    0: "Lun", 1: "Mar", 2: "Mer", 3: "Jeu",
    4: "Ven", 5: "Sam", 6: "Dim",
}


def format_schedule(data: dict) -> str:
    """Formater la planification en texte lisible."""
    schedule_type = data.get("schedule_type", "interval")
    send_hour = data.get("send_hour", 10)

    if schedule_type == "interval":
        secs = data.get("interval_seconds", 0)
        if secs >= 86400 and secs % 86400 == 0:
            interval_str = f"Every {secs // 86400}d"
        elif secs >= 3600:
            interval_str = f"Every {secs / 3600:.0f}h"
        else:
            interval_str = f"Every {secs // 60}m"
        return f"{interval_str} (around {send_hour}:00)"

    elif schedule_type == "weekdays":
        days = data.get("weekdays", [])
        day_names = [WEEKDAY_NAMES.get(d, "?") for d in sorted(days)]
        return f"{', '.join(day_names)} at {send_hour}:00"

    return "Unknown"


def format_promo_summary(pid: str, data: dict) -> str:
    """Formater un resume d'une promo pour l'affichage."""
    status = "✅" if data.get("active") else "⏸️"
    name = data.get("name", "Sans nom")
    schedule = format_schedule(data)
    times = data.get("times_sent", 0)
    msg_preview = data.get("message", "")[:60]
    if len(data.get("message", "")) > 60:
        msg_preview += "..."

    return (
        f"{status} {name}\n"
        f"   ID: {pid}\n"
        f"   Schedule: {schedule}\n"
        f"   Sent: {times}x\n"
        f"   Message: {msg_preview}"
    )


def parse_weekdays(text: str) -> list | None:
    """
    Parser une liste de jours.
    Accepte: "weekends", "sat,sun", "mon,wed,fri", "0,2,4", etc.
    Retourne une liste d'entiers (0=Mon, 6=Sun) ou None si invalide.
    """
    text = text.lower().strip()

    # Raccourcis
    if text in ("weekends", "weekend", "we"):
        return [5, 6]  # Saturday + Sunday
    if text in ("weekdays", "workdays", "wd"):
        return [0, 1, 2, 3, 4]  # Mon-Fri
    if text in ("everyday", "daily", "all"):
        return [0, 1, 2, 3, 4, 5, 6]

    name_map = {
        "mon": 0, "monday": 0,
        "tue": 1, "tuesday": 1,
        "wed": 2, "wednesday": 2,
        "thu": 3, "thursday": 3,
        "fri": 4, "friday": 4,
        "sat": 5, "saturday": 5,
        "sun": 6, "sunday": 6,
    }

    parts = [p.strip() for p in text.replace(" ", ",").split(",") if p.strip()]
    days = []
    for part in parts:
        if part in name_map:
            days.append(name_map[part])
        elif part.isdigit() and 0 <= int(part) <= 6:
            days.append(int(part))
        else:
            return None

    return sorted(set(days)) if days else None


def parse_interval(text: str) -> int | None:
    """Parser un intervalle (30m, 12h, 48h, 2d, 1w) en secondes."""
    match = re.match(r'^(\d+)([mhdw])$', text.lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    multipliers = {'m': 60, 'h': 3600, 'd': 86400, 'w': 604800}
    return value * multipliers[unit]
