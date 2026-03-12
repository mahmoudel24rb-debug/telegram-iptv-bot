// live-streamer.js - Live streaming vers Telegram Video Chat
require('dotenv').config();
const { TelegramClient, Api } = require('telegram');
const { StringSession } = require('telegram/sessions');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const SESSION_FILE = path.join(__dirname, '..', 'session.txt');

class LiveStreamer {
    constructor() {
        this.client = null;
        this.ffmpegProcess = null;
        this.isStreaming = false;
        this.currentContent = null;
    }

    /**
     * Charger la session
     */
    loadSession() {
        try {
            if (fs.existsSync(SESSION_FILE)) {
                return fs.readFileSync(SESSION_FILE, 'utf8').trim();
            }
        } catch (error) {
            console.error('❌ Erreur chargement session:', error);
        }
        return '';
    }

    /**
     * Se connecter à Telegram
     */
    async connect() {
        const sessionString = this.loadSession();

        if (!sessionString) {
            throw new Error('Session non trouvée. Lancez d\'abord: node src/userbot.js');
        }

        this.client = new TelegramClient(
            new StringSession(sessionString),
            parseInt(process.env.TELEGRAM_API_ID),
            process.env.TELEGRAM_API_HASH,
            { connectionRetries: 5 }
        );

        await this.client.connect();
        console.log('✅ Connecté à Telegram');

        const me = await this.client.getMe();
        console.log(`👤 Compte: ${me.firstName} (@${me.username})`);

        return this.client;
    }

    /**
     * Rejoindre un video chat de groupe
     */
    async joinGroupCall(groupUsername) {
        try {
            console.log(`🔄 Recherche du groupe: ${groupUsername}`);

            // Résoudre le groupe
            const result = await this.client.invoke(
                new Api.contacts.ResolveUsername({ username: groupUsername.replace('@', '') })
            );

            if (!result.chats || result.chats.length === 0) {
                throw new Error('Groupe non trouvé');
            }

            const chat = result.chats[0];
            console.log(`✅ Groupe trouvé: ${chat.title}`);

            // Vérifier s'il y a un appel en cours
            const fullChat = await this.client.invoke(
                new Api.channels.GetFullChannel({
                    channel: chat
                })
            );

            if (fullChat.fullChat.call) {
                console.log('📞 Video chat actif trouvé');
                return { chat, call: fullChat.fullChat.call };
            } else {
                console.log('⚠️ Aucun video chat actif. Création...');

                // Créer un nouveau video chat
                const newCall = await this.client.invoke(
                    new Api.phone.CreateGroupCall({
                        peer: chat,
                        randomId: Math.floor(Math.random() * 1000000),
                        title: 'BingeBear TV Live'
                    })
                );

                console.log('✅ Video chat créé');
                return { chat, call: newCall };
            }

        } catch (error) {
            console.error('❌ Erreur joinGroupCall:', error);
            throw error;
        }
    }

    /**
     * Démarrer le streaming RTMP vers Telegram
     * Note: Telegram utilise WebRTC, pas RTMP directement
     * On doit utiliser une approche différente
     */
    async startStream(content, groupUsername) {
        try {
            console.log('🎬 Démarrage du live stream...');
            console.log(`📺 Contenu: ${content.name}`);
            console.log(`📡 URL: ${content.url}`);

            this.currentContent = content;
            this.isStreaming = true;

            // Pour le live streaming Telegram, on a besoin de tgcalls
            // Malheureusement, la librairie Node.js pour ça n'est pas stable
            // Alternative: utiliser pytgcalls (Python) ou gram-tgcalls

            console.log('\n⚠️ LIMITATION TECHNIQUE:');
            console.log('Le live streaming Telegram nécessite WebRTC/tgcalls');
            console.log('qui n\'est pas disponible de manière stable en Node.js.\n');
            console.log('ALTERNATIVES RECOMMANDÉES:');
            console.log('1. Utiliser un bot Python avec pytgcalls');
            console.log('2. Utiliser le mode "segments vidéo" (ce qu\'on avait avant)');
            console.log('3. Restreamer vers YouTube Live\n');

            return false;

        } catch (error) {
            console.error('❌ Erreur startStream:', error);
            this.isStreaming = false;
            return false;
        }
    }

    /**
     * Arrêter le stream
     */
    async stopStream() {
        this.isStreaming = false;
        this.currentContent = null;

        if (this.ffmpegProcess) {
            this.ffmpegProcess.kill('SIGINT');
            this.ffmpegProcess = null;
        }

        console.log('⏹️ Stream arrêté');
        return true;
    }

    /**
     * Déconnecter
     */
    async disconnect() {
        if (this.client) {
            await this.client.disconnect();
        }
    }
}

// Test
if (require.main === module) {
    (async () => {
        const streamer = new LiveStreamer();

        try {
            await streamer.connect();

            // Teste avec ton groupe
            const groupUsername = process.argv[2] || 'bingebeartv';

            console.log(`\n🔍 Test avec le groupe: @${groupUsername}\n`);

            const { chat, call } = await streamer.joinGroupCall(groupUsername);

            console.log('\n📋 Informations:');
            console.log(`Groupe: ${chat.title}`);
            console.log(`ID: ${chat.id}`);

        } catch (error) {
            console.error('❌ Erreur:', error.message);
        }

        await streamer.disconnect();
    })();
}

module.exports = { LiveStreamer };
