// database.js - Client API Xtream Codes IPTV
const axios = require('axios');

class IPTVApiClient {
    constructor() {
        this.channels = [];
        this.xtreamConfig = {
            url: process.env.IPTV_SERVER_URL,
            username: process.env.IPTV_USERNAME,
            password: process.env.IPTV_PASSWORD
        };
    }

    /**
     * Initialiser - tester la connexion à l'API Xtream
     */
    async init() {
        try {
            console.log('🔄 Connexion à l\'API IPTV...');

            // Tester l'authentification
            const authUrl = `${this.xtreamConfig.url}/player_api.php?username=${this.xtreamConfig.username}&password=${this.xtreamConfig.password}`;
            const response = await axios.get(authUrl, { timeout: 15000 });

            if (response.data && response.data.user_info) {
                console.log('✅ API IPTV connectée');
                console.log(`👤 Utilisateur: ${response.data.user_info.username}`);
                console.log(`📅 Expiration: ${new Date(response.data.user_info.exp_date * 1000).toLocaleDateString()}`);
            } else {
                throw new Error('Réponse API invalide');
            }

        } catch (error) {
            console.error('❌ Erreur connexion API IPTV:', error.message);
            throw error;
        }
    }

    /**
     * Obtenir les catégories Live
     */
    async getLiveCategories() {
        try {
            const url = `${this.xtreamConfig.url}/player_api.php?username=${this.xtreamConfig.username}&password=${this.xtreamConfig.password}&action=get_live_categories`;
            const response = await axios.get(url, { timeout: 15000 });
            return response.data || [];
        } catch (error) {
            console.error('❌ Erreur chargement catégories:', error.message);
            return [];
        }
    }

    /**
     * Obtenir toutes les chaînes actives
     */
    async getChannels() {
        try {
            const url = `${this.xtreamConfig.url}/player_api.php?username=${this.xtreamConfig.username}&password=${this.xtreamConfig.password}&action=get_live_streams`;
            const response = await axios.get(url, { timeout: 30000 });

            if (!response.data || !Array.isArray(response.data)) {
                return [];
            }

            // Convertir au format attendu
            this.channels = response.data.map(ch => ({
                id: ch.stream_id,
                name: ch.name,
                stream_url: `${this.xtreamConfig.url}/live/${this.xtreamConfig.username}/${this.xtreamConfig.password}/${ch.stream_id}.m3u8`,
                type: 'live',
                category: ch.category_id,
                icon_url: ch.stream_icon
            }));

            console.log(`✅ ${this.channels.length} chaînes chargées`);
            return this.channels;

        } catch (error) {
            console.error('❌ Erreur récupération chaînes:', error.message);
            return [];
        }
    }

    /**
     * Obtenir une chaîne par ID (comparaison stricte avec fallback String)
     */
    async getChannelById(id) {
        // Si les chaînes ne sont pas encore chargées, les charger
        if (this.channels.length === 0) {
            await this.getChannels();
        }

        return this.channels.find(ch => ch.id === id || String(ch.id) === String(id)) || null;
    }

    /**
     * Obtenir les films VOD
     */
    async getVODMovies() {
        try {
            const url = `${this.xtreamConfig.url}/player_api.php?username=${this.xtreamConfig.username}&password=${this.xtreamConfig.password}&action=get_vod_streams`;
            const response = await axios.get(url, { timeout: 30000 });

            if (!response.data || !Array.isArray(response.data)) {
                return [];
            }

            return response.data.map(movie => ({
                id: movie.stream_id,
                name: movie.name,
                stream_url: `${this.xtreamConfig.url}/movie/${this.xtreamConfig.username}/${this.xtreamConfig.password}/${movie.stream_id}.${movie.container_extension || 'mp4'}`,
                type: 'vod',
                category: movie.category_id,
                icon_url: movie.stream_icon
            }));

        } catch (error) {
            console.error('❌ Erreur récupération films:', error.message);
            return [];
        }
    }

    /**
     * Obtenir le contenu programmé (retourne la première chaîne disponible)
     */
    async getScheduledContent() {
        // Charger les chaînes si pas encore fait
        if (this.channels.length === 0) {
            await this.getChannels();
        }

        if (this.channels.length === 0) {
            return null;
        }

        // Retourner la première chaîne
        const channel = this.channels[0];
        return {
            id: channel.id,
            name: channel.name,
            url: channel.stream_url,
            type: 'live',
            isLoop: true
        };
    }
}

// Rétro-compatibilité : exporter aussi sous l'ancien nom
module.exports = { IPTVApiClient, DatabaseManager: IPTVApiClient };
