#!/bin/bash
# ==============================================================================
# Standalone llama-server launcher for Agent Engine
# Usage: ./start_llama_server.sh [context_size] [port] (default: 4096, 8080)
# ==============================================================================

set -e

CONTEXT_SIZE=${1:-4096}
PORT=${2:-8080}
MODEL_PATH="/home/nadir/agent_engine/models/qwen2.5-coder-3b-instruct-q4_k_m.gguf"
SERVER_BIN="/home/nadir/.local/lib/ollama/llama-server"

echo "⚡ Starting standalone llama-server on port $PORT (Context: $CONTEXT_SIZE tokens)..."

if [ ! -f "$SERVER_BIN" ]; then
    echo "❌ Error: llama-server binary not found at $SERVER_BIN"
    exit 1
fi

if [ ! -f "$MODEL_PATH" ]; then
    echo "❌ Error: GGUF model not found at $MODEL_PATH"
    exit 1
fi

exec "$SERVER_BIN" \
    -m "$MODEL_PATH" \
    -c "$CONTEXT_SIZE" \
    --port "$PORT" \
    --host 127.0.0.1
