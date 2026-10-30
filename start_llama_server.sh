#!/bin/bash
# ==============================================================================
# Standalone llama-server launcher for Agent Engine
# Usage: ./start_llama_server.sh [context_size] [port] (default: 4096, 8080)
# ==============================================================================

set -e

CONTEXT_SIZE=${1:-4096}
PORT=${2:-8080}

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MODEL_PATH="${AGENT_ENGINE_MODEL_PATH:-$PROJECT_DIR/models/qwen2.5-coder-3b-instruct-q4_k_m.gguf}"

SERVER_BIN="${LLAMA_SERVER_BIN:-}"

if [ -z "$SERVER_BIN" ]; then
    SERVER_BIN="$(command -v llama-server 2>/dev/null || true)"
fi

if [ -z "$SERVER_BIN" ] && [ -x "$HOME/.local/lib/ollama/llama-server" ]; then
    SERVER_BIN="$HOME/.local/lib/ollama/llama-server"
fi

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
