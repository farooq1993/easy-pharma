// Offline Sync Manager for Easy Pharma PWA
// Requires localforage to be loaded.

const OfflineSync = {
    async init() {
        // Initialize stores
        this.salesStore = localforage.createInstance({ name: 'ep_sales' });
        this.purchaseStore = localforage.createInstance({ name: 'ep_purchases' });
        this.masterStore = localforage.createInstance({ name: 'ep_masters' });

        // Listen for back online
        window.addEventListener('online', () => {
            console.log('[OfflineSync] Back online. Triggering sync...');
            this.syncAll();
        });

        // Background periodic sync if currently online
        setInterval(() => {
            if (navigator.onLine) {
                this.syncAll();
            }
        }, 60000); // Check every minute
    },

    // ── Generic Queue Logic ──
    async queueRequest(store, url, payload, successMsg) {
        const id = 'req_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
        const reqData = {
            id: id,
            url: url,
            payload: payload,
            timestamp: new Date().toISOString()
        };
        await store.setItem(id, reqData);
        console.log(`[OfflineSync] Queued offline request to ${url}`, reqData);
        
        // Show visual indicator
        this.showToast(successMsg || 'Saved offline. Will sync when online.');
        
        // Update badge if exists
        const badge = document.getElementById('offlineQueueBadge');
        if (badge) badge.style.display = 'inline-block';
        
        return id;
    },

    async processQueue(store, csrfToken) {
        if (!navigator.onLine) return;
        
        const keys = await store.keys();
        if (keys.length === 0) return;

        console.log(`[OfflineSync] Processing ${keys.length} items in store ${store._config.name}...`);
        
        for (let key of keys) {
            const reqData = await store.getItem(key);
            if (!reqData) continue;

            try {
                const response = await fetch(reqData.url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify(reqData.payload)
                });

                if (response.ok) {
                    const result = await response.json();
                    if (result.success) {
                        console.log(`[OfflineSync] Synced item ${key} successfully.`);
                        await store.removeItem(key);
                    } else {
                        console.warn(`[OfflineSync] Server rejected item ${key}:`, result.error);
                        // If server permanently rejects it (e.g. invalid data), we might need to remove it to prevent blocking
                        // For now, we'll keep it to let user manually fix it, or if it's a conflict we drop it.
                        // For simplicity, if it's a hard error, remove it so it doesn't loop forever.
                        if (result.error && result.error.includes("already exists")) {
                            await store.removeItem(key);
                        }
                    }
                }
            } catch (err) {
                console.warn(`[OfflineSync] Network error while syncing ${key}. Will retry later.`, err);
            }
        }
    },

    async syncAll() {
        const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (!csrfInput) return;
        const token = csrfInput.value;

        await this.processQueue(this.salesStore, token);
        await this.processQueue(this.purchaseStore, token);
        await this.processQueue(this.masterStore, token);
    },

    showToast(message) {
        // Create a simple toast notification
        const toast = document.createElement('div');
        toast.style.position = 'fixed';
        toast.style.bottom = '80px';
        toast.style.left = '50%';
        toast.style.transform = 'translateX(-50%)';
        toast.style.background = '#f59e0b';
        toast.style.color = '#fff';
        toast.style.padding = '10px 20px';
        toast.style.borderRadius = '30px';
        toast.style.zIndex = '99999';
        toast.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
        toast.style.fontWeight = 'bold';
        toast.style.fontSize = '14px';
        toast.innerHTML = `<i class="fas fa-cloud-upload-alt me-2"></i> ${message}`;
        
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.5s';
            setTimeout(() => toast.remove(), 500);
        }, 4000);
    }
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    if (typeof localforage !== 'undefined') {
        OfflineSync.init();
    } else {
        console.warn('localforage not loaded. Offline sync disabled.');
    }
});
