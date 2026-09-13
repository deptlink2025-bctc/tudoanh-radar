/* Service worker: nhận Web Push + ép tải lại tài nguyên (chép từ kingstock/static/sw.js).
   Không cache offline — dữ liệu đổi mỗi ngày, cache cũ nguy hiểm hơn là không có. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.mode === "navigate" || /\.(js|css|webmanifest|json)$/.test(url.pathname)) {
    e.respondWith(fetch(new Request(e.request, { cache: "reload" })).catch(() => fetch(e.request)));
  }
});

self.addEventListener("push", (e) => {
  let p = {};
  try { p = e.data ? e.data.json() : {}; } catch (_) { p = { title: "TuDoanh Radar", body: e.data && e.data.text() }; }
  const opts = {
    body: p.body || "",
    icon: "icons/icon-192.png",
    badge: "icons/icon-192.png",
    tag: p.tag || "td",
    renotify: true,
    requireInteraction: !!p.hot,
    vibrate: p.hot ? [300, 100, 300, 100, 600] : [200, 100, 200],
    data: { url: p.url || "./" },
  };
  e.waitUntil(self.registration.showNotification(p.title || "TuDoanh Radar", opts));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = new URL(e.notification.data && e.notification.data.url || "./", self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const c of list) { if ("focus" in c) { c.navigate(target); return c.focus(); } }
    return self.clients.openWindow(target);
  }));
});
