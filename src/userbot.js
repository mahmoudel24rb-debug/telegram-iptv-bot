// userbot.js - Client utilisateur Telegram pour le live streaming
require('dotenv').config();
const { TelegramClient } = require('telegram');
const { StringSession } = require('telegram/sessions');
const input = require('input');
const fs = require('fs');
const path = require('path');

const apiId = parseInt(process.env.TELEGRAM_API_ID);
const apiHash = process.env.TELEGRAM_API_HASH;

// Fichier pour sauvegarder la session
const SESSION_FILE = path.join(__dirname, '..', 'session.txt');

class TelegramUserBot {
    constructor() {
        this.client = null;
        this.stringSession = new StringSession(this.loadSession());
    }

    /**
     * Charger la session sauvegardée
     */
    loadSession() {
        try {
            if (fs.existsSync(SESSION_FILE)) {
                const session = fs.readFileSync(SESSION_FILE, 'utf8').trim();
                console.log('📱 Session existante chargée');
                return session;
            }
        } catch (error) {
            console.log('⚠️ Pas de session sauvegardée');
        }
        return '';
    }

    /**
     * Sauvegarder la session
     */
    saveSession() {
        try {
            fs.writeFileSync(SESSION_FILE, this.client.session.save());
            console.log('💾 Session sauvegardée');
        } catch (error) {
            console.error('❌ Erreur sauvegarde session:', error);
        }
    }

    /**
     * Se connecter au compte Telegram
     */
    async connect() {
        console.log('🔄 Connexion à Telegram...');

        this.client = new TelegramClient(
            this.stringSession,
            apiId,
            apiHash,
            { connectionRetries: 5 }
        );

        await this.client.start({
            phoneNumber: async () => await input.text('📱 Numéro de téléphone (format: +33612345678): '),
            password: async () => await input.text('🔐 Mot de passe 2FA (si activé, sinon appuie Entrée): '),
            phoneCode: async () => await input.text('📨 Code reçu par SMS/Telegram: '),
            onError: (err) => console.error('❌ Erreur:', err),
        });

        console.log('✅ Connecté à Telegram!');

        // Sauvegarder la session pour ne pas avoir à se reconnecter
        this.saveSession();

        // Afficher les infos du compte
        const me = await this.client.getMe();
        console.log(`👤 Connecté en tant que: ${me.firstName} ${me.lastName || ''} (@${me.username || 'N/A'})`);

        return this.client;
    }

    /**
     * Obtenir le client
     */
    getClient() {
        return this.client;
    }

    /**
     * Déconnecter
     */
    async disconnect() {
        if (this.client) {
            await this.client.disconnect();
            console.log('👋 Déconnecté de Telegram');
        }
    }
}

// Si exécuté directement, lancer la connexion pour créer la session
if (require.main === module) {
    (async () => {
        console.log('🔐 Configuration du compte Telegram pour le live streaming\n');

        const userbot = new TelegramUserBot();
        await userbot.connect();

        console.log('\n✅ Configuration terminée!');
        console.log('La session est sauvegardée dans session.txt');
        console.log('Tu peux maintenant utiliser le bot pour le live streaming.\n');

        await userbot.disconnect();
        process.exit(0);
    })();
}

module.exports = { TelegramUserBot };
