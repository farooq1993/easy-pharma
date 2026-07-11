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

        // Preload product cache for offline use
        this.preloadProductCache();

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

    async preloadProductCache() {
        if (!navigator.onLine) return;
        try {
            console.log('[OfflineSync] Preloading product cache...');
            // Fetch products for POS (with batches)
            const posResponse = await fetch('/api/products/search/?limit=2000');
            if (posResponse.ok) {
                const products = await posResponse.json();
                if (Array.isArray(products) && products.length > 0) {
                    const store = localforage.createInstance({ name: 'ep_product_cache' });
                    await store.setItem('pos_products', products);
                    await store.setItem('all_products', products);
                    console.log(`[OfflineSync] Cached ${products.length} products for POS offline use.`);
                }
            }
            
            // Fetch products for Purchase Entry (without batches)
            const masterResponse = await fetch('/api/products/master-search/?limit=2000');
            if (masterResponse.ok) {
                const products = await masterResponse.json();
                if (Array.isArray(products) && products.length > 0) {
                    const store = localforage.createInstance({ name: 'ep_product_cache' });
                    await store.setItem('master_products', products);
                    console.log(`[OfflineSync] Cached ${products.length} products for Purchase offline use.`);
                }
            }
        } catch (e) {
            console.warn('[OfflineSync] Failed to preload product cache', e);
        }
    },

    async syncServiceWorkerQueue() {
        const dbName = 'ep-offline-requests';
        const storeName = 'requests';
        
        return new Promise((resolve) => {
            const request = indexedDB.open(dbName);
            request.onsuccess = async (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains(storeName)) {
                    db.close();
                    resolve();
                    return;
                }
                
                const tx = db.transaction(storeName, 'readwrite');
                const store = tx.objectStore(storeName);
                const getAllRequest = store.getAll();
                
                getAllRequest.onsuccess = async (e) => {
                    const items = e.target.result || [];
                    if (items.length === 0) {
                        db.close();
                        resolve();
                        return;
                    }
                    
                    console.log(`[OfflineSync] Syncing ${items.length} Service Worker queued requests...`);
                    const csrfToken = await this.getCSRFToken();
                    
                    for (const item of items) {
                        try {
                            const headers = { ...item.headers };
                            if (csrfToken) {
                                headers['X-CSRFToken'] = csrfToken;
                            }
                            headers['X-Requested-With'] = 'XMLHttpRequest';
                            
                            const response = await fetch(item.url, {
                                method: item.method,
                                headers: headers,
                                body: item.body,
                                credentials: 'include'
                            });
                            
                            let result = {};
                            try {
                                result = await response.json();
                            } catch (err) {}
                            
                            if (response.ok || response.status === 200 || result.success) {
                                const deleteTx = db.transaction(storeName, 'readwrite');
                                const deleteStore = deleteTx.objectStore(storeName);
                                deleteStore.delete(item.id);
                                console.log(`[OfflineSync] Successfully synced SW request: ${item.url}`);
                            }
                        } catch (err) {
                            console.error(`[OfflineSync] Failed to sync SW request:`, err);
                        }
                    }
                    db.close();
                    resolve();
                };
                getAllRequest.onerror = () => {
                    db.close();
                    resolve();
                };
            };
            request.onerror = () => {
                resolve();
            };
        });
    },

    // Add this in OfflineSync object
    async cacheProducts(products) {
        try {
            const store = localforage.createInstance({ name: 'ep_product_cache' });
            // Merge with existing cached products instead of overwriting entirely
            let existing = await store.getItem('all_products') || [];
            const existingIds = new Set(existing.map(p => p.id));
            products.forEach(p => {
                if (!existingIds.has(p.id)) {
                    existing.push(p);
                }
            });
            await store.setItem('all_products', existing.slice(0, 1000)); // limit total cache size
            console.log('[OfflineSync] Products cached for offline search');
        } catch (e) {
            console.warn('[OfflineSync] Failed to cache products', e);
        }
    },

    async searchOfflineProducts(query, type = 'pos') {
        try {
            const store = localforage.createInstance({ name: 'ep_product_cache' });
            const allProducts = await store.getItem('all_products') || [];
            const preloadedKey = type === 'pos' ? 'pos_products' : 'master_products';
            const preloadedProducts = await store.getItem(preloadedKey) || [];
            
            const combined = [...allProducts];
            const combinedIds = new Set(combined.map(p => p.id));
            preloadedProducts.forEach(p => {
                if (!combinedIds.has(p.id)) {
                    combined.push(p);
                }
            });
            
            const lowerQuery = query.toLowerCase();
            
            return combined.filter(product => 
                product.name.toLowerCase().includes(lowerQuery) ||
                (product.content && product.content.toLowerCase().includes(lowerQuery))
            ).slice(0, 30); // limit results
        } catch (e) {
            return [];
        }
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

            try {
                console.log(`[OfflineSync] Sending queued purchase:`, reqData.url);

                const response = await fetch(reqData.url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken || '',
                        'X-Requested-With': 'XMLHttpRequest',
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify(reqData.payload),
                    credentials: 'include'
                });

                console.log(`[OfflineSync] Response Status: ${response.status}`);

                let result = {};
                try {
                    result = await response.json();
                } catch (e) {}

                console.log(`[OfflineSync] Server Result:`, result);

                if (response.ok || response.status === 200 || response.status === 201 || result.success) {
                    console.log(`[OfflineSync] ✅ Successfully synced ${key}`);
                    await store.removeItem(key);
                } else {
                    console.warn(`[OfflineSync] Rejected by server:`, result);
                }
            } catch (err) {
                console.error(`[OfflineSync] Failed to sync ${key}:`, err);
            }
        }
    },

    async syncAll() {
        console.log('[OfflineSync] 🚀 Starting full synchronization...');
        
        const csrfToken = await this.getCSRFToken();
        if (!csrfToken) {
            console.warn('[OfflineSync] CSRF token not found. Sync may fail.');
        }

        // Notify SW to sync its background queue
        if (navigator.serviceWorker && navigator.serviceWorker.controller) {
            navigator.serviceWorker.controller.postMessage('SYNC_OFFLINE');
        }

        await this.syncServiceWorkerQueue();
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