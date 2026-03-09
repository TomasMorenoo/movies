// Un Service Worker básico que permite la instalación de la PWA
self.addEventListener('install', (e) => {
    console.log('[Mobatai Vault] Service Worker Instalado');
});

self.addEventListener('fetch', (e) => {
    // Por ahora no cacheamos nada offline, solo dejamos pasar la petición
});