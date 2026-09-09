#!/bin/bash
# ==============================================================================
# Agent Engine Studio Unified Launcher
# Usage: ./start_studio.sh [context_size] (default: 4096)
# ==============================================================================

set -e

CONTEXT_SIZE=${1:-4096}
PROJECT_DIR="/home/nadir/agent_engine"
mkdir -p "$PROJECT_DIR/logs"

echo "⚡ Starting Autonomous Agent Engine Studio (Context Window: ${CONTEXT_SIZE} tokens)..."

# 1. Start Ollama daemon if not already running
export OLLAMA_IGPU_ENABLE=1
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_NUM_CTX="$CONTEXT_SIZE"

if ! curl -s http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
    echo "Starting background Ollama daemon with AMD Radeon Vega iGPU support..."
    nohup "$PROJECT_DIR/start_ollama.sh" > "$PROJECT_DIR/logs/ollama.log" 2>&1 &
    sleep 2
else
    echo "Local Ollama daemon is already active on port 11434."
fi

# 2. Launch Streamlit Control Center
echo "🚀 Launching Streamlit Control Center on http://localhost:8501..."
exec "$PROJECT_DIR/.venv/bin/python" -m streamlit run "$PROJECT_DIR/server/dashboard.py" \
    --server.port 8501 \
    --server.headless true
