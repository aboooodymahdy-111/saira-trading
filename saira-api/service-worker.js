/*
 * service-worker.js — Saira Terminal PWA (المرحلة 5).
 *
 * يخزّن الصدفة الثابتة فقط (HTML/مكتبة الشارت/الأيقونات) عشان يفتح التطبيق
 * بسرعة من الشاشة الرئيسية — لا يخزّن أي استجابة من /candles أو /gann/* أو
 * غيرها من نقاط نهاية الـ API. هذا مقصود: البيانات كلها حية من خادم محلي
 * (127.0.0.1:8787 أو نطاق حقيقي بعد النشر العام)، وتخزينها offline يعني
 * عرض شموع/مؤشرات قديمة بصمت بدل رسالة واضحة إن الخادم غير متاح — وهو عكس
 * مبدأ المشروع الأساسي ("fail loud, don't let stale data silently mean
 * something"). الشارت نفسه يتعامل مع فقد الاتصال بالفعل (setSrv(false) في
 * saira-terminal.html) فلا داعي لطبقة تخزين مضلِّلة هنا.
 */
const CACHE_NAME = "saira-shell-v1";
const SHELL_ASSETS = [
  "./saira-terminal.html",
  "./lightweight-charts.standalone.production.js",
  "./manifest.webmanifest",
  "./icons/icon-32.png",
  "./icons/icon-128.png",
  "./icons/icon-256.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // فقط أصول الصدفة الثابتة من نفس الأصل — أي شيء آخر (خاصة نداءات
  // 127.0.0.1:8787 أو أي API) يمر مباشرة للشبكة بلا تدخل من الكاش.
  const isShellAsset = SHELL_ASSETS.some((path) => url.pathname.endsWith(path.replace("./", "/")));
  if (!isShellAsset || event.request.method !== "GET") return;

  event.respondWith(
    caches.match(event.request).then((cached) =>
      cached || fetch(event.request).then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      })
    )
  );
});
