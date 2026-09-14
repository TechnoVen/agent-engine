#!/bin/bash

# Ensure igpu is available on Arch Linux / Manjaro
if command -v modprobe &> /dev/null; then
    sudo modprobe i915
fi

# Set environment for Intel Integrated GPU support
export OLLAMA_IGPU_ENABLE=1
export OLLAMA_HOST=127.0.0.1:11434

# Use bash to execute to ensure clean signal handling
OLLAMA_BIN="${OLLAMA_BIN:-$(command -v ollama 2>/dev/null || true)}"

if [ -z "$OLLAMA_BIN" ]; then
    echo "Error: ollama executable not found in PATH." >&2
    exit 1
fi

exec "$OLLAMA_BIN" serve
