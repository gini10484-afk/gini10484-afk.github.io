// 离线缓存：有网时永远先拿最新的（行情、页面都是），没网时用上一次存下的。
// 改了这个文件里的 VERSION，旧缓存会被清掉。
const VERSION = "v1";
const CACHE = "dingtou-" + VERSION;
const SHELL = ["/", "/strategy.js", "/fonts/manrope.woff2", "/manifest.webmanifest", "/icons/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("dingtou-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // 只管自己网站的文件
  if (url.pathname.startsWith("/nasdaq100-dca/")) return; // 旧的第一个站不归这里管
  const key = req.mode === "navigate" ? "/" : url.pathname; // 页面都存成同一份，查询参数不算
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(key, copy));
        }
        return res;
      })
      .catch(() => caches.match(key).then((hit) => hit || caches.match("/")))
  );
});
