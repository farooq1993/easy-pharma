/**
 * Easy Pharma — Service Worker
 * Provides offline support with a three-tier caching strategy:
 *   1. STATIC  — Cache-First  : CSS, JS, fonts, images (long-lived)
 *   2. PAGES   — Stale-While-Revalidate : HTML pages visited by the user
 *   3. API     — Network-First (3 s timeout) : JSON API calls for live data
 *
 * IMPORTANT: POS billing and purchase entry can now queue writes while offline.
 * Failed POST transactions are stored locally and retried when connectivity returns.
 */

const SW_VERSION = 'v1.5.5';   // 
const CACHE_STATIC = `ep-static-${SW_VERSION}`;
const CACHE_PAGES  = `ep-pages-${SW_VERSION}`;
const CACHE_API    = `ep-api-${SW_VERSION}`;

const DB_NAME = 'ep-offline-requests';
const DB_VERSION = 1;
const DB_STORE = 'requests';

// Static assets to pre-cache on install
const PRECACHE_ASSETS = [
  '/static/css/global.css',
  '/static/css/customecss/sidebar.css',
  '/static/img/pwa-icon-192.png',
  '/static/img/pwa-icon-512.png',
  '/offline/',
  '/pos/',
  '/purchase/',
];

// URLs whose responses should always come from the network (write/auth pages)
const NETWORK_ONLY_PATTERNS = [
  /\/accounts\//,
  /\/admin\//,
];

// URLs that are pure static assets (Cache-First)
const STATIC_PATTERNS = [
  /\/static\//,
  /fonts\.googleapis\.com/,
  /fonts\.gstatic\.com/,
  /cdn\.jsdelivr\.net/,
  /cdnjs\.cloudflare\.com/,
];

// API patterns — split by behaviour
const API_NETWORK_ONLY_PATTERNS = [
  /\/api\/products\/search/,   // live stock search — never serve stale
  /\/api\/products\/master-search/,
  /\/api\/products\/substitute/, // live stock substitute
  /\/api\/products\/.*search.*/, // extra safety
];

const API_PATTERNS = [
  /\/api\//,
];

// API POST requests that should be queued when offline
// Line ~60 ke aas-paas — isse replace kar do
const OFFLINE_QUEUE_PATTERNS = [
  /\/api\//i,
  /\/pos\//i,           // ← Yeh important hai
  /\/entry\//i,         // Purchase entry ke liye
  /\/sales\//i,
  /\/purchase\//i,
];
// const OFFLINE_QUEUE_PATTERNS = [
//   /\/api\/(sales|purchase|returns?|invoice|order|checkout)/i,
// ];

// ─── Install ────────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache => {
      return cache.addAll(PRECACHE_ASSETS).catch(err => {
        console.warn('[SW] Pre-cache partial failure:', err);
      });
    })
  );
});

// ─── Activate ───────────────────────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_STATIC && k !== CACHE_PAGES && k !== CACHE_API)
          .map(k => {
            console.log('[SW] Deleting old cache:', k);
            return caches.delete(k);
          })
      )
    ).then(() => self.clients.claim())
  );
});

// ─── Fetch ──────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle HTTP(s) requests
  if (!['http:', 'https:'].includes(url.protocol)) return;

  // Handle offline-capable POST requests first
  if (request.method === 'POST' && OFFLINE_QUEUE_PATTERNS.some(p => p.test(url.pathname))) {
    event.respondWith(handleOfflinePost(request, event));
    return;
  }

  // Only handle GET requests from here.
  if (request.method !== 'GET') return;

  // 1. Network-Only for auth/admin pages and critical form actions
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

  // 3a. Network-Only for live stock search APIs (must never return stale stock)
    // 3a. Special handling for product search (live data)
  if (API_NETWORK_ONLY_PATTERNS.some(p => p.test(url.pathname))) {
    event.respondWith(
      fetch(request).catch(() => 
        new Response(JSON.stringify({ 
          results: [],
          error: 'offline',
          message: 'Product search requires internet.' 
        }), {
          headers: { 'Content-Type': 'application/json' },
          status: 200   // ← 503 ki jagah 200 kar do taaki frontend crash na kare
        })
      )
    );
    return;
  }

  // 3b. Network-First (with timeout) for other API calls
  if (API_PATTERNS.some(p => p.test(url.pathname))) {
    event.respondWith(networkFirstWithTimeout(request, CACHE_API, 3000));
    return;
  }

  // 4. Stale-While-Revalidate for HTML pages
  if (request.headers.get('Accept') && request.headers.get('Accept').includes('text/html')) {
    event.respondWith(staleWhileRevalidate(request, CACHE_PAGES));
    return;
  }

  // 5. Default: network with cache fallback
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});

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
      // Background sync not available; offline queue will still be processed later.
    }
    console.log('[SW] POST intercepted for offline queuing:', request.url);
    return new Response(JSON.stringify({
      error: 'offline',
      queued: true,
      message: 'Transaction saved locally and will sync when back online.'
    }), {
      headers: { 'Content-Type': 'application/json' },
      status: 202
    });
  }
}

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
  console.log('[SW] Request queued successfully:', request.url);
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
  console.log(`[SW] Replaying ${queued.length} queued requests...`);

  for (const item of queued) {
    try {
      const request = new Request(item.url, {
        method: item.method,
        headers: item.headers,
        body: item.body || null,
        credentials: 'include',        // ← Important (cookies ke liye)
        redirect: 'follow'
      });

      const response = await fetch(request);
      
      console.log(`[SW] Replay ${item.url} → Status: ${response.status}`);

      if (response && (response.ok || response.status === 200)) {
        await deleteQueuedRequest(item.id);
        console.log('[SW] Successfully replayed and deleted from queue');
      }
    } catch (err) {
      console.error('[SW] Replay failed for', item.url, err);
    }
  }
}

self.addEventListener('sync', event => {
  if (event.tag === 'sync-offline-requests') {
    event.waitUntil(replayQueuedRequests());
  }
});

self.addEventListener('message', event => {
  if (event.data === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  if (event.data === 'SYNC_OFFLINE') {
    event.waitUntil(replayQueuedRequests());
  }
});

// ─── Strategy helpers ───────────────────────────────────────────────────────

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

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request)
    .then(response => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  // Return cached immediately, revalidate in background
  if (cached) {
    fetchPromise; // kick off background refresh
    return cached;
  }

  // No cache — wait for network
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
// ─── Message from client → force activate ───────────────────────────────────
self.addEventListener('message', event => {
    if (event.data === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});