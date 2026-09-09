#!/bin/bash
export OLLAMA_IGPU_ENABLE=1
export OLLAMA_HOST=127.0.0.1:11434
exec /home/nadir/.local/bin/ollama serve
