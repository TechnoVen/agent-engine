#!/bin/bash

# --- COLOR PROMPTS FOR LOGGER UTILITIES ---
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${CYAN}==================================================${NC}"
echo -e "${CYAN}   🚀 INITIALIZING SECURE AGENT DEVELOPMENT CONSOLE  ${NC}"
echo -e "${CYAN}==================================================${NC}"

set -e

# 1. Parse Context Dynamic Arguments (Default to 4096 if unassigned)
CONTEXT_SIZE=${1:-4096}
PROJECT_DIR="/home/nadir/agent_engine"
mkdir -p "$PROJECT_DIR/logs"

echo -e "${GREEN}🎯 Target Workspace KV Cache Limit: ${CONTEXT_SIZE} Tokens${NC}"

# 2. Verify Virtual Environment Status
if [ -d "$PROJECT_DIR/.venv" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

# 3. Start Local Inference Daemons (Ollama & llama-server)
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
python -m server.watcher > "$PROJECT_DIR/logs/watcher.log" 2>&1 &
PID_WATCHER=$!

# 5. Launch Streamlit UI Dashboard Interface Panel Control Core
echo -e "${GREEN}📊 Spinning up Streamlit Operations Center UI Panel...${NC}"
# Use exec to let Streamlit inherit cleaner tracking signal cycles inside the primary execution thread
exec "$PROJECT_DIR/.venv/bin/python" -m streamlit run "$PROJECT_DIR/server/dashboard.py" \
    --server.port 8501 \
    --server.headless true

# --- CLEAN TEARDOWN HANDLER ---
cleanup() {
    echo -e "\n${YELLOW}🛑 Intercepted shutdown signal. Safely terminating background agents...${NC}"
    if [ ! -z "$PID_OLLAMA" ]; then kill $PID_OLLAMA 2>/dev/null; fi
    if [ ! -z "$PID_LLAMA" ]; then kill $PID_LLAMA 2>/dev/null; fi
    kill $PID_WATCHER 2>/dev/null
    echo -e "${GREEN}✨ Workspace cleaned successfully. All engines offline.${NC}"
    exit 0
}

# Trap termination intercept triggers to clean up ports securely
trap cleanup SIGINT SIGTERM
