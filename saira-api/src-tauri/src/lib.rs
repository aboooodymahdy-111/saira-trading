use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

// المرحلة 3 (Tauri): يشغّل خادم FastAPI المحلي كعملية فرعية عند إقلاع
// التطبيق بدل الاعتماد على تشغيل يدوي لـ run.bat أولًا — نفس أمر run.bat
// (uvicorn app.main:app على 127.0.0.1:8787) لكن مُدار من التطبيق نفسه
// ومُنهى تلقائيًا عند إغلاقه (Drop impl أدناه).
struct BackendProcess(Mutex<Option<Child>>);

impl Drop for BackendProcess {
    fn drop(&mut self) {
        if let Ok(mut guard) = self.0.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
            }
        }
    }
}

// المشروع الرئيسي (C:\Users\...\Saira-Trading\src) فيه أدوات جان الحقيقية
// (gann_increment_selection.py، full_universe_analysis.py، إلخ) التي
// app/config.py's PROJECT_ROOT يفترض وجودها بمسار نسبي (API_ROOT.parent /
// "src") — صحيح فقط عند التشغيل من داخل saira-api/ الأصلي مباشرة، وليس من
// موارد Tauri المنسوخة (src-tauri/target/.../resources)، حيث src/ غير
// منسوخة أصلًا. بدل نسخ كل المشروع الرئيسي داخل حزمة التطبيق (يضاعف الحجم
// ويحتاج إعادة بناء يدوية عند أي تحديث)، نمرّر SAIRA_ROOT كمتغير بيئة
// يشير مباشرة لمكانه الحقيقي على القرص — قابل للتخصيص عبر
// SAIRA_ROOT_OVERRIDE لو المستخدم ثبّت المشروع في مكان مختلف عن الافتراضي.
fn find_project_src_dir() -> Option<std::path::PathBuf> {
    if let Ok(over) = std::env::var("SAIRA_ROOT_OVERRIDE") {
        let p = std::path::PathBuf::from(over);
        if p.join("full_universe_analysis.py").exists() {
            return Some(p);
        }
    }
    if let Some(home) = dirs_next_home() {
        let candidate = home.join("Saira-Trading").join("src");
        if candidate.join("full_universe_analysis.py").exists() {
            return Some(candidate);
        }
    }
    None
}

fn dirs_next_home() -> Option<std::path::PathBuf> {
    std::env::var_os("USERPROFILE").map(std::path::PathBuf::from)
}

fn spawn_backend(resource_dir: &std::path::Path) -> Option<Child> {
    let project_src = find_project_src_dir();
    if project_src.is_none() {
        log::warn!("لم يُعثر على مجلد src/ الحقيقي للمشروع — أدوات المعايرة \
                     الحقيقية وربط اللجنة الحية لن تعمل، لكن باقي الميزات \
                     (الشموع/المؤشرات/الفلك المستقل) ستعمل عاديًا. اضبط \
                     SAIRA_ROOT_OVERRIDE لو المشروع في مكان غير معتاد.");
    }

    // "python" العادي أولًا (يفترض pip install -r requirements.txt سبق
    // تنفيذه مرة على جهاز المستخدم — راجع resources/run.bat)، مع py -3
    // كبديل على ويندوز لو "python" مش على PATH مباشرة.
    for cmd in ["python", "py"] {
        let mut command = Command::new(cmd);
        if cmd == "py" {
            command.arg("-3");
        }
        command
            .args(["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8787"])
            .current_dir(resource_dir);
        if let Some(ref src) = project_src {
            command.env("SAIRA_ROOT", src);
            // كاش الفلترة الأخلاقية الحقيقي (runs/ticker_eligibility_cache.json)
            // نفس مشكلة SAIRA_ROOT بالضبط: config.py's ELIGIBILITY_CACHE_PATH
            // مسار نسبي (API_ROOT.parent / "runs") لا يصل لمجلد runs/ الحقيقي
            // من داخل موارد Tauri — src/ الأب هو Saira-Trading نفسه فنشتق
            // runs/ منه مباشرة (project_src = Saira-Trading/src).
            if let Some(project_root) = src.parent() {
                command.env("SAIRA_ELIGIBILITY_CACHE",
                           project_root.join("runs").join("ticker_eligibility_cache.json"));
            }
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            command.creation_flags(CREATE_NO_WINDOW);
        }
        if let Ok(child) = command.spawn() {
            return Some(child);
        }
    }
    None
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      let resource_dir = app.path().resource_dir()?;
      let child = spawn_backend(&resource_dir);
      if child.is_none() {
        log::warn!("Could not start the Python backend automatically — \
                     start it manually via run.bat, then reload the window.");
      }
      app.manage(BackendProcess(Mutex::new(child)));
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
