// streamer.js - Gestion du streaming FFmpeg vers Telegram
const ffmpeg = require('fluent-ffmpeg');
const { spawn } = require('child_process');
const axios = require('axios');

class StreamManager {
    constructor(bot) {
        this.bot = bot;
        this.currentStream = null;
        this.ffmpegProcess = null;
        this.isStreaming = false;
        this.currentContent = null;
        this.startTime = null;
    }

    /**
     * Démarrer un stream
     */
    async startStream(content) {
        try {
            // Guard : empêcher les lancements multiples simultanés
            if (this.isStreaming) {
                console.warn('[STREAM] Déjà en cours, commande ignorée');
                return false;
            }

            console.log('🎬 Démarrage stream:', content.name);

            // Verrouiller AVANT l'appel async pour éviter la race condition
            this.isStreaming = true;
            this.currentContent = content;
            this.startTime = new Date().toISOString();

            // Stream via FFmpeg vers fichier temporaire puis upload
            await this.streamToTelegram(content);

            console.log('✅ Stream démarré avec succès');
            return true;

        } catch (error) {
            console.error('❌ Erreur démarrage stream:', error);
            // Reset en cas d'erreur
            this.isStreaming = false;
            this.currentContent = null;
            this.startTime = null;
            return false;
        }
    }

    /**
     * Stream vers Telegram via segments vidéo
     * Retourne une Promise qui se résout quand FFmpeg a bien démarré (ou rejette après timeout)
     */
    async streamToTelegram(content) {
        const fs = require('fs');
        const path = require('path');
        const streamUrl = this.buildStreamUrl(content);

        console.log('📡 URL Stream:', streamUrl);

        // Fichier de log dédié pour stderr de FFmpeg
        const logDir = './output';
        if (!fs.existsSync(logDir)) {
            fs.mkdirSync(logDir, { recursive: true });
        }
        const ffmpegLogPath = path.join(logDir, 'ffmpeg_stderr.log');
        const ffmpegLogStream = fs.createWriteStream(ffmpegLogPath, { flags: 'a' });
        ffmpegLogStream.write(`\n=== Nouveau stream: ${content.name} — ${new Date().toISOString()} ===\n`);

        // Créer un processus FFmpeg pour capturer le stream et le découper en segments
        this.ffmpegProcess = spawn('ffmpeg', [
            '-i', streamUrl,
            '-c:v', 'libx264',           // Codec vidéo H264
            '-preset', 'ultrafast',       // Preset rapide
            '-b:v', '2500k',              // Bitrate vidéo
            '-maxrate', '2500k',
            '-bufsize', '5000k',
            '-c:a', 'aac',                // Codec audio AAC
            '-b:a', '128k',               // Bitrate audio
            '-ar', '44100',               // Sample rate
            '-ac', '2',                   // Canaux audio stéréo
            '-f', 'segment',              // Format segment
            '-segment_time', '300',       // Segments de 5 minutes
            '-segment_format', 'mp4',     // Format MP4
            '-reset_timestamps', '1',
            '-strftime', '1',
            `./output/stream_%Y%m%d_%H%M%S.mp4`
        ]);

        // Attendre que FFmpeg démarre effectivement (ou timeout après 10s)
        await new Promise((resolve, reject) => {
            let started = false;
            const startTimeout = setTimeout(() => {
                if (!started) {
                    reject(new Error('FFmpeg n\'a pas démarré dans les 10 secondes'));
                }
            }, 10000);

            this.ffmpegProcess.stderr.on('data', (data) => {
                const message = data.toString();
                // Logger TOUTES les sorties stderr dans le fichier dédié
                ffmpegLogStream.write(message);

                // Détecter le démarrage effectif de FFmpeg
                if (!started && (message.includes('Output #0') || message.includes('time='))) {
                    started = true;
                    clearTimeout(startTimeout);
                    console.log('[FFMPEG] Processus démarré avec succès');
                    resolve();
                }

                // Afficher uniquement les messages importants en console
                if (!message.includes('time=') && !message.includes('speed=')) {
                    console.log(`FFmpeg: ${message.trim()}`);
                }
            });

            this.ffmpegProcess.stdout.on('data', (data) => {
                console.log(`FFmpeg stdout: ${data}`);
            });

            this.ffmpegProcess.on('error', (error) => {
                console.error('❌ Erreur FFmpeg:', error);
                ffmpegLogStream.write(`ERREUR: ${error.message}\n`);
                clearTimeout(startTimeout);
                if (!started) {
                    reject(error);
                }
                this.isStreaming = false;
                this._cleanupWatcher();
            });

            this.ffmpegProcess.on('close', (code) => {
                console.log(`FFmpeg terminé avec code ${code}`);
                ffmpegLogStream.write(`=== Terminé avec code ${code} — ${new Date().toISOString()} ===\n`);
                ffmpegLogStream.end();
                clearTimeout(startTimeout);
                if (!started) {
                    reject(new Error(`FFmpeg s'est terminé prématurément avec code ${code}`));
                }
                this.isStreaming = false;
                this._cleanupWatcher();
            });
        });

        // Surveiller les nouveaux segments et les envoyer
        this.watchSegments();

        // Watchdog : si aucun nouveau segment pendant 10 min (2× segment_time), redémarrer
        this._startWatchdog(content);
    }

    /**
     * Watchdog : redémarre FFmpeg si aucun nouveau segment n'est produit pendant 10 min
     */
    _startWatchdog(content) {
        this.lastSegmentTime = Date.now();

        if (this.watchdogInterval) {
            clearInterval(this.watchdogInterval);
        }

        this.watchdogInterval = setInterval(async () => {
            if (!this.isStreaming) {
                clearInterval(this.watchdogInterval);
                this.watchdogInterval = null;
                return;
            }

            const elapsed = Date.now() - this.lastSegmentTime;
            const watchdogTimeout = 10 * 60 * 1000; // 10 minutes

            if (elapsed > watchdogTimeout) {
                console.warn(`[WATCHDOG] Aucun segment depuis ${Math.round(elapsed / 60000)} min, redémarrage FFmpeg...`);
                try {
                    await this.stopStream();
                    await this.startStream(content);
                } catch (err) {
                    console.error('[WATCHDOG] Erreur lors du redémarrage:', err);
                }
            }
        }, 60000); // Vérifier toutes les 60 secondes
    }

    /**
     * Nettoyer le watcher de segments et le watchdog
     */
    _cleanupWatcher() {
        if (this.segmentWatcher) {
            clearInterval(this.segmentWatcher);
            this.segmentWatcher = null;
        }
        if (this.watchdogInterval) {
            clearInterval(this.watchdogInterval);
            this.watchdogInterval = null;
        }
    }

    /**
     * Surveiller et envoyer les segments vidéo
     * Utilise fs.promises pour éviter les exceptions synchrones non gérées
     */
    watchSegments() {
        const fs = require('fs');
        const fsPromises = fs.promises;
        const path = require('path');
        const outputDir = './output';

        // Créer le dossier output si n'existe pas
        if (!fs.existsSync(outputDir)) {
            fs.mkdirSync(outputDir, { recursive: true });
        }

        // Nettoyer un éventuel watcher précédent (évite les fuites)
        if (this.segmentWatcher) {
            clearInterval(this.segmentWatcher);
            this.segmentWatcher = null;
        }

        let sentFiles = new Set();

        // Surveiller les nouveaux fichiers toutes les 10 secondes
        this.segmentWatcher = setInterval(async () => {
            try {
                // Utiliser fs.promises au lieu de fs.readdirSync (non-bloquant, erreurs catchées)
                let files;
                try {
                    files = await fsPromises.readdir(outputDir);
                } catch (readErr) {
                    console.error('[WATCHER] Dossier output inaccessible:', readErr.message);
                    return;
                }

                files = files.filter(f => f.endsWith('.mp4')).sort();

                for (const file of files) {
                    const filePath = path.join(outputDir, file);

                    // Vérifier si le fichier n'a pas déjà été envoyé
                    if (sentFiles.has(file)) continue;

                    // Vérifier que le fichier existe et récupérer sa taille (async, race-condition safe)
                    let stats;
                    try {
                        stats = await fsPromises.stat(filePath);
                    } catch (statErr) {
                        // Fichier supprimé entre readdir et stat — ignorer
                        console.warn(`[WATCHER] Fichier disparu: ${file}`);
                        continue;
                    }

                    // Attendre que le fichier soit complètement écrit (taille stable)
                    const isStable = await this.waitForFileStable(filePath);
                    if (!isStable) {
                        console.warn(`[WATCHER] Fichier instable ou disparu, ignoré: ${file}`);
                        continue;
                    }

                    // Mettre à jour le watchdog
                    if (this.lastSegmentTime !== undefined) {
                        this.lastSegmentTime = Date.now();
                    }

                    // Envoyer le segment sur Telegram
                    const sizeMB = (stats.size / 1024 / 1024).toFixed(2);
                    console.log(`📤 Envoi segment: ${file} (${sizeMB} MB)`);

                    const contentName = this.currentContent?.name ?? 'Stream';
                    await this.bot.sendVideoToChannel(
                        filePath,
                        `🎬 *${contentName}*\n\n` +
                        `Segment: ${file}\n` +
                        `Taille: ${sizeMB} MB`
                    );

                    sentFiles.add(file);

                    // Supprimer le fichier après envoi pour économiser l'espace
                    setTimeout(async () => {
                        try {
                            await fsPromises.unlink(filePath);
                            console.log(`🗑️ Segment supprimé: ${file}`);
                        } catch (e) {
                            console.log(`⚠️ Impossible de supprimer ${file}, sera supprimé plus tard`);
                        }
                    }, 5000);
                }
            } catch (error) {
                console.error('❌ Erreur surveillance segments:', error);
            }
        }, 10000); // Vérifier toutes les 10 secondes
    }

    /**
     * Attendre que la taille du fichier soit stable
     * Retourne false si le fichier est instable ou inaccessible
     */
    async waitForFileStable(filePath, timeout = 30000) {
        const fsPromises = require('fs').promises;
        const startTime = Date.now();
        let lastSize = 0;

        while (Date.now() - startTime < timeout) {
            try {
                const stats = await fsPromises.stat(filePath);
                const currentSize = stats.size;

                if (currentSize === lastSize && currentSize > 0) {
                    // Taille stable, fichier complet
                    return true;
                }

                lastSize = currentSize;
            } catch {
                // Fichier supprimé ou inaccessible pendant la vérification
                return false;
            }
            await new Promise(resolve => setTimeout(resolve, 2000));
        }

        // Timeout = fichier pas stable
        return false;
    }

    /**
     * Construire l'URL du stream
     */
    buildStreamUrl(content) {
        if (content.url) {
            return content.url;
        }

        // Construire l'URL Xtream Codes si nécessaire
        const baseURL = process.env.IPTV_SERVER_URL;
        const username = process.env.IPTV_USERNAME;
        const password = process.env.IPTV_PASSWORD;

        if (content.type === 'live') {
            return `${baseURL}/live/${username}/${password}/${content.id}.ts`;
        } else if (content.type === 'movie') {
            return `${baseURL}/movie/${username}/${password}/${content.id}.${content.extension || 'mkv'}`;
        } else if (content.type === 'series') {
            return `${baseURL}/series/${username}/${password}/${content.id}.${content.extension || 'mkv'}`;
        }

        throw new Error('Type de contenu non supporté');
    }

    /**
     * Arrêter le stream
     */
    async stopStream() {
        try {
            console.log('🛑 Arrêt du stream...');

            // Nettoyer les watchers (segments + watchdog)
            this._cleanupWatcher();

            // Arrêter le processus FFmpeg avec fallback SIGKILL
            if (this.ffmpegProcess && !this.ffmpegProcess.killed) {
                const proc = this.ffmpegProcess;
                this.ffmpegProcess = null;

                proc.kill('SIGINT'); // Arrêt propre

                // Si SIGINT est ignoré après 5s, forcer avec SIGKILL
                const forceKill = setTimeout(() => {
                    if (!proc.killed) {
                        console.warn('[FFMPEG] SIGINT ignoré, envoi SIGKILL');
                        proc.kill('SIGKILL');
                    }
                }, 5000);

                proc.on('exit', () => clearTimeout(forceKill));
            }

            this.isStreaming = false;
            this.currentContent = null;
            this.startTime = null;

            console.log('✅ Stream arrêté');
            return true;

        } catch (error) {
            console.error('❌ Erreur arrêt stream:', error);
            return false;
        }
    }

    /**
     * Obtenir le statut du stream
     */
    async getStatus() {
        return {
            isStreaming: this.isStreaming,
            currentContent: this.currentContent,
            startTime: this.startTime,
            duration: this.calculateDuration()
        };
    }

    /**
     * Calculer la durée du stream
     */
    calculateDuration() {
        if (!this.startTime) return null;

        const start = new Date(this.startTime);
        const now = new Date();
        const diff = now - start;

        const hours = Math.floor(diff / 3600000);
        const minutes = Math.floor((diff % 3600000) / 60000);
        const seconds = Math.floor((diff % 60000) / 1000);

        return `${hours}h ${minutes}m ${seconds}s`;
    }
}

module.exports = { StreamManager };
