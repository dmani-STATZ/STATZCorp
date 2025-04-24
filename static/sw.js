// Service Worker for STATZ Corporation PWA - No Offline Support
const CACHE_NAME = 'statz-cache-v1';

// Assets to cache for performance improvements only (not offline)
const STATIC_ASSETS = [
    '/static/css/dist/styles.css',
    '/static/images/StatzCorpColorFINAL.png',
    '/static/favicon/favicon.ico',
    // Icon files
    '/static/images/icons/icon-72x72.png',
    '/static/images/icons/icon-96x96.png',
    '/static/images/icons/icon-128x128.png',
    '/static/images/icons/icon-144x144.png',
    '/static/images/icons/icon-152x152.png',
    '/static/images/icons/icon-192x192.png',
    '/static/images/icons/icon-384x384.png',
    '/static/images/icons/icon-512x512.png',
    // Splash screen files
    '/static/images/icons/splash/splash-414x896.png',
    '/static/images/icons/splash/splash-768x1024.png',
    '/static/images/icons/splash/splash-896x414.png',
    '/static/images/icons/splash/splash-1024x768.png',
    '/static/images/icons/splash/splash-1366x768.png',
    '/static/images/icons/splash/splash-1920x1080.png',
    '/static/images/icons/splash/splash-2560x1440.png',
    '/static/images/icons/splash/splash-3840x2160.png'
];

// Installation event - cache only static assets for performance
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Opened cache for static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activation event - clean up old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.filter(cacheName => {
                    return cacheName !== CACHE_NAME;
                }).map(cacheName => {
                    return caches.delete(cacheName);
                })
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch event - Cache-then-network strategy only for static assets
// All other requests go straight to the network (no offline support)
self.addEventListener('fetch', event => {
    // Skip non-GET requests and browser extension requests
    if (event.request.method !== 'GET' || event.request.url.startsWith('chrome-extension://')) {
        return;
    }

    // Only apply caching for static assets
    const url = new URL(event.request.url);
    const isStaticAsset = STATIC_ASSETS.some(asset => url.pathname.endsWith(asset)) || 
                         url.pathname.startsWith('/static/');

    if (isStaticAsset) {
        // For static assets, use cache-first strategy
        event.respondWith(
            caches.match(event.request)
                .then(cachedResponse => {
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    return fetch(event.request)
                        .then(response => {
                            // Don't cache if response is not valid
                            if (!response || response.status !== 200 || response.type !== 'basic') {
                                return response;
                            }
                            
                            // IMPORTANT: Clone the response
                            const responseToCache = response.clone();
                            
                            caches.open(CACHE_NAME)
                                .then(cache => {
                                    cache.put(event.request, responseToCache);
                                });
                                
                            return response;
                        });
                })
        );
    } else {
        // For all other requests (API calls, pages, etc.), go straight to network
        // No attempt to serve offline content, since the app requires database connection
        return;
    }
}); 