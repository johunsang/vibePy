#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_DIR="$ROOT/third_party/llama.cpp-src"
BIN="$LLAMA_DIR/build/bin/llama-server"

if [[ ! -d "$LLAMA_DIR/.git" ]]; then
  echo "llama.cpp not found at: $LLAMA_DIR" >&2
  echo "Clone with: git clone https://github.com/ggerganov/llama.cpp \"$LLAMA_DIR\"" >&2
  exit 1
fi

if [[ ! -x "$BIN" ]]; then
  echo "llama-server not found: $BIN" >&2
  echo "Build with: cmake -S $LLAMA_DIR -B $LLAMA_DIR/build && cmake --build $LLAMA_DIR/build -j" >&2
  exit 1
fi

MODEL_REPO="${GLM47_REPO:-AaryanK/GLM-4.7-Flash-GGUF:Q4_K_M}"
HOST="${GLM47_HOST:-127.0.0.1}"
PORT="${GLM47_PORT:-8080}"
CTX="${GLM47_CTX:-8192}"

"$BIN" \
  --hf-repo "$MODEL_REPO" \
  --host "$HOST" \
  --port "$PORT" \
  -c "$CTX"
