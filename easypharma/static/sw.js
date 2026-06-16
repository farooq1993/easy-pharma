/**
 * Easy Pharma — Service Worker
 * Provides offline support with a three-tier caching strategy:
 *   1. STATIC  — Cache-First  : CSS, JS, fonts, images (long-lived)
 *   2. PAGES   — Stale-While-Revalidate : HTML pages visited by the user
 *   3. API     — Network-First (3 s timeout) : JSON API calls for live data
 *
 * IMPORTANT: POS billing and purchase entry always use the network.
 * If the network is unavailable for those actions an offline notice is shown.
 */

const SW_VERSION   = 'v1.0.0';
const CACHE_STATIC = `ep-static-${SW_VERSION}`;
const CACHE_PAGES  = `ep-pages-${SW_VERSION}`;
const CACHE_API    = `ep-api-${SW_VERSION}`;

// Static assets to pre-cache on install
const PRECACHE_ASSETS = [
  '/static/css/global.css',
  '/static/css/customecss/sidebar.css',
  '/static/img/pwa-icon-192.png',
  '/static/img/pwa-icon-512.png',
  '/offline/',
];

// URLs whose responses should always come from the network (write operations)
const NETWORK_ONLY_PATTERNS = [
  /\/pos\/?$/,
  /\/purchase\/entry/,
  /\/accounts\//,
  /\/admin\//,
  /\/api\/save/,
  /\/api\/complete/,
  /\/api\/purchase/,
];

// URLs that are pure static assets (Cache-First)
const STATIC_PATTERNS = [
  /\/static\//,
  /fonts\.googleapis\.com/,
  /fonts\.gstatic\.com/,
  /cdn\.jsdelivr\.net/,
  /cdnjs\.cloudflare\.com/,
];

// API patterns (Network-First with timeout)
const API_PATTERNS = [
  /\/api\//,
];

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

  // Only handle GET requests
  if (request.method !== 'GET') return;

  // Ignore chrome-extension etc.
  if (!['http:', 'https:'].includes(url.protocol)) return;

  // 1. Network-Only for write/auth pages
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

  // 3. Network-First (with timeout) for API calls
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
