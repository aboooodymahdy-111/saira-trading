use std::fs;
use std::path::Path;

// saira-terminal.html (جذر saira-api/) هو المصدر الوحيد الحقيقي للواجهة —
// frontend/index.html هنا مجرد نسخة يحتاجها Tauri (frontendDist لازم يكون
// مجلد منفصل عن src-tauri نفسه، وإلا يحاول تضمين target/ الخاص به في نفسه
// أثناء البناء ويفشل بقفل ملف ذاتي). هذه الدالة تُزامن النسخة تلقائيًا قبل
// كل بناء بدل الاعتماد على نسخ يدوي يفوت التحديثات.
fn sync_frontend_copy() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
    let frontend = Path::new(env!("CARGO_MANIFEST_DIR")).join("frontend");
    let _ = fs::create_dir_all(&frontend);

    let pairs = [
        ("saira-terminal.html", "index.html"),
        ("lightweight-charts.standalone.production.js",
         "lightweight-charts.standalone.production.js"),
    ];
    for (src_name, dst_name) in pairs {
        let src = root.join(src_name);
        let dst = frontend.join(dst_name);
        if src.exists() {
            fs::copy(&src, &dst).expect("failed to sync frontend asset for Tauri build");
            println!("cargo:rerun-if-changed={}", src.display());
        }
    }
}

fn main() {
  sync_frontend_copy();
  tauri_build::build()
}
