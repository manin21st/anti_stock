const CACHE_NAME = 'anti-stock-v3';
const ASSETS = [
    '/',
    '/static/style.css',
    '/static/app.js',
    '/static/logo.png',
    '/static/modules/chart.js',
    '/static/modules/watchlist.js',
    '/static/modules/backtest.js',
    '/static/modules/journal.js',
    '/static/modules/checklist.js'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS);
        })
    );
});

self.addEventListener('fetch', (event) => {
    event.respondWith(
        caches.match(event.request).then((response) => {
            return response || fetch(event.request);
        })
    );
});
