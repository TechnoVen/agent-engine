use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::process::Child;
use tokio::sync::Mutex;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub const CURRENT_TARGET_TRIPLE: &str = "x86_64-unknown-linux-gnu";
#[cfg(all(target_os = "linux", target_arch = "aarch64"))]
pub const CURRENT_TARGET_TRIPLE: &str = "aarch64-unknown-linux-gnu";
#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
pub const CURRENT_TARGET_TRIPLE: &str = "aarch64-apple-darwin";
#[cfg(all(target_os = "macos", target_arch = "x86_64"))]
pub const CURRENT_TARGET_TRIPLE: &str = "x86_64-apple-darwin";
#[cfg(all(target_os = "windows", target_arch = "x86_64"))]
pub const CURRENT_TARGET_TRIPLE: &str = "x86_64-pc-windows-msvc";

#[cfg(not(any(
    all(target_os = "linux", target_arch = "x86_64"),
    all(target_os = "linux", target_arch = "aarch64"),
    all(target_os = "macos", target_arch = "aarch64"),
    all(target_os = "macos", target_arch = "x86_64"),
    all(target_os = "windows", target_arch = "x86_64")
)))]
pub const CURRENT_TARGET_TRIPLE: &str = "unknown";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SidecarStatus {
    pub is_running: bool,
    pub port: u16,
    pub pid: Option<u32>,
    pub status: String,
    pub version: Option<String>,
    pub engine: Option<String>,
    pub checksum_verified: bool,
    pub binary_path: Option<String>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct HealthResponse {
    status: Option<String>,
    version: Option<String>,
    engine: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[allow(dead_code)]
struct SignedManifestPayload {
    manifest: Option<ManifestData>,
    signature: Option<String>,
    algorithm: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[allow(dead_code)]
struct ManifestData {
    name: Option<String>,
    version: Option<String>,
    target_triple: Option<String>,
    binary: Option<String>,
    sha256: Option<String>,
}

pub struct SidecarSupervisor {
    port: u16,
    running: Arc<AtomicBool>,
    pid: Arc<AtomicU32>,
    checksum_verified: Arc<AtomicBool>,
    resolved_path: Arc<Mutex<Option<PathBuf>>>,
    child: Arc<Mutex<Option<Child>>>,
    last_error: Arc<Mutex<Option<String>>>,
    owned: Arc<AtomicBool>,
}

impl SidecarSupervisor {
    pub fn new(port: u16) -> Self {
        Self {
            port,
            running: Arc::new(AtomicBool::new(false)),
            pid: Arc::new(AtomicU32::new(0)),
            checksum_verified: Arc::new(AtomicBool::new(false)),
            resolved_path: Arc::new(Mutex::new(None)),
            child: Arc::new(Mutex::new(None)),
            last_error: Arc::new(Mutex::new(None)),
            owned: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::SeqCst)
    }

    pub fn current_pid(&self) -> Option<u32> {
        let p = self.pid.load(Ordering::SeqCst);
        if p > 0 {
            Some(p)
        } else {
            None
        }
    }

    /// Retrieve the authoritative local IPC authentication token or securely initialize one.
    pub fn get_or_init_ipc_token() -> String {
        if let Ok(token) = std::env::var("AGENT_ENGINE_IPC_TOKEN") {
            let trimmed = token.trim();
            if !trimmed.is_empty() {
                return trimmed.to_string();
            }
        }

        let token_path = if let Ok(path_str) = std::env::var("AGENT_ENGINE_TOKEN_FILE") {
            PathBuf::from(path_str)
        } else {
            let home_dir = std::env::var("HOME")
                .or_else(|_| std::env::var("USERPROFILE"))
                .map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("."));
            home_dir.join(".agent_engine").join("ipc.token")
        };

        if token_path.is_file() {
            if let Ok(content) = std::fs::read_to_string(&token_path) {
                let trimmed = content.trim();
                if !trimmed.is_empty() {
                    std::env::set_var("AGENT_ENGINE_IPC_TOKEN", trimmed);
                    return trimmed.to_string();
                }
            }
        }

        let token = {
            let mut bytes = [0u8; 32];
            let mut filled = false;
            #[cfg(unix)]
            {
                use std::io::Read;
                if let Ok(mut f) = std::fs::File::open("/dev/urandom") {
                    if f.read_exact(&mut bytes).is_ok() {
                        filled = true;
                    }
                }
            }
            if !filled {
                let mut hasher = Sha256::new();
                hasher.update(&std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_nanos().to_le_bytes());
                hasher.update(&std::process::id().to_le_bytes());
                hasher.update(b"agent_engine_ipc_secure_entropy_seed");
                let result = hasher.finalize();
                bytes.copy_from_slice(&result);
            }
            let mut hex_str = String::with_capacity(64);
            for b in bytes {
                hex_str.push_str(&format!("{:02x}", b));
            }
            hex_str
        };

        if let Some(parent) = token_path.parent() {
            let _ = std::fs::create_dir_all(parent);
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o700));
            }
        }

        if std::fs::write(&token_path, &token).is_ok() {
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = std::fs::set_permissions(&token_path, std::fs::Permissions::from_mode(0o600));
            }
        }

        std::env::set_var("AGENT_ENGINE_IPC_TOKEN", &token);
        token
    }

    pub fn get_ipc_token() -> String {
        Self::get_or_init_ipc_token()
    }

    /// Compute SHA-256 hexadecimal checksum of a file on disk.
    pub fn compute_sha256(path: &Path) -> Result<String, String> {
        let mut file = std::fs::File::open(path).map_err(|e| format!("Failed to open file: {e}"))?;
        let mut hasher = Sha256::new();
        let mut buffer = [0u8; 65536];
        loop {
            let n = std::io::Read::read(&mut file, &mut buffer)
                .map_err(|e| format!("Read error: {e}"))?;
            if n == 0 {
                break;
            }
            hasher.update(&buffer[..n]);
        }
        let result = hasher.finalize();
        Ok(result.iter().map(|b| format!("{:02x}", b)).collect())
    }

    /// Locate the bundled sidecar binary across standard candidate locations.
    pub fn locate_sidecar_binary() -> Option<PathBuf> {
        let binary_name = format!("agent-engine-sidecar-{}", CURRENT_TARGET_TRIPLE);
        let binary_name_win = format!("agent-engine-sidecar-{}.exe", CURRENT_TARGET_TRIPLE);

        let candidates = vec![
            PathBuf::from("binaries").join(&binary_name),
            PathBuf::from("binaries").join(&binary_name_win),
            PathBuf::from("binaries").join("agent-engine-sidecar"),
            PathBuf::from("src-tauri/binaries").join(&binary_name),
            PathBuf::from("apps/desktop/src-tauri/binaries").join(&binary_name),
            PathBuf::from("../src-tauri/binaries").join(&binary_name),
        ];

        // Also check relative to the current executable directory
        if let Ok(exe_path) = std::env::current_exe() {
            if let Some(exe_dir) = exe_path.parent() {
                let p1 = exe_dir.join(&binary_name);
                if p1.is_file() {
                    return Some(p1);
                }
                let p2 = exe_dir.join("agent-engine-sidecar");
                if p2.is_file() {
                    return Some(p2);
                }
                let p3 = exe_dir.join("binaries").join(&binary_name);
                if p3.is_file() {
                    return Some(p3);
                }
            }
        }

        for candidate in candidates {
            if candidate.is_file() {
                return Some(candidate);
            }
        }

        None
    }

    /// Locate repository root by walking up from current directory or executable.
    pub fn find_repo_root() -> Option<PathBuf> {
        if let Ok(root) = std::env::var("AGENT_ENGINE_REPO_ROOT") {
            let p = PathBuf::from(root);
            if p.join("pyproject.toml").is_file() {
                return Some(p);
            }
        }

        let mut candidates = Vec::new();
        if let Ok(cwd) = std::env::current_dir() {
            candidates.push(cwd);
        }
        if let Ok(exe) = std::env::current_exe() {
            if let Some(parent) = exe.parent() {
                candidates.push(parent.to_path_buf());
            }
        }

        for start in candidates {
            let mut curr = Some(start.as_path());
            while let Some(dir) = curr {
                if dir.join("pyproject.toml").is_file()
                    && dir.join("services").join("python").is_dir()
                {
                    return Some(dir.to_path_buf());
                }
                curr = dir.parent();
            }
        }

        None
    }

    /// Resolve command to launch sidecar deterministically using project runtime environment.
    fn resolve_spawn_command(&self, token: &str) -> Result<tokio::process::Command, String> {
        if let Some(repo_root) = Self::find_repo_root() {
            let venv_python = if cfg!(windows) {
                repo_root.join(".venv").join("Scripts").join("python.exe")
            } else {
                repo_root.join(".venv").join("bin").join("python")
            };

            if venv_python.is_file() {
                let mut cmd = tokio::process::Command::new(&venv_python);
                cmd.arg("-m")
                    .arg("uvicorn")
                    .arg("services.python.server.app:create_app")
                    .arg("--factory")
                    .arg("--host")
                    .arg("127.0.0.1")
                    .arg("--port")
                    .arg(self.port.to_string());
                cmd.current_dir(&repo_root);

                // Deterministically isolate environment to the Agent Engine project .venv
                cmd.env("VIRTUAL_ENV", repo_root.join(".venv"));
                let bin_dir = if cfg!(windows) {
                    repo_root.join(".venv").join("Scripts")
                } else {
                    repo_root.join(".venv").join("bin")
                };
                let path = format!(
                    "{}:{}",
                    bin_dir.display(),
                    std::env::var("PATH").unwrap_or_default()
                );
                cmd.env("PATH", path);
                cmd.env("PYTHONPATH", &repo_root);
                cmd.env_remove("PYTHONHOME");
                cmd.env("AGENT_ENGINE_IPC_TOKEN", token);
                cmd.env("PORT", self.port.to_string());
                cmd.env("AGENT_ENGINE_PORT", self.port.to_string());
                cmd.env("AGENT_ENGINE_HOST", "127.0.0.1");
                return Ok(cmd);
            }

            // Fallback: Check if uv is available
            let uv_exists = std::process::Command::new("uv")
                .arg("--version")
                .output()
                .is_ok();
            if uv_exists {
                let mut cmd = tokio::process::Command::new("uv");
                cmd.arg("run")
                    .arg("--directory")
                    .arg(&repo_root)
                    .arg("uvicorn")
                    .arg("services.python.server.app:create_app")
                    .arg("--factory")
                    .arg("--host")
                    .arg("127.0.0.1")
                    .arg("--port")
                    .arg(self.port.to_string());
                cmd.current_dir(&repo_root);
                cmd.env_remove("VIRTUAL_ENV");
                cmd.env("AGENT_ENGINE_IPC_TOKEN", token);
                cmd.env("PORT", self.port.to_string());
                cmd.env("AGENT_ENGINE_PORT", self.port.to_string());
                cmd.env("AGENT_ENGINE_HOST", "127.0.0.1");
                return Ok(cmd);
            }

            // Fallback: Check if python3 is available
            let py3_exists = std::process::Command::new("python3")
                .arg("--version")
                .output()
                .is_ok();
            if py3_exists {
                let mut cmd = tokio::process::Command::new("python3");
                cmd.arg("-m")
                    .arg("uvicorn")
                    .arg("services.python.server.app:create_app")
                    .arg("--factory")
                    .arg("--host")
                    .arg("127.0.0.1")
                    .arg("--port")
                    .arg(self.port.to_string());
                cmd.current_dir(&repo_root);
                cmd.env("PYTHONPATH", &repo_root);
                cmd.env("AGENT_ENGINE_IPC_TOKEN", token);
                cmd.env("PORT", self.port.to_string());
                cmd.env("AGENT_ENGINE_PORT", self.port.to_string());
                cmd.env("AGENT_ENGINE_HOST", "127.0.0.1");
                return Ok(cmd);
            }
        }

        // Bundled binary fallback (production packaging)
        if let Some(binary_path) = Self::locate_sidecar_binary() {
            self.verify_binary_integrity(&binary_path)?;
            let mut cmd = tokio::process::Command::new(&binary_path);
            cmd.arg("--port")
                .arg(self.port.to_string())
                .arg("--host")
                .arg("127.0.0.1");
            cmd.env("PORT", self.port.to_string());
            cmd.env("AGENT_ENGINE_PORT", self.port.to_string());
            cmd.arg("--token").arg(&token);
            cmd.env("AGENT_ENGINE_IPC_TOKEN", &token);
            return Ok(cmd);
        }

        Err("executable not found: Python virtualenv (.venv/bin/python) or uv not found in repository root".to_string())
    }

    /// Verify the SHA-256 hash of the sidecar binary against manifest metadata (ADR-008).
    pub fn verify_binary_integrity(&self, binary_path: &Path) -> Result<bool, String> {
        // Allow bypass in development environments if explicitly set
        if std::env::var("AGENT_ENGINE_SKIP_VERIFY").unwrap_or_default() == "1" {
            self.checksum_verified.store(true, Ordering::SeqCst);
            return Ok(true);
        }

        let computed_hash = Self::compute_sha256(binary_path)?;
        let bin_dir = binary_path.parent().unwrap_or_else(|| Path::new("."));

        // Check manifest.signed.json first, then manifest.json
        let signed_manifest_path = bin_dir.join("manifest.signed.json");
        let plain_manifest_path = bin_dir.join("manifest.json");

        let expected_hash = if signed_manifest_path.is_file() {
            let data = std::fs::read_to_string(&signed_manifest_path)
                .map_err(|e| format!("Failed to read signed manifest: {e}"))?;
            let payload: SignedManifestPayload = serde_json::from_str(&data)
                .map_err(|e| format!("Invalid signed manifest format: {e}"))?;
            payload
                .manifest
                .and_then(|m| m.sha256)
                .ok_or_else(|| "Signed manifest missing sha256 field".to_string())?
        } else if plain_manifest_path.is_file() {
            let data = std::fs::read_to_string(&plain_manifest_path)
                .map_err(|e| format!("Failed to read manifest: {e}"))?;
            let manifest: ManifestData = serde_json::from_str(&data)
                .map_err(|e| format!("Invalid manifest format: {e}"))?;
            manifest
                .sha256
                .ok_or_else(|| "Manifest missing sha256 field".to_string())?
        } else {
            // Check SHA256SUMS file
            let sums_path = bin_dir.join("SHA256SUMS");
            if sums_path.is_file() {
                let sums_data = std::fs::read_to_string(&sums_path)
                    .map_err(|e| format!("Failed to read SHA256SUMS: {e}"))?;
                let file_name = binary_path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or_default();
                sums_data
                    .lines()
                    .find(|line| line.contains(file_name))
                    .and_then(|line| line.split_whitespace().next())
                    .map(|h| h.to_string())
                    .ok_or_else(|| format!("Binary {file_name} not found in SHA256SUMS"))?
            } else {
                return Err("No cryptographic manifest or SHA256SUMS file found for sidecar binary".to_string());
            }
        };

        if computed_hash.eq_ignore_ascii_case(&expected_hash) {
            self.checksum_verified.store(true, Ordering::SeqCst);
            Ok(true)
        } else {
            self.checksum_verified.store(false, Ordering::SeqCst);
            Err(format!(
                "Integrity check failed: expected hash {expected_hash}, got {computed_hash}"
            ))
        }
    }

    /// Start the sidecar process with canonical lifecycle and health polling.
    pub async fn start(&self) -> Result<SidecarStatus, String> {
        // 1. If healthy canonical sidecar already exists on configured port, attach safely
        let initial_status = self.check_health().await;
        if initial_status.is_running {
            println!(
                "[SidecarSupervisor] Attached safely to existing healthy canonical sidecar on port {}",
                self.port
            );
            self.owned.store(false, Ordering::SeqCst);
            *self.last_error.lock().await = None;
            return Ok(initial_status);
        }

        // 2. Check if port is already listening on TCP
        if tokio::net::TcpStream::connect(("127.0.0.1", self.port)).await.is_ok() {
            let url = format!("http://127.0.0.1:{}/healthz", self.port);
            let client = reqwest::Client::builder()
                .timeout(Duration::from_millis(1000))
                .build()
                .unwrap_or_default();
            if let Ok(resp) = client.get(&url).send().await {
                if resp.status().is_success() {
                    let err_msg = format!(
                        "token mismatch: sidecar running on port {} rejected IPC token with 401 Unauthorized",
                        self.port
                    );
                    *self.last_error.lock().await = Some(err_msg.clone());
                    return Err(err_msg);
                }
            }
            let err_msg = format!(
                "port conflict: port {} is already in use by another process",
                self.port
            );
            *self.last_error.lock().await = Some(err_msg.clone());
            return Err(err_msg);
        }

        // 3. Resolve executable command using deterministic runtime environment
        let token = Self::get_or_init_ipc_token();
        let mut cmd = match self.resolve_spawn_command(&token) {
            Ok(c) => c,
            Err(e) => {
                *self.last_error.lock().await = Some(e.clone());
                return Err(e);
            }
        };

        cmd.kill_on_drop(true);
        cmd.stderr(std::process::Stdio::piped());
        cmd.stdout(std::process::Stdio::inherit());

        let mut child_guard = self.child.lock().await;
        if self.is_running() && child_guard.is_some() {
            drop(child_guard);
            return Ok(self.check_health().await);
        }

        let mut spawned = cmd
            .spawn()
            .map_err(|e| {
                let err_msg = format!("executable not found: failed to spawn sidecar: {e}");
                err_msg
            })?;

        let pid_val = spawned.id().unwrap_or(0);
        self.pid.store(pid_val, Ordering::SeqCst);
        self.owned.store(true, Ordering::SeqCst);

        // Read stderr lines asynchronously into bounded buffer
        let child_stderr = spawned.stderr.take();
        let stderr_lines = Arc::new(tokio::sync::Mutex::new(Vec::<String>::new()));
        if let Some(stderr) = child_stderr {
            let lines_clone = Arc::clone(&stderr_lines);
            tokio::spawn(async move {
                use tokio::io::AsyncBufReadExt;
                let mut reader = tokio::io::BufReader::new(stderr).lines();
                while let Ok(Some(line)) = reader.next_line().await {
                    eprintln!("[sidecar] {}", line);
                    let mut guard = lines_clone.lock().await;
                    if guard.len() >= 50 {
                        guard.remove(0);
                    }
                    guard.push(line);
                }
            });
        }

        *child_guard = Some(spawned);
        drop(child_guard);

        // 4. Poll health endpoint with backoff (up to 10 seconds)
        let mut child_exit_code = None;
        for _ in 0..20 {
            tokio::time::sleep(Duration::from_millis(500)).await;

            // Check if child has exited prematurely
            {
                let mut guard = self.child.lock().await;
                if let Some(ch) = guard.as_mut() {
                    if let Ok(Some(exit_status)) = ch.try_wait() {
                        child_exit_code = Some(exit_status);
                        break;
                    }
                }
            }

            let status = self.check_health().await;
            if status.is_running {
                println!(
                    "[SidecarSupervisor] Python sidecar online on port {}: status={}",
                    self.port, status.status
                );
                *self.last_error.lock().await = None;
                return Ok(status);
            }
        }

        // Child process exited or failed to report healthy within timeout
        tokio::time::sleep(Duration::from_millis(100)).await;
        let captured_stderr = stderr_lines.lock().await.join("\n");

        if let Some(exit_status) = child_exit_code {
            let err_msg = if captured_stderr.contains("ModuleNotFoundError")
                || captured_stderr.contains("ImportError")
            {
                format!(
                    "module import failure: child exited with status {:?}: {}",
                    exit_status, captured_stderr
                )
            } else {
                format!(
                    "child exited: child exited with status {:?}: {}",
                    exit_status, captured_stderr
                )
            };
            *self.last_error.lock().await = Some(err_msg.clone());
            return Err(err_msg);
        }

        // Timed out while still running
        let err_msg = format!(
            "startup timeout: sidecar failed to become healthy on port {} within 10s. Stderr: {}",
            self.port, captured_stderr
        );
        *self.last_error.lock().await = Some(err_msg.clone());
        let _ = self.stop().await;
        Err(err_msg)
    }

    /// Gracefully stop the sidecar child process owned by this instance.
    pub async fn stop(&self) -> Result<(), String> {
        let is_owned = self.owned.load(Ordering::SeqCst);
        let mut child_guard = self.child.lock().await;
        if is_owned {
            if let Some(mut child) = child_guard.take() {
                println!(
                    "[SidecarSupervisor] Terminating owned sidecar process (PID {:?})",
                    child.id()
                );
                let _ = child.kill().await;
                let _ = child.wait().await;
            }
        } else {
            let _ = child_guard.take();
        }
        self.running.store(false, Ordering::SeqCst);
        self.pid.store(0, Ordering::SeqCst);
        self.owned.store(false, Ordering::SeqCst);
        Ok(())
    }

    /// Check health of the sidecar via HTTP endpoint.
    pub async fn check_health(&self) -> SidecarStatus {
        let url = format!("http://127.0.0.1:{}/v1/health", self.port);
        let client = reqwest::Client::builder()
            .timeout(Duration::from_millis(1500))
            .build()
            .unwrap_or_default();

        let bin_path_str = {
            let guard = self.resolved_path.lock().await;
            guard.as_ref().map(|p| p.to_string_lossy().to_string())
        };

        let token = Self::get_or_init_ipc_token();
        let mut req = client.get(&url);
        if !token.is_empty() {
            req = req.header("Authorization", format!("Bearer {token}"))
                     .header("X-IPC-Token", &token);
        }

        match req.send().await {
            Ok(resp) => {
                if resp.status().is_success() {
                    let health: Option<HealthResponse> = resp.json().await.ok();
                    self.running.store(true, Ordering::SeqCst);
                    SidecarStatus {
                        is_running: true,
                        port: self.port,
                        pid: self.current_pid(),
                        status: health
                            .as_ref()
                            .and_then(|h| h.status.clone())
                            .unwrap_or_else(|| "healthy".to_string()),
                        version: health.as_ref().and_then(|h| h.version.clone()),
                        engine: health.as_ref().and_then(|h| h.engine.clone()),
                        checksum_verified: self.checksum_verified.load(Ordering::SeqCst),
                        binary_path: bin_path_str,
                        error: None,
                    }
                } else if resp.status().as_u16() == 401 {
                    self.running.store(false, Ordering::SeqCst);
                    SidecarStatus {
                        is_running: false,
                        port: self.port,
                        pid: self.current_pid(),
                        status: "unauthorized".to_string(),
                        version: None,
                        engine: None,
                        checksum_verified: self.checksum_verified.load(Ordering::SeqCst),
                        binary_path: bin_path_str,
                        error: Some("HTTP 401 Unauthorized: token mismatch".to_string()),
                    }
                } else {
                    self.running.store(false, Ordering::SeqCst);
                    SidecarStatus {
                        is_running: false,
                        port: self.port,
                        pid: self.current_pid(),
                        status: "degraded".to_string(),
                        version: None,
                        engine: None,
                        checksum_verified: self.checksum_verified.load(Ordering::SeqCst),
                        binary_path: bin_path_str,
                        error: Some(format!("HTTP {}", resp.status())),
                    }
                }
            }
            Err(e) => {
                self.running.store(false, Ordering::SeqCst);
                let err_detail = self.last_error.lock().await.clone();
                SidecarStatus {
                    is_running: false,
                    port: self.port,
                    pid: self.current_pid(),
                    status: "offline".to_string(),
                    version: None,
                    engine: None,
                    checksum_verified: self.checksum_verified.load(Ordering::SeqCst),
                    binary_path: bin_path_str,
                    error: err_detail.or_else(|| Some(e.to_string())),
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_sidecar_supervisor_lifecycle() {
        let port = 8795;
        let supervisor = SidecarSupervisor::new(port);

        // Start supervisor
        let status = supervisor.start().await.expect("SidecarSupervisor failed to start");
        assert!(status.is_running, "Sidecar status must report is_running=true");
        assert_eq!(status.port, port);

        // Verify port listener
        assert!(
            tokio::net::TcpStream::connect(("127.0.0.1", port)).await.is_ok(),
            "Port {port} must accept TCP connections"
        );

        // Verify /healthz returns ok
        let client = reqwest::Client::new();
        let res_healthz = client
            .get(format!("http://127.0.0.1:{port}/healthz"))
            .send()
            .await
            .expect("healthz request failed");
        assert!(res_healthz.status().is_success(), "/healthz must return 200 OK");

        // Verify unauthenticated /v1/health returns 401
        let res_unauth = client
            .get(format!("http://127.0.0.1:{port}/v1/health"))
            .send()
            .await
            .expect("unauthenticated /v1/health request failed");
        assert_eq!(
            res_unauth.status().as_u16(),
            401,
            "Unauthenticated /v1/health must return 401 Unauthorized"
        );

        // Verify authenticated /v1/health with same IPC token returns 200
        let token = SidecarSupervisor::get_ipc_token();
        let res_auth = client
            .get(format!("http://127.0.0.1:{port}/v1/health"))
            .header("Authorization", format!("Bearer {token}"))
            .send()
            .await
            .expect("authenticated /v1/health request failed");
        assert!(
            res_auth.status().is_success(),
            "Authenticated /v1/health with matching token must return 200 OK"
        );

        // Gracefully shut down supervisor
        supervisor.stop().await.expect("Failed to stop supervisor");
        assert!(!supervisor.is_running(), "Supervisor must report is_running=false after stop()");

        // Verify child process is gone and port is closed
        tokio::time::sleep(Duration::from_millis(600)).await;
        assert!(
            tokio::net::TcpStream::connect(("127.0.0.1", port)).await.is_err(),
            "Port {port} must reject connections after supervisor shutdown"
        );
    }
}
