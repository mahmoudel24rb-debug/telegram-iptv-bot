// bot.js - Bot Telegram principal
require('dotenv').config();
const { Bot, InlineKeyboard, InputFile } = require('grammy');
const { StreamManager } = require('./streamer');
const { IPTVApiClient } = require('./database');

class TelegramIPTVBot {
    constructor() {
        this.bot = new Bot(process.env.TELEGRAM_BOT_TOKEN);
        this.chatId = process.env.TELEGRAM_CHAT_ID;
        this.db = new IPTVApiClient();
        this.streamer = new StreamManager(this);

        this.currentStream = null;
        this.setupCommands();
        this.setupCallbacks();
    }

    setupCommands() {
        // Commande /start
        this.bot.command('start', async (ctx) => {
            await ctx.reply(
                '🎬 *Bot IPTV Streaming 24/7*\n\n' +
                'Bienvenue! Ce bot diffuse du contenu IPTV en continu.\n\n' +
                'Commandes disponibles:\n' +
                '/status - Voir le statut du stream\n' +
                '/channels - Liste des chaînes disponibles\n' +
                '/play - Démarrer le streaming\n' +
                '/stop - Arrêter le streaming\n' +
                '/current - Voir ce qui est diffusé\n' +
                '/help - Aide',
                { parse_mode: 'Markdown' }
            );
        });

        // Commande /status
        this.bot.command('status', async (ctx) => {
            const status = await this.streamer.getStatus();
            const emoji = status.isStreaming ? '🟢' : '🔴';

            let message = `${emoji} *Statut du Stream*\n\n`;
            message += `État: ${status.isStreaming ? 'En cours' : 'Arrêté'}\n`;

            if (status.isStreaming && status.currentContent) {
                message += `\n📺 *En diffusion:*\n`;
                message += `Nom: ${status.currentContent.name}\n`;
                message += `Type: ${status.currentContent.type}\n`;
                message += `Début: ${status.startTime}\n`;
                message += `Durée: ${status.duration || 'Indéfini'}`;
            }

            await ctx.reply(message, { parse_mode: 'Markdown' });
        });

        // Commande /channels
        this.bot.command('channels', async (ctx) => {
            try {
                const channels = await this.db.getChannels();

                if (channels.length === 0) {
                    await ctx.reply('❌ Aucune chaîne configurée.\n\nAjoutez des chaînes depuis le panneau WordPress.');
                    return;
                }

                // Créer un clavier inline avec les chaînes
                const keyboard = new InlineKeyboard();

                channels.slice(0, 20).forEach((channel, index) => {
                    if (index % 2 === 0) {
                        keyboard.text(`📡 ${channel.name}`, `play_live_${channel.id}`);
                    } else {
                        keyboard.text(`📡 ${channel.name}`, `play_live_${channel.id}`).row();
                    }
                });

                await ctx.reply(
                    '📺 *Chaînes disponibles:*\n\n' +
                    'Sélectionnez une chaîne pour démarrer le streaming:',
                    {
                        parse_mode: 'Markdown',
                        reply_markup: keyboard
                    }
                );
            } catch (error) {
                console.error('Erreur chargement chaînes:', error);
                await ctx.reply('❌ Erreur lors du chargement des chaînes.');
            }
        });

        // Commande /play
        this.bot.command('play', async (ctx) => {
            try {
                // Récupérer le contenu à diffuser depuis WordPress
                const content = await this.db.getScheduledContent();

                if (!content) {
                    await ctx.reply('❌ Aucun contenu programmé.\n\nConfigurez le contenu à diffuser depuis WordPress.');
                    return;
                }

                await ctx.reply('🔄 Démarrage du streaming...');

                const success = await this.streamer.startStream(content);

                if (success) {
                    await ctx.reply(
                        `✅ *Streaming démarré!*\n\n` +
                        `📺 ${content.name}\n` +
                        `Type: ${content.type}\n\n` +
                        `Le stream est maintenant en direct dans le canal.`,
                        { parse_mode: 'Markdown' }
                    );
                } else {
                    await ctx.reply('❌ Erreur lors du démarrage du stream.');
                }
            } catch (error) {
                console.error('Erreur démarrage stream:', error);
                await ctx.reply('❌ Erreur: ' + error.message);
            }
        });

        // Commande /stop
        this.bot.command('stop', async (ctx) => {
            await ctx.reply('🛑 Arrêt du streaming...');

            const success = await this.streamer.stopStream();

            if (success) {
                await ctx.reply('✅ Stream arrêté avec succès.');
            } else {
                await ctx.reply('❌ Erreur lors de l\'arrêt du stream.');
            }
        });

        // Commande /current
        this.bot.command('current', async (ctx) => {
            const status = await this.streamer.getStatus();

            if (!status.isStreaming) {
                await ctx.reply('❌ Aucun stream en cours.');
                return;
            }

            const content = status.currentContent;
            let message = `📺 *En diffusion:*\n\n`;
            message += `Nom: ${content?.name ?? 'N/A'}\n`;
            message += `Type: ${content?.type ?? 'N/A'}\n`;
            message += `URL: ${content?.url?.substring(0, 50) ?? 'N/A'}...\n`;
            message += `Début: ${status.startTime ?? 'N/A'}`;

            await ctx.reply(message, { parse_mode: 'Markdown' });
        });

        // Commande /help
        this.bot.command('help', async (ctx) => {
            await ctx.reply(
                '📖 *Aide - Bot IPTV*\n\n' +
                '*Commandes disponibles:*\n\n' +
                '/start - Démarrer le bot\n' +
                '/status - Voir le statut du stream\n' +
                '/channels - Liste des chaînes\n' +
                '/play - Démarrer le streaming\n' +
                '/stop - Arrêter le streaming\n' +
                '/current - Contenu actuel\n\n' +
                '*Configuration:*\n' +
                'Gérez le contenu à diffuser depuis:\n' +
                'https://bingebear.tv/wp-admin/\n\n' +
                '*Support:*\n' +
                'En cas de problème, contactez l\'administrateur.',
                { parse_mode: 'Markdown' }
            );
        });
    }

    setupCallbacks() {
        // Gérer les callbacks des boutons inline
        this.bot.on('callback_query:data', async (ctx) => {
            const data = ctx.callbackQuery.data;

            if (data.startsWith('play_live_')) {
                const channelId = data.replace('play_live_', '');

                await ctx.answerCallbackQuery('🔄 Démarrage du stream...');

                try {
                    const channel = await this.db.getChannelById(channelId);

                    if (!channel) {
                        await ctx.reply('❌ Chaîne introuvable.');
                        return;
                    }

                    const success = await this.streamer.startStream({
                        id: channel.id,
                        name: channel.name,
                        url: channel.stream_url,
                        type: 'live'
                    });

                    if (success) {
                        await ctx.reply(
                            `✅ *Stream démarré!*\n\n` +
                            `📺 ${channel.name}\n\n` +
                            `Le stream est maintenant en direct.`,
                            { parse_mode: 'Markdown' }
                        );
                    } else {
                        await ctx.reply('❌ Erreur lors du démarrage.');
                    }
                } catch (error) {
                    console.error('Erreur:', error);
                    await ctx.reply('❌ Erreur: ' + error.message);
                }
            }
        });
    }

    /**
     * Envoyer un message dans le canal
     */
    async sendToChannel(message, options = {}) {
        try {
            await this.bot.api.sendMessage(this.chatId, message, options);
        } catch (error) {
            console.error('Erreur envoi message canal:', error);
        }
    }

    /**
     * Envoyer une vidéo dans le canal
     */
    async sendVideoToChannel(videoPath, caption) {
        try {
            // Utiliser InputFile pour uploader le fichier local
            const videoFile = new InputFile(videoPath);
            await this.bot.api.sendVideo(this.chatId, videoFile, {
                caption: caption,
                parse_mode: 'Markdown',
                supports_streaming: true
            });
            console.log('✅ Vidéo envoyée avec succès');
        } catch (error) {
            console.error('❌ Erreur envoi vidéo:', error);
        }
    }

    /**
     * Démarrer le bot
     */
    async start() {
        try {
            console.log('🤖 Démarrage du bot Telegram IPTV...');

            // Initialiser la base de données
            await this.db.init();
            console.log('✅ Base de données connectée');

            // Démarrer le bot
            await this.bot.start();
            console.log('✅ Bot démarré avec succès!');
            console.log(`📢 Canal Telegram: ${this.chatId}`);

            // Message de démarrage dans le canal
            await this.sendToChannel(
                '🤖 *Bot IPTV démarré!*\n\n' +
                'Le bot est maintenant en ligne et prêt à diffuser du contenu.\n\n' +
                'Utilisez /help pour voir les commandes disponibles.',
                { parse_mode: 'Markdown' }
            );

        } catch (error) {
            console.error('❌ Erreur démarrage bot:', error);
            process.exit(1);
        }
    }

    /**
     * Arrêter le bot
     */
    async stop() {
        console.log('🛑 Arrêt du bot...');

        await this.streamer.stopStream();
        await this.bot.stop();

        console.log('✅ Bot arrêté');
    }
}

// Filet de sécurité : capturer les rejections non gérées
process.on('unhandledRejection', (reason, promise) => {
    console.error('[FATAL] Unhandled rejection:', reason);
});

// Démarrer le bot
const bot = new TelegramIPTVBot();
bot.start();

// Gérer l'arrêt propre
process.on('SIGINT', async () => {
    await bot.stop();
    process.exit(0);
});

process.on('SIGTERM', async () => {
    await bot.stop();
    process.exit(0);
});

module.exports = { TelegramIPTVBot };
