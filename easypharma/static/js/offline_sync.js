/**
 * Easy Pharma — Offline Sync Manager v3.0
 * ─────────────────────────────────────────────────────────────────────
 * Handles:
 *   1. Product catalog preloading (POS + Master, up to 5000 each)
 *   2. Master data preloading (suppliers, product types, taxes, schedules, companies)
 *   3. Offline search fallback for POS and Purchase Entry
 *   4. Offline queue for sales, purchases, and quick-add medicine
 *   5. Auto-sync on reconnect + periodic 45s sync
 *   6. Offline invoice number generation
 *   7. Offline status banner + toast notifications
 *   8. Report pages offline support (cached data banner + disable filter submit)
 */

// Report pages that get offline cached-data support
const OFFLINE_REPORT_PATHS = [
    '/reports/daily-sale/',
    '/reports/stock/',
    '/reports/profit/',
    '/reports/schedule-h1/',
    '/reports/schedule-h1-purchase/',
    '/reports/schedule-h/',
    '/reports/half-yearly/',
    '/reports/gst/',
    '/reports/gstr1/',
    '/reports/gstr3b/',
    '/reports/doctor-sale/',
    '/reports/narcotic/',
    '/reports/product-history/',
    '/reports/purchase-analysis/',
    '/reports/sale-billwise-profit/',
    '/reports/sales-return/',
];

const OfflineSync = {

    // ─── Initialization ──────────────────────────────────────────────
    async init() {
        if (typeof localforage === 'undefined') {
            console.error('[OfflineSync] localforage is not loaded!');
            return false;
        }

        // ── Offline stores ──
        this.salesStore    = localforage.createInstance({ name: 'ep_sales' });
        this.purchaseStore = localforage.createInstance({ name: 'ep_purchases' });
        this.masterStore   = localforage.createInstance({ name: 'ep_masters' });
        this.productCache  = localforage.createInstance({ name: 'ep_product_cache' });
        this.masterData    = localforage.createInstance({ name: 'ep_master_data' }); // suppliers, types, taxes

        // ── Offline status tracking ──
        this._offlineSeq = 0;
        this._isOnline = navigator.onLine;

        // ── Listeners ──
        window.addEventListener('online', () => {
            this._isOnline = true;
            this._updateOnlineBanner(true);
            this.syncAll();
        });
        window.addEventListener('offline', () => {
            this._isOnline = false;
            this._updateOnlineBanner(false);
        });

        // ── Init offline banner ──
        this._initOfflineBanner();
        this._updateOnlineBanner(navigator.onLine);

        // ── Preload product catalog and master data ──
        this.preloadProductCache();
        this.preloadMasterData();

        // ── Periodic sync every 45 seconds ──
        setInterval(() => {
            if (navigator.onLine) this.syncAll();
        }, 45000);
    },

    // ─── Offline Banner ──────────────────────────────────────────────
    _initOfflineBanner() {
        if (document.getElementById('ep-offline-banner')) return;
        const banner = document.createElement('div');
        banner.id = 'ep-offline-banner';
        banner.style.cssText = `
            display: none; position: fixed; top: 0; left: 0; right: 0; z-index: 99999;
            background: #f59e0b; color: white; text-align: center;
            padding: 8px 16px; font-size: 13px; font-weight: 600;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        `;
        banner.innerHTML = `
            <i class="bi bi-wifi-off me-2"></i>
            You are offline — Bills & entries will be saved locally and auto-synced when back online.
            <span id="ep-offline-queue-count" class="ms-2 badge bg-dark"></span>
        `;
        document.body.prepend(banner);
    },

    _updateOnlineBanner(isOnline) {
        const banner = document.getElementById('ep-offline-banner');
        if (!banner) return;
        if (isOnline) {
            banner.style.display = 'none';
        } else {
            banner.style.display = 'block';
        }
    },

    async _updateQueueCount() {
        const el = document.getElementById('ep-offline-queue-count');
        if (!el) return;
        try {
            const sKeys = await this.salesStore.keys();
            const pKeys = await this.purchaseStore.keys();
            const mKeys = await this.masterStore.keys();
            const total = sKeys.length + pKeys.length + mKeys.length;
            if (total > 0) {
                el.textContent = `${total} pending`;
                el.style.display = 'inline-block';
            } else {
                el.style.display = 'none';
            }
        } catch (e) {}
    },

    // ─── CSRF Token ──────────────────────────────────────────────────
    async getCSRFToken() {
        let token = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
        if (!token) token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        if (!token) {
            for (let cookie of document.cookie.split(';')) {
                if (cookie.trim().startsWith('csrftoken=')) {
                    token = cookie.trim().split('=')[1];
                    break;
                }
            }
        }
        return token;
    },

    // ─── Offline Invoice Number ───────────────────────────────────────
    /**
     * Generates a temporary offline invoice number like "OFFLINE-300726-001"
     * This will be replaced with the real server invoice number on sync.
     */
    generateOfflineInvoiceNumber() {
        this._offlineSeq = (this._offlineSeq || 0) + 1;
        const now = new Date();
        const dateStr = String(now.getDate()).padStart(2,'0') +
                        String(now.getMonth()+1).padStart(2,'0') +
                        String(now.getFullYear()).slice(-2);
        const seq = String(this._offlineSeq).padStart(3, '0');
        return `OFFLINE-${dateStr}-${seq}`;
    },

    // ─── Product Cache Preload ────────────────────────────────────────
    async preloadProductCache() {
        if (!navigator.onLine) return;
        try {
            const lastSync = await this.productCache.getItem('last_product_sync_time');
            const now = Date.now();
            const cacheDuration = 15 * 60 * 1000; // 15 minutes

            // Check if pos_products exists in localforage and localStorage
            const existing = await this.productCache.getItem('pos_products');
            if (existing && Array.isArray(existing) && existing.length > 50 && lastSync && (now - lastSync < cacheDuration)) {
                // Ensure localStorage also has a copy
                try {
                    if (!localStorage.getItem('ep_pos_products_cache')) {
                        localStorage.setItem('ep_pos_products_cache', JSON.stringify(existing.slice(0, 2000)));
                    }
                } catch(e) {}
                return;
            }

            // Fetch all products for POS (with all batch-wise stock up to 10000)
            const posResponse = await fetch('/api/products/search/?limit=10000&nocache=1');
            if (posResponse.ok) {
                const products = await posResponse.json();
                if (Array.isArray(products) && products.length > 0) {
                    await this.productCache.setItem('pos_products', products);
                    await this.productCache.setItem('all_products', products);
                    // Also save to localStorage for instant synchronous fallback
                    try {
                        localStorage.setItem('ep_pos_products_cache', JSON.stringify(products.slice(0, 2000)));
                        localStorage.setItem('ep_pos_last_sync', String(now));
                    } catch(e) {
                        console.warn('[OfflineSync] localStorage quota, IndexedDB holds full catalog');
                    }
                    console.log(`[OfflineSync] Cached ${products.length} products with batch-wise stock for offline billing.`);
                }
            }

            // Fetch all products for Purchase Entry (without stock)
            const masterResponse = await fetch('/api/products/master-search/?limit=5000&nocache=1');
            if (masterResponse.ok) {
                const products = await masterResponse.json();
                if (Array.isArray(products) && products.length > 0) {
                    await this.productCache.setItem('master_products', products);
                    try {
                        localStorage.setItem('ep_master_products_cache', JSON.stringify(products.slice(0, 1500)));
                    } catch(e) {}
                }
            }

            await this.productCache.setItem('last_product_sync_time', now);
        } catch (e) {
            console.warn('[OfflineSync] Failed to preload product cache', e);
        }
    },

    // ─── Master Data Preload ─────────────────────────────────────────
    /**
     * Preloads suppliers, product types, tax rates, schedules, companies
     * so Quick Add Medicine and Purchase Entry dropdowns work offline.
     */
    async preloadMasterData() {
        if (!navigator.onLine) return;
        try {
            const lastSync = await this.masterData.getItem('last_master_sync_time');
            const now = Date.now();
            const cacheDuration = 60 * 60 * 1000; // 1 hour (master data rarely changes)

            if (lastSync && (now - lastSync < cacheDuration)) {
                return; // Fresh
            }

            // Try fetching master data APIs
            const endpoints = [
                { key: 'suppliers',      url: '/api/suppliers/search/?limit=1000' },
            ];

            for (const ep of endpoints) {
                try {
                    const res = await fetch(ep.url);
                    if (res.ok) {
                        const data = await res.json();
                        await this.masterData.setItem(ep.key, data);
                    }
                } catch (e) {
                    // Silently skip unavailable endpoints
                }
            }

            await this.masterData.setItem('last_master_sync_time', now);
        } catch (e) {
            console.warn('[OfflineSync] Failed to preload master data', e);
        }
    },

    // ─── Offline Product Search ───────────────────────────────────────
    /**
     * Searches locally cached products when offline.
     * Called by POS and Purchase Entry when navigator.onLine is false.
     * @param {string} query - search term
     * @param {string} type - 'pos' (with batches) or 'master' (without batches)
     * @returns {Array} matching products
     */
    /**
     * Searches locally cached products when offline.
     * Called by POS and Purchase Entry when navigator.onLine is false.
     * @param {string} query - search term
     * @param {string} type - 'pos' (with batches) or 'master' (without batches)
     * @returns {Array} matching products
     */
    async searchOfflineProducts(query, type = 'pos') {
        try {
            const cacheKey = type === 'pos' ? 'pos_products' : 'master_products';
            let products = await this.productCache.getItem(cacheKey);
            
            // Fallback to localStorage if IndexedDB is empty
            if (!Array.isArray(products) || products.length === 0) {
                try {
                    const localData = localStorage.getItem(type === 'pos' ? 'ep_pos_products_cache' : 'ep_master_products_cache');
                    if (localData) products = JSON.parse(localData);
                } catch (e) {}
            }
            if (!Array.isArray(products)) products = [];
            
            let combined = [...products];
            if (type !== 'pos') {
                const allProducts = await this.productCache.getItem('all_products') || [];
                const combinedIds = new Set(combined.map(p => p.id));
                allProducts.forEach(p => {
                    if (!combinedIds.has(p.id)) combined.push(p);
                });
            }

            const lowerQuery = (query || '').toLowerCase().trim();
            if (!lowerQuery) {
                // Return top items with active batches first
                return combined.sort((a, b) => (b.batches?.length || 0) - (a.batches?.length || 0)).slice(0, 30);
            }

            return combined.filter(p => {
                const name = (p.name || p.product_name || '').toLowerCase();
                const content = (p.content || p.salt || '').toLowerCase();
                const company = (p.company || p.company_name || '').toLowerCase();
                const hasMatchingBatch = Array.isArray(p.batches) && p.batches.some(b => 
                    (b.batch_no || b.batch_number || '').toLowerCase().includes(lowerQuery)
                );
                return name.includes(lowerQuery) || content.includes(lowerQuery) || company.includes(lowerQuery) || hasMatchingBatch;
            }).slice(0, 30);
        } catch (e) {
            console.error('[OfflineSync] searchOfflineProducts error:', e);
            return [];
        }
    },

    /**
     * Cache a newly created (Quick Add) product immediately into the local store
     * so the pharmacist can select it in the current bill without going online.
     */
    async cacheNewProduct(product) {
        if (!product) return;
        try {
            const formatted = {
                id: product.id,
                name: product.name || product.product_name,
                product_name: product.name || product.product_name,
                packing: product.packing || product.product_packing || '1',
                product_packing: product.packing || product.product_packing || '1',
                conversion_factor: parseInt(product.conversion_factor) || 1,
                tax_rate: product.tax_rate !== undefined && product.tax_rate !== null ? parseFloat(product.tax_rate) : 0,
                tax_id: product.tax_id || null,
                schedule_id: product.schedule_id || null,
                schedule_name: product.schedule_name || '',
                company_id: product.company_id || null,
                company_name: product.company_name || '',
                content_id: product.content_id || null,
                content: product.content || product.salt || '',
                salt: product.content || product.salt || '',
                hsn_code: product.hsn_code || '',
                batches: Array.isArray(product.batches) ? product.batches : [],
                is_offline: Boolean(product.is_offline)
            };

            const updateCacheStore = async (key) => {
                let list = await this.productCache.getItem(key) || [];
                const idx = list.findIndex(p => p.id === formatted.id || (p.name && p.name.toLowerCase() === formatted.name.toLowerCase()));
                if (idx >= 0) {
                    const existingBatches = list[idx].batches || [];
                    const newBatches = (Array.isArray(formatted.batches) && formatted.batches.length > 0) ? formatted.batches : existingBatches;
                    list[idx] = { ...list[idx], ...formatted, batches: newBatches, out_of_stock: newBatches.length === 0 };
                } else {
                    list.unshift(formatted);
                }
                await this.productCache.setItem(key, list.slice(0, 5000));
            };

            await updateCacheStore('pos_products');
            await updateCacheStore('master_products');
            await updateCacheStore('all_products');

            // Also update localStorage
            try {
                const localStr = localStorage.getItem('ep_pos_products_cache');
                let localList = localStr ? JSON.parse(localStr) : [];
                const fIdx = localList.findIndex(p => p.id === formatted.id || (p.name && p.name.toLowerCase() === formatted.name.toLowerCase()));
                if (fIdx >= 0) {
                    localList[fIdx] = { ...localList[fIdx], ...formatted };
                } else {
                    localList.unshift(formatted);
                }
                localStorage.setItem('ep_pos_products_cache', JSON.stringify(localList.slice(0, 2000)));
            } catch(e) {}
        } catch (e) {
            console.warn('[OfflineSync] Failed to cache new product', e);
        }
    },

    // ─── Queue Offline Request ────────────────────────────────────────
    async queueRequest(store, url, payload, successMsg = 'Saved offline. Will sync when online.') {
        if (!store) {
            console.error('[OfflineSync] Store not initialized');
            return null;
        }

        const id = 'req_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        const reqData = {
            id,
            url,
            payload,
            timestamp: new Date().toISOString()
        };

        await store.setItem(id, reqData);
        if (successMsg) this.showToast(successMsg);
        this._updateQueueCount();
        return id;
    },

    // ─── Process Queue ────────────────────────────────────────────────
    async processQueue(store, csrfToken) {
        if (!navigator.onLine || !store) return;

        const keys = await store.keys();
        if (keys.length === 0) return;

        for (let key of keys) {
            const reqData = await store.getItem(key);
            if (!reqData) continue;

            try {
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

                let result = {};
                try { result = await response.json(); } catch (e) {}

                if (response.ok || response.status === 200 || response.status === 201 || result.success) {
                    await store.removeItem(key);
                } else {
                    console.warn('[OfflineSync] Server rejected:', result);
                }
            } catch (err) {
                console.error('[OfflineSync] Sync failed for', key, err);
            }
        }
        this._updateQueueCount();
    },

    // ─── Sync SW Queue ────────────────────────────────────────────────
    async syncServiceWorkerQueue() {
        const dbName = 'ep-offline-requests';
        const storeName = 'requests';

        return new Promise((resolve) => {
            const request = indexedDB.open(dbName);
            request.onsuccess = async (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains(storeName)) {
                    db.close(); resolve(); return;
                }
                const tx = db.transaction(storeName, 'readwrite');
                const store = tx.objectStore(storeName);
                const getAllRequest = store.getAll();

                getAllRequest.onsuccess = async (e) => {
                    const items = e.target.result || [];
                    if (items.length === 0) { db.close(); resolve(); return; }

                    const csrfToken = await this.getCSRFToken();
                    for (const item of items) {
                        try {
                            const headers = { ...item.headers };
                            if (csrfToken) headers['X-CSRFToken'] = csrfToken;
                            headers['X-Requested-With'] = 'XMLHttpRequest';

                            const response = await fetch(item.url, {
                                method: item.method,
                                headers,
                                body: item.body,
                                credentials: 'include'
                            });

                            let result = {};
                            try { result = await response.json(); } catch (err) {}

                            if (response.ok || response.status === 200 || result.success) {
                                const deleteTx = db.transaction(storeName, 'readwrite');
                                deleteTx.objectStore(storeName).delete(item.id);
                            }
                        } catch (err) {
                            console.error('[OfflineSync] SW queue replay failed:', err);
                        }
                    }
                    db.close(); resolve();
                };
                getAllRequest.onerror = () => { db.close(); resolve(); };
            };
            request.onerror = () => resolve();
        });
    },

    // ─── Sync All ────────────────────────────────────────────────────
    async syncAll() {
        const csrfToken = await this.getCSRFToken();

        // Tell SW to replay its queue too
        if (navigator.serviceWorker && navigator.serviceWorker.controller) {
            navigator.serviceWorker.controller.postMessage('SYNC_OFFLINE');
        }

        await this.syncServiceWorkerQueue();

        // Flush any emergency sales queued directly in localStorage
        try {
            const rawQueue = localStorage.getItem('ep_offline_sales_queue');
            if (rawQueue) {
                const q = JSON.parse(rawQueue);
                if (Array.isArray(q) && q.length > 0) {
                    for (let item of q) {
                        await this.salesStore.setItem(item.id, {
                            id: item.id,
                            url: '/pos/',
                            payload: item.data,
                            timestamp: item.timestamp
                        });
                    }
                    localStorage.removeItem('ep_offline_sales_queue');
                }
            }
        } catch(e) {}

        // Master queue synced first so new products exist on server before purchases/sales
        await this.processQueue(this.masterStore, csrfToken);
        await this.processQueue(this.purchaseStore, csrfToken);
        await this.processQueue(this.salesStore, csrfToken);
        this._updateQueueCount();

        // After sync, refresh product cache if it's old
        if (navigator.onLine) {
            this.preloadProductCache();
        }
    },

    // ─── Report Offline Support ───────────────────────────────────────
    /**
     * Call on report pages to:
     *  1. Save the current URL + timestamp to localStorage (marks this report as "cached")
     *  2. When offline: show a prominent "Viewing cached data" banner
     *  3. When offline: disable filter form submit + show tooltip
     *
     * Called automatically for all report pages on DOMContentLoaded.
     */
    initReportOfflineSupport() {
        const LS_KEY = 'ep_report_last_fetch';
        const path = window.location.pathname + window.location.search;

        // Save timestamp when online
        const saveTimestamp = () => {
            try {
                const timestamps = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
                timestamps[window.location.pathname] = {
                    time: Date.now(),
                    label: document.title || window.location.pathname
                };
                localStorage.setItem(LS_KEY, JSON.stringify(timestamps));
            } catch (e) {}
        };

        const getLastFetch = () => {
            try {
                const timestamps = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
                return timestamps[window.location.pathname] || null;
            } catch (e) { return null; }
        };

        const formatTime = (ts) => {
            const d = new Date(ts);
            return d.toLocaleString('en-IN', {
                day: '2-digit', month: 'short', year: 'numeric',
                hour: '2-digit', minute: '2-digit'
            });
        };

        const showCachedBanner = () => {
            if (document.getElementById('ep-report-cached-banner')) return;

            const lastFetch = getLastFetch();
            const timeLabel = lastFetch
                ? `Last updated: <strong>${formatTime(lastFetch.time)}</strong>`
                : 'Last updated: <strong>Unknown</strong>';

            const banner = document.createElement('div');
            banner.id = 'ep-report-cached-banner';
            banner.style.cssText = `
                position: sticky; top: 0; z-index: 9998;
                background: linear-gradient(135deg, #1e3a5f, #2563eb);
                color: #fff; padding: 10px 20px;
                display: flex; align-items: center; justify-content: space-between;
                font-size: 13px; box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                flex-wrap: wrap; gap: 8px;
            `;
            banner.innerHTML = `
                <span>
                    <i class="bi bi-hdd-fill me-2" style="color:#93c5fd"></i>
                    <strong>Offline Mode</strong> — Showing cached report data.
                    ${timeLabel}.
                </span>
                <span style="display:flex;gap:8px;align-items:center;">
                    <span class="badge" style="background:#1e40af;padding:5px 10px;">
                        <i class="bi bi-wifi-off me-1"></i>No Internet
                    </span>
                    <span style="opacity:0.75;font-size:11px;">Filters disabled while offline</span>
                </span>
            `;

            // Insert at top of main content area
            const content = document.getElementById('content') || document.querySelector('.container-fluid') || document.body;
            content.insertBefore(banner, content.firstChild);

            // Disable all filter forms on the page
            document.querySelectorAll('form[method="GET"], form[method="get"]').forEach(form => {
                // Disable all inputs, selects, buttons
                form.querySelectorAll('input, select, button[type="submit"]').forEach(el => {
                    el.disabled = true;
                    el.title = 'Filters disabled while offline';
                    el.style.opacity = '0.5';
                    el.style.cursor = 'not-allowed';
                });
                // Prevent onchange auto-submits (e.g. stock report dropdowns)
                form.querySelectorAll('select[onchange]').forEach(sel => {
                    sel.removeAttribute('onchange');
                });
                form.addEventListener('submit', e => {
                    e.preventDefault();
                    this.showToast('Filters require internet connection. Showing cached data.', 'info');
                });
            });

            // Also disable quick-filter links
            document.querySelectorAll('a[href*="?"]').forEach(link => {
                link.addEventListener('click', e => {
                    e.preventDefault();
                    this.showToast('Filters require internet. Showing cached data.', 'info');
                });
                link.style.opacity = '0.5';
                link.style.cursor = 'not-allowed';
                link.title = 'Disabled while offline';
            });
        };

        const removeCachedBanner = () => {
            const banner = document.getElementById('ep-report-cached-banner');
            if (banner) banner.remove();
            // Re-enable forms on reconnect
            document.querySelectorAll('form[method="GET"] input, form[method="GET"] select, form[method="GET"] button').forEach(el => {
                el.disabled = false;
                el.style.opacity = '';
                el.style.cursor = '';
            });
        };

        if (!navigator.onLine) {
            showCachedBanner();
        } else {
            saveTimestamp(); // Save "I visited this page at X time" for next offline visit
        }

        window.addEventListener('offline', () => showCachedBanner());
        window.addEventListener('online', () => {
            removeCachedBanner();
            saveTimestamp();
        });
    },

    // ─── Toast ───────────────────────────────────────────────────────
    showToast(message, type = 'warning') {
        const colors = {
            warning: '#f59e0b',
            success: '#10b981',
            error:   '#ef4444',
            info:    '#3b82f6'
        };
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
            background: ${colors[type] || colors.warning}; color: white;
            padding: 12px 24px; border-radius: 30px; z-index: 99999;
            box-shadow: 0 4px 15px rgba(0,0,0,0.25); font-weight: 600;
            font-size: 14px; white-space: nowrap; max-width: 90vw;
            animation: epToastIn 0.3s ease;
        `;
        toast.innerHTML = `<i class="bi bi-cloud-arrow-up-fill me-2"></i>${message}`;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.transition = 'opacity 0.5s';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 600);
        }, 4500);
    },

    // ─── Offline Sales Inspection & Management ──────────────────────
    async getPendingSales() {
        const list = [];
        if (this.salesStore) {
            try {
                const keys = await this.salesStore.keys();
                for (let k of keys) {
                    const item = await this.salesStore.getItem(k);
                    if (item && (item.payload || item.data)) {
                        list.push({
                            storeKey: k,
                            id: item.id || k,
                            data: item.payload || item.data,
                            timestamp: item.timestamp || new Date().toISOString()
                        });
                    }
                }
            } catch(e) {
                console.warn('[OfflineSync] Error reading salesStore:', e);
            }
        }
        try {
            const raw = localStorage.getItem('ep_offline_sales_queue');
            if (raw) {
                const q = JSON.parse(raw);
                if (Array.isArray(q)) {
                    q.forEach(item => {
                        if (item && item.data && !list.some(x => x.id === item.id)) {
                            list.push({
                                storeKey: null,
                                isLocalStorage: true,
                                id: item.id,
                                data: item.data,
                                timestamp: item.timestamp || new Date().toISOString()
                            });
                        }
                    });
                }
            }
        } catch(e) {}

        list.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        return list;
    },

    async deletePendingSale(keyOrId) {
        if (this.salesStore) {
            try {
                await this.salesStore.removeItem(keyOrId);
            } catch(e) {}
        }
        try {
            const raw = localStorage.getItem('ep_offline_sales_queue');
            if (raw) {
                let q = JSON.parse(raw);
                if (Array.isArray(q)) {
                    q = q.filter(x => x.id !== keyOrId);
                    localStorage.setItem('ep_offline_sales_queue', JSON.stringify(q));
                }
            }
        } catch(e) {}
        this._updateQueueCount();
    },

    printOfflineSaleReceipt(data) {
        const W = 42;
        const lines = [];
        lines.push(" ");
        const invoiceDate = data.date || new Date().toLocaleDateString('en-GB');
        lines.push("           EASY PHARMA (OFFLINE MEMO)");
        lines.push(" CASH MEMO: Pending Sync*  Dt: " + invoiceDate);
        lines.push(" " + "-".repeat(W));
        lines.push(" Pt  : " + (data.patient_name || 'CASH CUSTOMER').substring(0, W));
        if (data.patient_phone) lines.push(" Ph  : " + data.patient_phone.substring(0, W));
        if (data.doctor_name) lines.push(" Dr  : " + data.doctor_name.substring(0, W));
        lines.push(" " + "-".repeat(W));
        lines.push(" PRODUCT               BATCH    QTY     TOTAL");
        lines.push(" " + "-".repeat(W));
        const items = data.items || data.cart || [];
        items.forEach(it => {
            const n = (it.name || '').substring(0, 18).padEnd(19);
            const b = (it.batch_no || 'OFFLINE').substring(0, 7).padEnd(8);
            const q = String(it.quantity || 1).padStart(3);
            const t = Number(it.total || (it.price * it.quantity) || 0).toFixed(2).padStart(9);
            lines.push(` ${n} ${b} ${q} ${t}`);
        });
        lines.push(" " + "-".repeat(W));
        lines.push(` Sub Total:   ₹${Number(data.sub_total || 0).toFixed(2)}`.padStart(W));
        if (Number(data.tax_amount) > 0) {
            lines.push(` Tax/GST:     ₹${Number(data.tax_amount || 0).toFixed(2)}`.padStart(W));
        }
        if (Number(data.discount_amount) > 0) {
            lines.push(` Discount:    ₹${Number(data.discount_amount || 0).toFixed(2)}`.padStart(W));
        }
        lines.push(" " + "-".repeat(W));
        lines.push(` GRAND TOTAL: ₹${Number(data.total_amount || 0).toFixed(2)}`.padStart(W));
        lines.push(" " + "-".repeat(W));
        lines.push("   * Offline Bill - Will sync when online *");

        const win = window.open('', '_blank', 'width=500,height=600');
        if (win) {
            win.document.write(`
                <!DOCTYPE html><html><head><meta charset="utf-8"><title>Offline Receipt</title>
                <style>body{margin:0;padding:14px;font-family:monospace;font-size:12px;font-weight:bold;line-height:1.2;white-space:pre;}</style>
                </head><body><pre>${lines.join('\n')}</pre><script>window.onload=function(){window.print();};<\/script></body></html>
            `);
            win.document.close();
        }
    },

    // Legacy compat
    updateOfflineBadge() {
        this._updateQueueCount();
    }
};

// ─── Initialize on DOM ready ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    OfflineSync.init();

    // Auto-enable offline reports support if on a report page
    const currentPath = window.location.pathname;
    if (OFFLINE_REPORT_PATHS.some(p => currentPath.startsWith(p)) || currentPath.includes('/report')) {
        OfflineSync.initReportOfflineSupport();
    }
});

// Global access for debugging and POS/Purchase page JS
window.OfflineSync = OfflineSync;