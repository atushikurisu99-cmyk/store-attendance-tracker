// 最小限のService Worker。PWAとして認識させる(=ホーム画面追加でstandalone/
// 横固定表示を有効にする)ことが目的で、オフラインキャッシュ機能は持たせていない。
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // そのままネットワークに委譲(キャッシュ制御は今回のスコープ外)
  event.respondWith(fetch(event.request));
});
