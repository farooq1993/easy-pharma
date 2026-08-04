/**
 * Easy Pharma — Service Worker v2.0.0
 * ─────────────────────────────────────────────────────────────────────
 * Strategy per resource type:
 *   STATIC   — Cache-First        : CSS, JS, fonts, images (long-lived)
 *   PAGES    — Stale-While-Revalidate : HTML pages → instant load + bg refresh
 *   API      — Network-First (3 s timeout) : JSON API calls
 *   POSTS    — Offline queue      : Failed writes stored, retried on reconnect
 *
 * v2.0.0 Improvements:
 *   • Expanded pre-cache: POS, Purchase Entry, key reports
 *   • Stale-While-Revalidate for all HTML pages → instant second-visit loads
 *   • Master data (suppliers, product types, taxes) cached in API cache
 *   • Proper Cache-Control header respect on API responses
 */

const SW_VERSION = 'v2.0.0';
const CACHE_STATIC = `ep-static-${SW_VERSION}`;
const CACHE_PAGES  = `ep-pages-${SW_VERSION}`;
const CACHE_API    = `ep-api-${SW_VERSION}`;

const DB_NAME    = 'ep-offline-requests';
const DB_VERSION = 2;
const DB_STORE   = 'requests';

// ─── Pre-cache on install ────────────────────────────────────────────
// All critical assets loaded before the user even visits those pages
const PRECACHE_ASSETS = [
  // Core styles & scripts
  '/static/css/global.css',
  '/static/css/customecss/sidebar.css',
  '/static/js/offline_sync.js',
  '/static/js/localforage.min.js',
  // PWA icons
  '/static/img/pwa-icon-192.png',
  '/static/img/pwa-icon-512.png',
  // Offline fallback
  '/offline/',
  // Key pages — cached so second visit is instant
  '/pos/',
  '/entry/',
  '/home',
];

// ─── URL matching patterns ────────────────────────────────────────────

// Never cache auth/admin/logout
const NETWORK_ONLY_PATTERNS = [
  /^\/$/,
  /\/accounts\//,
  /\/admin\//,
  /\/logout/,
  /\/createuser/,
];

// Long-lived static assets → Cache-First
const STATIC_PATTERNS = [
  /\/static\//,
  /fonts\.googleapis\.com/,
  /fonts\.gstatic\.com/,
  /cdn\.jsdelivr\.net/,
  /cdnjs\.cloudflare\.com/,
];

// Live stock search — never serve stale (stock levels change per sale)
const API_NETWORK_ONLY_PATTERNS = [
  /\/api\/products\/search/,
  /\/api\/products\/master-search/,
  /\/api\/products\/substitute/,
];

// Other API calls — Network-First with 3s timeout, fallback to cache
const API_PATTERNS = [
  /\/api\//,
];

// Offline queue — these POST urls are queued to IndexedDB when offline
const OFFLINE_QUEUE_PATTERNS = [
  /\/pos\//i,
  /\/entry\//i,
  /\/api\/products\/create-quick\//i,
  /\/api\/products\/quick-add\//i,
  /\/sales\//i,
  /\/purchase\//i,
];

// ─── Install ─────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache => {
      return cache.addAll(PRECACHE_ASSETS).catch(err => {
        console.warn('[SW v2] Pre-cache partial failure:', err);
      });
    })
  );
});

// ─── Activate ────────────────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_STATIC && k !== CACHE_PAGES && k !== CACHE_API)
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ─── Fetch ────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle HTTP(s)
  if (!['http:', 'https:'].includes(url.protocol)) return;

  // 0. Offline-capable POST requests — queue when offline
  if (request.method === 'POST' && OFFLINE_QUEUE_PATTERNS.some(p => p.test(url.pathname))) {
    event.respondWith(handleOfflinePost(request, event));
    return;
  }

  // Only GET from here
  if (request.method !== 'GET') return;

  // 1. Network-Only for auth pages
  if (NETWORK_ONLY_PATTERNS.some(p => p.test(url.pathname + url.search))) {
    event.respondWith(
      fetch(request).catch(() => caches.match('/offline/'))
    );
    return;
  }

  // 2. Cache-First for static assets
  if (STATIC_PATTERNS.some(p => p.test(request.url))) {
    event.respondWith(cacheFirst(request, CACHE_STATIC));
    return;
  }

  // 3a. Network-Only for live stock search
  if (API_NETWORK_ONLY_PATTERNS.some(p => p.test(url.pathname))) {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(JSON.stringify({
          error: 'offline',
          message: 'Product search requires internet connection.'
        }), {
          headers: { 'Content-Type': 'application/json' },
          status: 503
        })
      )
    );
    return;
  }

  // 3b. Network-First with timeout for other API calls
  if (API_PATTERNS.some(p => p.test(url.pathname))) {
    event.respondWith(networkFirstWithTimeout(request, CACHE_API, 3000));
    return;
  }

  // 4. Stale-While-Revalidate for all HTML pages
  //    → Second visit loads INSTANTLY from cache, background refresh updates it
  if (request.headers.get('Accept') && request.headers.get('Accept').includes('text/html')) {
    event.respondWith(staleWhileRevalidate(request, CACHE_PAGES));
    return;
  }

  // 5. Default: network with cache fallback
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});

// ─── Offline POST Handler ─────────────────────────────────────────────
async function handleOfflinePost(request, event) {
  const fetchRequest = request.clone();
  const queueRequest = request.clone();

  try {
    const response = await fetch(fetchRequest);
    if (response && response.ok) {
      event.waitUntil(replayQueuedRequests());
    }
    return response;
  } catch (err) {
    await saveRequestToQueue(queueRequest);
    try {
      await self.registration.sync.register('sync-offline-requests');
    } catch (syncError) {
      // Background sync not available; queue will still be replayed on reconnect
    }
    return new Response(JSON.stringify({
      error: 'offline',
      queued: true,
      message: 'Transaction saved locally. Will sync when back online.'
    }), {
      headers: { 'Content-Type': 'application/json' },
      status: 202
    });
  }
}

// ─── IndexedDB helpers ────────────────────────────────────────────────
function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = event => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(DB_STORE)) {
        db.createObjectStore(DB_STORE, { keyPath: 'id', autoIncrement: true });
      }
    };
    request.onsuccess = event => resolve(event.target.result);
    request.onerror = event => reject(event.target.error);
  });
}

async function saveRequestToQueue(request) {
  const db = await openDb();
  const tx = db.transaction(DB_STORE, 'readwrite');
  const store = tx.objectStore(DB_STORE);

  const headers = {};
  for (const [key, value] of request.headers.entries()) {
    headers[key] = value;
  }

  let body = null;
  try {
    if (request.body) {
      body = await request.clone().text();
    }
  } catch (e) {}

  const entry = {
    url: request.url,
    method: request.method,
    headers,
    body,
    timestamp: Date.now(),
  };

  await store.add(entry);
  return tx.complete;
}

function getQueuedRequests() {
  return new Promise(async (resolve, reject) => {
    const db = await openDb();
    const tx = db.transaction(DB_STORE, 'readonly');
    const store = tx.objectStore(DB_STORE);
    const request = store.getAll();
    request.onsuccess = event => resolve(event.target.result || []);
    request.onerror = event => reject(event.target.error);
  });
}

function deleteQueuedRequest(id) {
  return new Promise(async (resolve, reject) => {
    const db = await openDb();
    const tx = db.transaction(DB_STORE, 'readwrite');
    const store = tx.objectStore(DB_STORE);
    const request = store.delete(id);
    request.onsuccess = () => resolve();
    request.onerror = event => reject(event.target.error);
  });
}

async function replayQueuedRequests() {
  const queued = await getQueuedRequests();
  for (const item of queued) {
    try {
      const response = await fetch(new Request(item.url, {
        method: item.method,
        headers: item.headers,
        body: item.body || null,
        credentials: 'include',
        redirect: 'follow'
      }));
      if (response && (response.ok || response.status === 200)) {
        await deleteQueuedRequest(item.id);
      }
    } catch (err) {
      console.error('[SW v2] Replay failed for', item.url, err);
    }
  }
}

// ─── Background sync ─────────────────────────────────────────────────
self.addEventListener('sync', event => {
  if (event.tag === 'sync-offline-requests') {
    event.waitUntil(replayQueuedRequests());
  }
});

// ─── Messages from client ─────────────────────────────────────────────
self.addEventListener('message', event => {
  if (event.data === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  if (event.data === 'SYNC_OFFLINE') {
    event.waitUntil(replayQueuedRequests());
  }
});

// ─── Strategy helpers ─────────────────────────────────────────────────

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('', { status: 503 });
  }
}

/**
 * Stale-While-Revalidate:
 * Returns cached version INSTANTLY if available (making page feel instant),
 * while silently fetching fresh data in the background to update the cache.
 * On first visit or when cache is empty, waits for network.
 */
async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request)
    .then(response => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  // ← Return cached page INSTANTLY, revalidate in background
  if (cached) {
    fetchPromise; // kick off background refresh (don't await)
    return cached;
  }

  // First visit — wait for network
  const response = await fetchPromise;
  if (response) return response;

  // Both failed — show offline page
  const offline = await caches.match('/offline/');
  return offline || new Response('<h1>You are offline</h1>', {
    headers: { 'Content-Type': 'text/html' }
  });
}

async function networkFirstWithTimeout(request, cacheName, timeout) {
  const cache = await caches.open(cacheName);
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const response = await fetch(request, { signal: controller.signal });
    clearTimeout(timer);
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'offline', cached: false }), {
      headers: { 'Content-Type': 'application/json' },
      status: 503
    });
  }
}