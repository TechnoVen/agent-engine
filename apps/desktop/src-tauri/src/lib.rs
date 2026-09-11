pub mod credentials;
pub mod sidecar;

use credentials::{
    CredentialClient, CredentialInfo, SetCredentialPayload, TestCredentialPayload,
    TestCredentialResponse,
};
use sidecar::{SidecarStatus, SidecarSupervisor};
use std::sync::Arc;
use tauri::State;

#[tauri::command]
async fn get_sidecar_status(
    supervisor: State<'_, Arc<SidecarSupervisor>>,
) -> Result<SidecarStatus, String> {
    Ok(supervisor.check_health().await)
}

#[tauri::command]
async fn start_sidecar(
    supervisor: State<'_, Arc<SidecarSupervisor>>,
) -> Result<SidecarStatus, String> {
    supervisor.start().await
}

#[tauri::command]
async fn stop_sidecar(
    supervisor: State<'_, Arc<SidecarSupervisor>>,
) -> Result<(), String> {
    supervisor.stop().await
}

#[tauri::command]
async fn verify_sidecar_binary(
    supervisor: State<'_, Arc<SidecarSupervisor>>,
) -> Result<bool, String> {
    let path = SidecarSupervisor::locate_sidecar_binary()
        .ok_or_else(|| "Sidecar binary not found in binaries/ directory".to_string())?;
    supervisor.verify_binary_integrity(&path)
}

#[tauri::command]
fn get_app_version() -> &'static str {
    "0.1.0"
}

#[tauri::command]
async fn get_credentials(
    client: State<'_, Arc<CredentialClient>>,
    service: Option<String>,
) -> Result<Vec<CredentialInfo>, String> {
    client.list_credentials(service).await
}

#[tauri::command]
async fn set_credential(
    client: State<'_, Arc<CredentialClient>>,
    payload: SetCredentialPayload,
) -> Result<CredentialInfo, String> {
    client.set_credential(payload).await
}

#[tauri::command]
async fn delete_credential(
    client: State<'_, Arc<CredentialClient>>,
    service: String,
    key: String,
) -> Result<bool, String> {
    client.delete_credential(&service, &key).await
}

#[tauri::command]
async fn test_credential(
    client: State<'_, Arc<CredentialClient>>,
    payload: TestCredentialPayload,
) -> Result<TestCredentialResponse, String> {
    client.test_credential(payload).await
}

pub fn run() {
    let supervisor = Arc::new(SidecarSupervisor::new(8000));
    let cred_client = Arc::new(CredentialClient::new(8000));
    let shutdown_sup = Arc::clone(&supervisor);

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .manage(supervisor)
        .manage(cred_client)
        .invoke_handler(tauri::generate_handler![
            get_sidecar_status,
            start_sidecar,
            stop_sidecar,
            verify_sidecar_binary,
            get_app_version,
            get_credentials,
            set_credential,
            delete_credential,
            test_credential
        ])
        .build(tauri::generate_context!())
        .expect("error while building agent-engine-desktop")
        .run(move |_app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let sup = Arc::clone(&shutdown_sup);
                tauri::async_runtime::block_on(async move {
                    let _ = sup.stop().await;
                });
            }
        });
}

