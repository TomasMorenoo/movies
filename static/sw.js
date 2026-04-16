const CACHE_NAME = 'mobatai-vault-v2';

// Recursos a cachear en la instalación (shell de la app)
const STATIC_ASSETS = [
    '/dashboard/index',
    '/manifest.json',
    '/static/mbvault-192.png',
    '/static/mbvault-512.png',
    'https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js'
];

// Instalar: pre-cachear la shell
self.addEventListener('install', (event) => {
    console.log('[MobataiVault SW] Instalando v2...');
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(STATIC_ASSETS).catch((err) => {
                console.warn('[MobataiVault SW] Algunos assets no se cachearon:', err);
            });
        }).then(() => self.skipWaiting())
    );
});

// Activar: limpiar caches viejas
self.addEventListener('activate', (event) => {
    console.log('[MobataiVault SW] Activando, limpiando caché vieja...');
    event.waitUntil(
        caches.keys().then((keyList) => {
            return Promise.all(
                keyList.map((key) => {
                    if (key !== CACHE_NAME) {
                        console.log('[MobataiVault SW] Borrando caché vieja:', key);
                        return caches.delete(key);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch: estrategia mixta
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // 1. Peticiones POST y rutas sensibles → siempre red (nunca cachear)
    if (event.request.method !== 'GET') return;
    if (url.pathname.includes('/dashboard/save') ||
        url.pathname.includes('/dashboard/delete') ||
        url.pathname.includes('/dashboard/oracle') ||
        url.pathname.includes('/dashboard/export') ||
        url.pathname.includes('/login') ||
        url.pathname.includes('/register') ||
        url.pathname.includes('/logout')) {
        return;
    }

    // 2. Imágenes de TMDB → Cache First
    if (url.hostname === 'image.tmdb.org') {
        event.respondWith(
            caches.open(CACHE_NAME).then((cache) => {
                return cache.match(event.request).then((cached) => {
                    if (cached) return cached;
                    return fetch(event.request).then((response) => {
                        if (response.ok) cache.put(event.request, response.clone());
                        return response;
                    }).catch(() => cached);
                });
            })
        );
        return;
    }

    // 3. CDN (Bootstrap, Fonts) → Cache First
    if (url.hostname.includes('jsdelivr.net') ||
        url.hostname.includes('fonts.googleapis.com') ||
        url.hostname.includes('fonts.gstatic.com')) {
        event.respondWith(
            caches.open(CACHE_NAME).then((cache) => {
                return cache.match(event.request).then((cached) => {
                    if (cached) return cached;
                    return fetch(event.request).then((response) => {
                        if (response.ok) cache.put(event.request, response.clone());
                        return response;
                    });
                });
            })
        );
        return;
    }

    // 4. Páginas propias → Network First con fallback a caché
    if (url.origin === self.location.origin) {
        event.respondWith(
            fetch(event.request)
                .then((response) => {
                    if (response.ok) {
                        const responseClone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(event.request, responseClone);
                        });
                    }
                    return response;
                })
                .catch(() => {
                    return caches.match(event.request).then((cached) => {
                        if (cached) return cached;
                        return caches.match('/dashboard/index');
                    });
                })
        );
        return;
    }
});
