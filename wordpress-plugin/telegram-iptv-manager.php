<?php
/**
 * Plugin Name: Telegram IPTV Manager
 * Description: Gestion du bot Telegram IPTV 24/7 - Contrôle des chaînes et du contenu diffusé
 * Version: 1.0.0
 * Author: BingeBear
 */

if (!defined('ABSPATH')) {
    exit;
}

class TelegramIPTVManager {
    private $table_channels;
    private $table_schedule;
    private $table_logs;

    public function __construct() {
        global $wpdb;

        $this->table_channels = $wpdb->prefix . 'telegram_iptv_channels';
        $this->table_schedule = $wpdb->prefix . 'telegram_iptv_schedule';
        $this->table_logs = $wpdb->prefix . 'telegram_iptv_logs';

        // Hooks
        add_action('admin_menu', array($this, 'add_admin_menu'));
        add_action('admin_enqueue_scripts', array($this, 'enqueue_admin_scripts'));
        add_action('rest_api_init', array($this, 'register_rest_routes'));

        // Activation hook
        register_activation_hook(__FILE__, array($this, 'activate'));
    }

    /**
     * Activation du plugin
     */
    public function activate() {
        global $wpdb;

        $charset_collate = $wpdb->get_charset_collate();

        // Table des chaînes
        $sql1 = "CREATE TABLE IF NOT EXISTS {$this->table_channels} (
            id mediumint(9) NOT NULL AUTO_INCREMENT,
            name varchar(255) NOT NULL,
            stream_url text NOT NULL,
            type varchar(50) DEFAULT 'live',
            category varchar(100) DEFAULT 'general',
            icon_url text,
            is_active tinyint(1) DEFAULT 1,
            created_at datetime DEFAULT CURRENT_TIMESTAMP,
            updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY  (id)
        ) $charset_collate;";

        // Table de programmation
        $sql2 = "CREATE TABLE IF NOT EXISTS {$this->table_schedule} (
            id mediumint(9) NOT NULL AUTO_INCREMENT,
            content_id mediumint(9) NOT NULL,
            content_type varchar(50) NOT NULL,
            content_name varchar(255) NOT NULL,
            content_url text NOT NULL,
            start_time datetime NULL,
            end_time datetime NULL,
            is_active tinyint(1) DEFAULT 1,
            is_loop tinyint(1) DEFAULT 0,
            created_at datetime DEFAULT CURRENT_TIMESTAMP,
            updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY  (id)
        ) $charset_collate;";

        // Table des logs
        $sql3 = "CREATE TABLE IF NOT EXISTS {$this->table_logs} (
            id mediumint(9) NOT NULL AUTO_INCREMENT,
            content_id mediumint(9) NOT NULL,
            content_name varchar(255) NOT NULL,
            content_type varchar(50) NOT NULL,
            start_time datetime NOT NULL,
            end_time datetime NULL,
            duration_seconds int DEFAULT 0,
            status varchar(50) DEFAULT 'running',
            error_message text NULL,
            created_at datetime DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY  (id)
        ) $charset_collate;";

        require_once(ABSPATH . 'wp-admin/includes/upgrade.php');
        dbDelta($sql1);
        dbDelta($sql2);
        dbDelta($sql3);
    }

    /**
     * Ajouter le menu admin
     */
    public function add_admin_menu() {
        add_menu_page(
            'Telegram IPTV Bot',
            'Telegram IPTV',
            'manage_options',
            'telegram-iptv',
            array($this, 'admin_page'),
            'dashicons-video-alt3',
            30
        );

        add_submenu_page(
            'telegram-iptv',
            'Chaînes',
            'Chaînes',
            'manage_options',
            'telegram-iptv-channels',
            array($this, 'channels_page')
        );

        add_submenu_page(
            'telegram-iptv',
            'Programmation',
            'Programmation',
            'manage_options',
            'telegram-iptv-schedule',
            array($this, 'schedule_page')
        );

        add_submenu_page(
            'telegram-iptv',
            'Logs',
            'Logs',
            'manage_options',
            'telegram-iptv-logs',
            array($this, 'logs_page')
        );
    }

    /**
     * Enqueue admin scripts
     */
    public function enqueue_admin_scripts($hook) {
        if (strpos($hook, 'telegram-iptv') === false) {
            return;
        }

        wp_enqueue_style('telegram-iptv-admin', plugins_url('css/admin.css', __FILE__));
        wp_enqueue_script('telegram-iptv-admin', plugins_url('js/admin.js', __FILE__), array('jquery'), '1.0', true);

        wp_localize_script('telegram-iptv-admin', 'telegramIPTV', array(
            'ajaxurl' => admin_url('admin-ajax.php'),
            'nonce' => wp_create_nonce('telegram_iptv_nonce')
        ));
    }

    /**
     * Register REST routes
     */
    public function register_rest_routes() {
        register_rest_route('telegram-iptv/v1', '/channels', array(
            'methods' => 'GET',
            'callback' => array($this, 'api_get_channels'),
            'permission_callback' => '__return_true'
        ));

        register_rest_route('telegram-iptv/v1', '/schedule', array(
            'methods' => 'GET',
            'callback' => array($this, 'api_get_schedule'),
            'permission_callback' => '__return_true'
        ));

        register_rest_route('telegram-iptv/v1', '/import-m3u', array(
            'methods' => 'POST',
            'callback' => array($this, 'api_import_m3u'),
            'permission_callback' => array($this, 'check_permissions')
        ));
    }

    /**
     * API: Get channels
     */
    public function api_get_channels() {
        global $wpdb;

        $channels = $wpdb->get_results(
            "SELECT * FROM {$this->table_channels} WHERE is_active = 1 ORDER BY name ASC"
        );

        return rest_ensure_response($channels);
    }

    /**
     * API: Get schedule
     */
    public function api_get_schedule() {
        global $wpdb;

        $schedule = $wpdb->get_results(
            "SELECT * FROM {$this->table_schedule}
             WHERE is_active = 1
             AND (start_time IS NULL OR start_time <= NOW())
             AND (end_time IS NULL OR end_time >= NOW())
             ORDER BY created_at DESC
             LIMIT 1"
        );

        return rest_ensure_response($schedule);
    }

    /**
     * API: Import M3U playlist
     */
    public function api_import_m3u($request) {
        $m3u_url = $request->get_param('m3u_url');
        $m3u_content = $request->get_param('m3u_content');

        if (!$m3u_url && !$m3u_content) {
            return new WP_Error('missing_data', 'M3U URL or content required', array('status' => 400));
        }

        // Télécharger le M3U si URL fournie
        if ($m3u_url) {
            $response = wp_remote_get($m3u_url);

            if (is_wp_error($response)) {
                return new WP_Error('download_error', 'Failed to download M3U', array('status' => 500));
            }

            $m3u_content = wp_remote_retrieve_body($response);
        }

        // Parser le M3U
        $channels = $this->parse_m3u($m3u_content);

        if (empty($channels)) {
            return new WP_Error('parse_error', 'No channels found in M3U', array('status' => 400));
        }

        // Importer les chaînes
        global $wpdb;
        $imported = 0;

        foreach ($channels as $channel) {
            $result = $wpdb->insert(
                $this->table_channels,
                array(
                    'name' => $channel['name'],
                    'stream_url' => $channel['url'],
                    'type' => 'live',
                    'category' => $channel['group'] ?? 'general',
                    'icon_url' => $channel['logo'] ?? null
                ),
                array('%s', '%s', '%s', '%s', '%s')
            );

            if ($result) {
                $imported++;
            }
        }

        return rest_ensure_response(array(
            'success' => true,
            'imported' => $imported,
            'total' => count($channels)
        ));
    }

    /**
     * Parser M3U
     */
    private function parse_m3u($content) {
        $channels = array();
        $lines = explode("\n", $content);

        $current_channel = null;

        foreach ($lines as $line) {
            $line = trim($line);

            if (strpos($line, '#EXTINF:') === 0) {
                // Ligne d'info de chaîne
                $current_channel = array();

                // Extraire le nom
                if (preg_match('/,(.+)$/', $line, $matches)) {
                    $current_channel['name'] = trim($matches[1]);
                }

                // Extraire le logo
                if (preg_match('/tvg-logo="([^"]+)"/', $line, $matches)) {
                    $current_channel['logo'] = $matches[1];
                }

                // Extraire le groupe
                if (preg_match('/group-title="([^"]+)"/', $line, $matches)) {
                    $current_channel['group'] = $matches[1];
                }

            } elseif (!empty($line) && strpos($line, '#') !== 0 && $current_channel !== null) {
                // Ligne d'URL
                $current_channel['url'] = $line;
                $channels[] = $current_channel;
                $current_channel = null;
            }
        }

        return $channels;
    }

    /**
     * Check permissions
     */
    public function check_permissions() {
        return current_user_can('manage_options');
    }

    /**
     * Page d'administration principale
     */
    public function admin_page() {
        include plugin_dir_path(__FILE__) . 'views/dashboard.php';
    }

    /**
     * Page des chaînes
     */
    public function channels_page() {
        include plugin_dir_path(__FILE__) . 'views/channels.php';
    }

    /**
     * Page de programmation
     */
    public function schedule_page() {
        include plugin_dir_path(__FILE__) . 'views/schedule.php';
    }

    /**
     * Page des logs
     */
    public function logs_page() {
        include plugin_dir_path(__FILE__) . 'views/logs.php';
    }
}

// Initialiser le plugin
new TelegramIPTVManager();
