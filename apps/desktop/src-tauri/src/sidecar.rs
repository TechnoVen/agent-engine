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

    /// Start the bundled sidecar process with health polling.
    pub async fn start(&self) -> Result<SidecarStatus, String> {
        let mut child_guard = self.child.lock().await;

        // If child is already running, check its health
        if self.is_running() && child_guard.is_some() {
            return Ok(self.check_health().await);
        }

        let binary_path = Self::locate_sidecar_binary()
            .ok_or_else(|| "Could not locate sidecar binary in binaries/ directory".to_string())?;

        // Zero-Trust binary integrity verification (ADR-008)
        self.verify_binary_integrity(&binary_path)?;

        let mut cmd = tokio::process::Command::new(&binary_path);
        cmd.arg("--port")
            .arg(self.port.to_string())
            .arg("--host")
            .arg("127.0.0.1");

        // Forward environment
        cmd.env("PORT", self.port.to_string());
        cmd.env("AGENT_ENGINE_PORT", self.port.to_string());

        let spawned = cmd
            .spawn()
            .map_err(|e| format!("Failed to spawn sidecar process: {e}"))?;

        if let Some(id) = spawned.id() {
            self.pid.store(id, Ordering::SeqCst);
        }

        *child_guard = Some(spawned);
        let mut path_guard = self.resolved_path.lock().await;
        *path_guard = Some(binary_path);

        // Poll health endpoint with backoff (up to 5 seconds)
        for _ in 0..10 {
            tokio::time::sleep(Duration::from_millis(500)).await;
            let status = self.check_health().await;
            if status.is_running {
                return Ok(status);
            }
        }

        Ok(self.check_health().await)
    }

    /// Gracefully stop the sidecar child process.
    pub async fn stop(&self) -> Result<(), String> {
        let mut child_guard = self.child.lock().await;
        if let Some(mut child) = child_guard.take() {
            let _ = child.kill().await;
        }
        self.running.store(false, Ordering::SeqCst);
        self.pid.store(0, Ordering::SeqCst);
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

        match client.get(&url).send().await {
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
                SidecarStatus {
                    is_running: false,
                    port: self.port,
                    pid: self.current_pid(),
                    status: "offline".to_string(),
                    version: None,
                    engine: None,
                    checksum_verified: self.checksum_verified.load(Ordering::SeqCst),
                    binary_path: bin_path_str,
                    error: Some(e.to_string()),
                }
            }
        }
    }
}
