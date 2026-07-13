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

fn spawn_backend(resource_dir: &std::path::Path) -> Option<Child> {
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
