# 🤖 Bot Telegram IPTV Streaming 24/7

Bot Telegram qui diffuse du contenu IPTV en continu dans un canal Telegram, contrôlé via un plugin WordPress.

## 🎯 Fonctionnalités

✅ Streaming IPTV 24/7 vers canal Telegram
✅ Gestion depuis WordPress (import M3U, sélection chaînes)
✅ Support Live TV, Films, Séries
✅ Découpage automatique en segments vidéo
✅ Logs détaillés des streams
✅ Programmation horaire du contenu
✅ Interface d'administration complète

---

## 📦 Installation

### 1. Prérequis

- Node.js 18+ installé
- FFmpeg installé ([Télécharger](https://ffmpeg.org/download.html))
- Accès à WordPress + MySQL
- Bot Telegram créé ([BotFather](https://t.me/BotFather))
- Canal Telegram créé

### 2. Installation du Bot

```cmd
cd C:\Users\mahmo\Downloads\TelegramIPTVBot
npm install
```

### 3. Configuration

Copier `.env.example` vers `.env` et remplir :

```env
# Bot Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=@your_channel

# Base de données (même que WordPress)
DB_HOST=localhost
DB_USER=u800901920_username
DB_PASSWORD=votre_mot_de_passe
DB_NAME=u800901920_Bingebeartv

# IPTV (optionnel, si vous utilisez Xtream Codes)
IPTV_SERVER_URL=http://exemple.com
IPTV_USERNAME=username
IPTV_PASSWORD=password

# WordPress
WORDPRESS_URL=https://bingebear.tv
```

### 4. Installation du Plugin WordPress

1. Copier le dossier `wordpress-plugin/telegram-iptv-manager` vers :
   ```
   /wp-content/plugins/telegram-iptv-manager/
   ```

2. Activer le plugin dans WordPress Admin → Plugins

3. Accéder à "Telegram IPTV" dans le menu admin

---

## 🚀 Utilisation

### Démarrer le bot

```cmd
cd C:\Users\mahmo\Downloads\TelegramIPTVBot
npm start
```

Ou en mode développement :
```cmd
npm run dev
```

### Créer un bot Telegram

1. Parler à [@BotFather](https://t.me/BotFather)
2. Utiliser `/newbot`
3. Suivre les instructions
4. Copier le token dans `.env`

### Obtenir l'ID du canal

1. Créer un canal Telegram public
2. Ajouter le bot comme admin du canal
3. L'ID sera `@nom_du_canal`

Ou pour un canal privé:
```cmd
# Envoyer un message dans le canal puis utiliser:
curl https://api.telegram.org/bot<TOKEN>/getUpdates
```

---

## 📺 Importer des chaînes depuis M3U

### Méthode 1: Depuis WordPress

1. Aller dans **Telegram IPTV → Chaînes**
2. Cliquer sur "Importer M3U"
3. Coller l'URL ou le contenu du M3U
4. Cliquer "Importer"

### Méthode 2: Via API

```bash
curl -X POST https://bingebear.tv/wp-json/telegram-iptv/v1/import-m3u \
  -H "Content-Type: application/json" \
  -d '{
    "m3u_url": "http://exemple.com/playlist.m3u"
  }'
```

---

## 🎬 Programmer un stream

### Depuis WordPress

1. **Telegram IPTV → Programmation**
2. Cliquer "Nouveau stream"
3. Sélectionner :
   - Chaîne / Film / Série
   - Heure de début (optionnel)
   - Heure de fin (optionnel)
   - Loop (répéter en boucle)
4. Sauvegarder

### Depuis le bot Telegram

```
/channels       - Voir les chaînes disponibles
/play           - Démarrer le stream programmé
/stop           - Arrêter le stream
/status         - Voir le statut
```

---

## 🔧 Commandes du bot

| Commande | Description |
|----------|-------------|
| `/start` | Démarrer le bot |
| `/status` | Statut du stream actuel |
| `/channels` | Liste des chaînes |
| `/play` | Démarrer le streaming |
| `/stop` | Arrêter le streaming |
| `/current` | Voir ce qui est diffusé |
| `/help` | Aide |

---

## 📁 Structure du projet

```
TelegramIPTVBot/
├── src/
│   ├── bot.js           # Bot Telegram principal
│   ├── streamer.js      # Gestion FFmpeg + streaming
│   └── database.js      # Gestion MySQL
├── wordpress-plugin/
│   ├── telegram-iptv-manager.php  # Plugin WordPress
│   ├── views/           # Interfaces admin
│   │   ├── dashboard.php
│   │   ├── channels.php
│   │   ├── schedule.php
│   │   └── logs.php
│   ├── css/
│   └── js/
├── output/              # Segments vidéo temporaires
├── .env                 # Configuration
├── .env.example         # Exemple de configuration
├── package.json
└── README.md
```

---

## ⚙️ Fonctionnement technique

### 1. Flux de streaming

```
IPTV Source → FFmpeg → Segments MP4 → Telegram API → Canal
```

### 2. Processus FFmpeg

- Capture le stream IPTV
- Transcode en H264 + AAC
- Découpe en segments de 5 minutes
- Génère des fichiers MP4

### 3. Upload Telegram

- Surveille les nouveaux segments
- Upload via Telegram Bot API
- Supprime les segments après envoi

---

## 🎥 Formats supportés

### Input (depuis IPTV)
- M3U / M3U8
- HLS (HTTP Live Streaming)
- RTMP
- HTTP/HTTPS direct

### Output (vers Telegram)
- MP4 (H.264 + AAC)
- Résolution : 720p par défaut
- Bitrate : 2500k

---

## 📊 Base de données

### Tables créées

```sql
wp_telegram_iptv_channels   -- Chaînes IPTV
wp_telegram_iptv_schedule   -- Contenu programmé
wp_telegram_iptv_logs       -- Historique des streams
```

---

## 🐛 Troubleshooting

### Le bot ne démarre pas

```cmd
# Vérifier les variables d'environnement
cat .env

# Vérifier la connexion MySQL
node -e "require('./src/database').test()"
```

### Le stream ne fonctionne pas

1. Vérifier que FFmpeg est installé :
   ```cmd
   ffmpeg -version
   ```

2. Tester l'URL du stream manuellement :
   ```cmd
   ffmpeg -i "http://stream-url" -t 10 test.mp4
   ```

3. Vérifier les logs du bot

### Les segments ne s'envoient pas

- Vérifier les permissions du dossier `output/`
- Vérifier la limite de taille Telegram (50 MB max)
- Vérifier que le bot est admin du canal

---

## 🔒 Sécurité

⚠️ **Important:**

- Ne jamais commit le fichier `.env`
- Utiliser des mots de passe forts
- Limiter les permissions du bot WordPress
- Surveiller l'utilisation de la bande passante

---

## 📈 Améliorations futures

- [ ] Support multi-canaux
- [ ] Playlist automatique
- [ ] Détection de panne automatique
- [ ] Qualité adaptive (SD/HD/FHD)
- [ ] Statistiques de visionnage
- [ ] Interface web en temps réel
- [ ] Support Docker

---

## 💡 Exemples d'utilisation

### Stream une chaîne 24/7

```javascript
// Dans WordPress, programmer:
Chaîne: "France 24"
Loop: Oui
Début: Maintenant
Fin: (vide)
```

### Programmer un film pour ce soir

```javascript
Contenu: "Film XYZ"
Type: VOD
Début: 2026-01-18 20:00:00
Fin: 2026-01-18 22:30:00
```

---

## 📞 Support

Pour toute question:
- GitHub Issues
- Email: support@bingebear.tv

---

## 📜 Licence

MIT License - Libre d'utilisation et modification
