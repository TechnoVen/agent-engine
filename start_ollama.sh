#!/bin/bash

# Ensure igpu is available on Arch Linux / Manjaro
if command -v modprobe &> /dev/null; then
    sudo modprobe i915
fi

# Set environment for Intel Integrated GPU support
export OLLAMA_IGPU_ENABLE=1
export OLLAMA_HOST=127.0.0.1:11434

# Use bash to execute to ensure clean signal handling
exec /home/nadir/.local/bin/ollama serve
