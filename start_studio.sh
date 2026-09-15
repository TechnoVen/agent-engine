#!/bin/bash

# --- COLOR PROMPTS FOR LOGGER UTILITIES ---
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}==================================================${NC}"
echo -e "${CYAN}   🚀 INITIALIZING SECURE AGENT DEVELOPMENT CONSOLE  ${NC}"
echo -e "${CYAN}==================================================${NC}"

set -e

# 1. Parse Context Dynamic Arguments (Default to 4096 if unassigned)
CONTEXT_SIZE=${1:-4096}
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$PROJECT_DIR/logs"

echo -e "${GREEN}🎯 Target Workspace KV Cache Limit: ${CONTEXT_SIZE} Tokens${NC}"

# 2. Verify Virtual Environment Status
PYTHON_BIN="python"
if [ -d "$PROJECT_DIR/.venv" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
fi

# Track child PIDs explicitly started by this launcher
PID_OLLAMA=""
PID_LLAMA=""
PID_WATCHER=""
PID_SIDECAR=""
PID_DESKTOP=""
CLEANED_UP=0

# --- CLEAN TEARDOWN HANDLER (F14 Remediation) ---
# Install trap BEFORE launching child processes to ensure cleanup is reachable.
cleanup() {
    if [ "$CLEANED_UP" -eq 1 ]; then
        return
    fi
    CLEANED_UP=1
    echo -e "\n${YELLOW}🛑 Intercepted shutdown signal. Safely terminating background processes...${NC}"
    if [ -n "$PID_SIDECAR" ] && kill -0 "$PID_SIDECAR" 2>/dev/null; then
        kill "$PID_SIDECAR" 2>/dev/null || true
    fi
    if [ -n "$PID_WATCHER" ] && kill -0 "$PID_WATCHER" 2>/dev/null; then
        kill "$PID_WATCHER" 2>/dev/null || true
    fi
    if [ -n "$PID_LLAMA" ] && kill -0 "$PID_LLAMA" 2>/dev/null; then
        kill "$PID_LLAMA" 2>/dev/null || true
    fi
    if [ -n "$PID_OLLAMA" ] && kill -0 "$PID_OLLAMA" 2>/dev/null; then
        kill "$PID_OLLAMA" 2>/dev/null || true
    fi
    if [ -n "$PID_DESKTOP" ] && kill -0 "$PID_DESKTOP" 2>/dev/null; then
        kill "$PID_DESKTOP" 2>/dev/null || true
    fi
    echo -e "${GREEN}✨ Workspace cleaned successfully. All supervised engines offline.${NC}"
}

# Trap termination intercept triggers to clean up ports securely
trap cleanup SIGINT SIGTERM EXIT

# 3. Start Local Inference Daemons (Ollama & llama-server) if not already running
export OLLAMA_IGPU_ENABLE=1
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_NUM_CTX="$CONTEXT_SIZE"

if ! curl -s http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
    echo -e "${GREEN}🖥️  Starting background Ollama daemon with AMD Radeon Vega iGPU support...${NC}"
    nohup "$PROJECT_DIR/start_ollama.sh" > "$PROJECT_DIR/logs/ollama.log" 2>&1 &
    PID_OLLAMA=$!
    sleep 2
else
    echo -e "${YELLOW}ℹ Local Ollama daemon is already active on port 11434.${NC}"
fi

if ! curl -s http://127.0.0.1:8080/v1/models > /dev/null 2>&1; then
    echo -e "${GREEN}⚡ Starting background llama-server on port 8080...${NC}"
    nohup "$PROJECT_DIR/start_llama_server.sh" "$CONTEXT_SIZE" 8080 > "$PROJECT_DIR/logs/llama_server.log" 2>&1 &
    PID_LLAMA=$!
    sleep 2
else
    echo -e "${YELLOW}ℹ Local llama-server is already active on port 8080.${NC}"
fi

# 4. Launch System Code Guard Daemons
echo -e "${GREEN}🛰️  Activating Sentry Watcher File Daemon...${NC}"
"$PYTHON_BIN" -m server.watcher > "$PROJECT_DIR/logs/watcher.log" 2>&1 &
PID_WATCHER=$!

# 5. Launch FastAPI Sidecar Backend (Supervised without exec replacement)
echo -e "${GREEN}🔌 Starting FastAPI Sidecar Backend on port 8000...${NC}"
"$PYTHON_BIN" -m services.python.server.api --host 127.0.0.1 --port 8000 > "$PROJECT_DIR/logs/sidecar.log" 2>&1 &
PID_SIDECAR=$!

echo -e "\n${GREEN}==================================================${NC}"
echo -e "${GREEN}   ✨ AGENT ENGINE STUDIO SUPERVISOR ACTIVE      ${NC}"
echo -e "${GREEN}==================================================${NC}"
echo -e "${CYAN}• FastAPI Sidecar:       http://127.0.0.1:8000${NC}"
echo -e "${CYAN}• Official Tauri UI:     make desktop-tauri-dev${NC}"
echo -e "${CYAN}• Internal Dev Tool:     make dev-dashboard${NC}"
echo -e "${YELLOW}Press [Ctrl+C] at any time to cleanly stop all engines.${NC}\n"

# Supervise child processes without replacing shell via exec
wait "$PID_SIDECAR"
