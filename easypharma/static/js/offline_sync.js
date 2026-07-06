// Offline Sync Manager for Easy Pharma PWA - Improved Version
// v2.0

const OfflineSync = {
    async init() {
        if (typeof localforage === 'undefined') {
            console.error('[OfflineSync] localforage is not loaded! Offline queuing will not work.');
            return false;
        }

        this.salesStore = localforage.createInstance({ name: 'ep_sales' });
        this.purchaseStore = localforage.createInstance({ name: 'ep_purchases' });
        this.masterStore = localforage.createInstance({ name: 'ep_masters' });

        console.log('[OfflineSync] Initialized successfully with 3 stores.');

        // Listen for back online
        window.addEventListener('online', () => {
            console.log('[OfflineSync] 🔄 Back online. Starting sync...');
            this.syncAll();
        });

        // Periodic sync
        setInterval(() => {
            if (navigator.onLine) this.syncAll();
        }, 45000); // 45 seconds
    },

    async getCSRFToken() {
        // Multiple ways to get CSRF token
        let token = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
        
        if (!token) {
            token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        }
        if (!token) {
            const cookies = document.cookie.split(';');
            for (let cookie of cookies) {
                if (cookie.trim().startsWith('csrftoken=')) {
                    token = cookie.trim().split('=')[1];
                    break;
                }
            }
        }
        return token;
    },

    async queueRequest(store, url, payload, successMsg = 'Saved offline. Will sync when online.') {
        if (!store) {
            console.error('[OfflineSync] Store not initialized');
            return null;
        }

        const id = 'req_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        
        const reqData = {
            id: id,
            url: url,
            payload: payload,
            timestamp: new Date().toISOString()
        };

        await store.setItem(id, reqData);
        console.log(`[OfflineSync] ✅ Queued to ${url}`, reqData);

        this.showToast(successMsg);
        this.updateOfflineBadge();

        return id;
    },

    async processQueue(store, csrfToken) {
        if (!navigator.onLine || !store) return;

        const keys = await store.keys();
        if (keys.length === 0) return;

        console.log(`[OfflineSync] Processing ${keys.length} items from ${store._config.name}...`);

        for (let key of keys) {
            const reqData = await store.getItem(key);
            if (!reqData) continue;

            console.log(`[OfflineSync] Trying to sync purchase:`, reqData.payload); // ← Extra log

            try {
                const response = await fetch(reqData.url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken,
                        'Accept': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify(reqData.payload),
                    credentials: 'include'
                });

                console.log(`[OfflineSync] Response status for ${key}: ${response.status}`);

                if (response.ok) {
                    const result = await response.json().catch(() => ({}));
                    console.log(`[OfflineSync] Server response:`, result);

                    if (result.success || result.status === 'success' || response.status < 400) {
                        console.log(`[OfflineSync] ✅ Successfully synced purchase ${key}`);
                        await store.removeItem(key);
                    }
                } else {
                    console.warn(`[OfflineSync] Failed ${response.status} for ${key}`);
                }
            } catch (err) {
                console.error(`[OfflineSync] Error syncing ${key}:`, err);
            }
        }
    },

    async syncAll() {
        console.log('[OfflineSync] 🚀 Starting full synchronization...');
        
        const csrfToken = await this.getCSRFToken();
        if (!csrfToken) {
            console.warn('[OfflineSync] CSRF token not found. Sync may fail.');
        }

        await this.processQueue(this.salesStore, csrfToken);
        await this.processQueue(this.purchaseStore, csrfToken);
        await this.processQueue(this.masterStore, csrfToken);

        console.log('[OfflineSync] Sync cycle completed.');
    },

    updateOfflineBadge() {
        const badge = document.getElementById('offlineQueueBadge');
        if (badge) badge.style.display = 'inline-block';
    },

    showToast(message) {
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
            background: #f59e0b; color: white; padding: 12px 24px; border-radius: 30px;
            z-index: 99999; box-shadow: 0 4px 15px rgba(0,0,0,0.2); font-weight: bold;
            font-size: 14px; white-space: nowrap;
        `;
        toast.innerHTML = `<i class="fas fa-cloud-upload-alt me-2"></i> ${message}`;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.transition = 'opacity 0.5s';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 600);
        }, 4500);
    }
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    OfflineSync.init();
});

// Make it globally available for debugging
window.OfflineSync = OfflineSync;