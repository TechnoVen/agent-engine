// apps/desktop/src-tauri/src/updater.rs
//! Client helpers and IPC representations for sidecar auto-update management (Task 2.4 - ADR-008).

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpdateStatus {
    pub current_version: String,
    pub channel: String,
    pub auto_check: bool,
    pub last_checked_at: Option<f64>,
    pub feed_url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SetChannelPayload {
    pub channel: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpdateCheckPayload {
    pub channel: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpdateCheckResult {
    pub update_available: bool,
    pub current_version: String,
    pub latest_version: String,
    pub channel: String,
    pub release_notes: String,
    pub pub_date: Option<String>,
    pub download_url: Option<String>,
    pub signature: Option<String>,
    pub sha256: Option<String>,
}

pub struct UpdateClient {
    client: reqwest::Client,
    base_url: String,
}

impl UpdateClient {
    pub fn new(port: u16) -> Self {
        Self {
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(10))
                .build()
                .unwrap_or_default(),
            base_url: format!("http://127.0.0.1:{}", port),
        }
    }

    pub async fn get_status(&self) -> Result<UpdateStatus, String> {
        let url = format!("{}/v1/updater/status", self.base_url);
        let res = self
            .client
            .get(&url)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !res.status().is_success() {
            return Err(format!("Sidecar returned error status: {}", res.status()));
        }
        res.json::<UpdateStatus>().await.map_err(|e| e.to_string())
    }

    pub async fn set_channel(&self, channel: String) -> Result<UpdateStatus, String> {
        let url = format!("{}/v1/updater/channel", self.base_url);
        let payload = SetChannelPayload { channel };
        let res = self
            .client
            .post(&url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !res.status().is_success() {
            return Err(format!("Sidecar returned error status: {}", res.status()));
        }
        res.json::<UpdateStatus>().await.map_err(|e| e.to_string())
    }

    pub async fn check_for_updates(
        &self,
        channel: Option<String>,
    ) -> Result<UpdateCheckResult, String> {
        let url = format!("{}/v1/updater/check", self.base_url);
        let payload = UpdateCheckPayload { channel };
        let res = self
            .client
            .post(&url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !res.status().is_success() {
            return Err(format!("Sidecar returned error status: {}", res.status()));
        }
        res.json::<UpdateCheckResult>()
            .await
            .map_err(|e| e.to_string())
    }
}
