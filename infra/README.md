# Agent Engine Infrastructure & Packaging

This directory contains infrastructure, build, and packaging scripts for Agent Engine:
- `sidecar-build/`: PyInstaller / Nuitka bundling scripts per OS (macOS, Linux, Windows).
- `update-server/`: Update server configuration and manifest generators for Tauri updater.
- `k8s/`: Kubernetes manifests for cloud SaaS deployments.
- `terraform/`: Cloud provisioning definitions (PostgreSQL, object storage, networking).
- `grafana/`: Prometheus metric exporter dashboards and templates.
