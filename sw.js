/* TEFAS Quant servis çalışanı: aylık rapor bildirimlerini gösterir. Önbellek tutmaz. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data?.text() || "" }; }
  event.waitUntil(self.registration.showNotification(data.title || "TEFAS Quant", {
    body: data.body || "",
    icon: "/tefas-quant/assets/img/logo-192.png",
    badge: "/tefas-quant/assets/img/logo-64.png",
    tag: data.tag || "tq-rapor",
    renotify: true,
    data: { url: data.url || "/tefas-quant/#/modelrapor" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/tefas-quant/";
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    const open = wins.find((c) => c.url.includes("/tefas-quant/"));
    if (open) return open.focus().then(() => open.navigate?.(url));
    return self.clients.openWindow(url);
  }));
});
