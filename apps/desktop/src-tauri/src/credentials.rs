// apps/desktop/src-tauri/src/credentials.rs
//! Client helpers and IPC representations for sidecar credential storage (ADR-008).

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CredentialInfo {
    pub service: String,
    pub key: String,
    pub masked_value: String,
    pub backend: String,
    pub updated_at: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GetCredentialResponse {
    pub service: String,
    pub key: String,
    pub masked_value: String,
    pub backend: String,
    pub value: Option<String>,
    pub revealed: bool,
    pub updated_at: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SetCredentialPayload {
    pub service: String,
    pub key: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestCredentialPayload {
    pub provider: String,
    pub api_key: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestCredentialResponse {
    pub provider: String,
    pub valid: bool,
    pub latency_ms: f64,
    pub error: Option<String>,
}

pub struct CredentialClient {
    client: reqwest::Client,
    base_url: String,
}

impl CredentialClient {
    pub fn new(port: u16) -> Self {
        Self {
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(10))
                .build()
                .unwrap_or_default(),
            base_url: format!("http://127.0.0.1:{}", port),
        }
    }

    pub async fn list_credentials(
        &self,
        service: Option<String>,
    ) -> Result<Vec<CredentialInfo>, String> {
        let mut url = format!("{}/v1/credentials", self.base_url);
        if let Some(s) = service {
            url = format!("{}?service={}", url, s);
        }
        let res = self
            .client
            .get(&url)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !res.status().is_success() {
            return Err(format!("Sidecar returned error status: {}", res.status()));
        }
        res.json::<Vec<CredentialInfo>>()
            .await
            .map_err(|e| e.to_string())
    }

    pub async fn set_credential(
        &self,
        payload: SetCredentialPayload,
    ) -> Result<CredentialInfo, String> {
        let url = format!("{}/v1/credentials", self.base_url);
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
        res.json::<CredentialInfo>()
            .await
            .map_err(|e| e.to_string())
    }

    pub async fn get_credential(
        &self,
        service: &str,
        key: &str,
        reveal: bool,
    ) -> Result<GetCredentialResponse, String> {
        let url = format!(
            "{}/v1/credentials/{}/{}?reveal={}",
            self.base_url, service, key, reveal
        );
        let res = self
            .client
            .get(&url)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !res.status().is_success() {
            return Err(format!("Sidecar returned error status: {}", res.status()));
        }
        res.json::<GetCredentialResponse>()
            .await
            .map_err(|e| e.to_string())
    }

    pub async fn delete_credential(&self, service: &str, key: &str) -> Result<bool, String> {
        let url = format!("{}/v1/credentials/{}/{}", self.base_url, service, key);
        let res = self
            .client
            .delete(&url)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if res.status().as_u16() == 404 {
            return Ok(false);
        }
        if !res.status().is_success() {
            return Err(format!("Sidecar returned error status: {}", res.status()));
        }
        Ok(true)
    }

    pub async fn test_credential(
        &self,
        payload: TestCredentialPayload,
    ) -> Result<TestCredentialResponse, String> {
        let url = format!("{}/v1/credentials/test", self.base_url);
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
        res.json::<TestCredentialResponse>()
            .await
            .map_err(|e| e.to_string())
    }
}
