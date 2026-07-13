// يزامن أصول الواجهة (saira-terminal.html وما يرافقه) إلى مجلد إخراج ثابت.
// يُستخدم من sync-www.js (أندرويد/Capacitor) ومن أمر بناء Cloudflare Pages
// (الوسيط الأول: اسم المجلد الوجهة، نسبةً لجذر saira-api). المصدر الوحيد
// الحقيقي يبقى saira-terminal.html، بلا نسخ يدوية تتفرّق مع الوقت.
const fs = require("fs");
const path = require("path");

const outName = process.argv[2] || "www";
const root = path.join(__dirname, "..");
const out = path.join(root, outName);

// نسخة Tauri (src-tauri/frontend) بلا PWA (لا manifest/service-worker/icons/ —
// أيقونات سطح المكتب تُدار عبر src-tauri/icons وtauri.conf.json's bundle.icon)
const isTauri = outName === "src-tauri/frontend";
if (!isTauri) fs.mkdirSync(path.join(out, "icons"), { recursive: true });
else fs.mkdirSync(out, { recursive: true });

const copies = [
  ["saira-terminal.html", "index.html"],
  ["lightweight-charts.standalone.production.js", "lightweight-charts.standalone.production.js"],
];
if (!isTauri) {
  copies.push(
    ["manifest.webmanifest", "manifest.webmanifest"],
    ["service-worker.js", "service-worker.js"],
  );
}
for (const [src, dst] of copies) {
  fs.copyFileSync(path.join(root, src), path.join(out, dst));
}
if (!isTauri) {
  for (const f of fs.readdirSync(path.join(root, "icons"))) {
    fs.copyFileSync(path.join(root, "icons", f), path.join(out, "icons", f));
  }
}
console.log(`${outName}/ synced from source assets.`);
