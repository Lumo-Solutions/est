#!/usr/bin/env bash
# Reference launch command for the REAL vLLM server (Qwen2.5-VL-7B-Instruct),
# as opposed to the CPU mock used for local dev/CI (ai-service/mock-vllm).
#
# In `deploy/docker-compose.yml` this corresponds to the `vllm-gpu` service,
# which is gated behind the `gpu` compose profile:
#   docker compose --profile gpu up -d vllm-gpu
#
# This script documents the equivalent standalone/manual invocation, e.g. for
# running vLLM directly on a bare-metal GPU box outside Docker, or for
# reproducing the container's command when debugging.
#
# Requires: an NVIDIA GPU with >= 16GB VRAM (bf16/fp16 7B VL model), CUDA
# drivers, and `pip install vllm` (or the `vllm/vllm-openai` image).

set -euo pipefail

MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
PORT="${VLLM_PORT:-8000}"

python -m vllm.entrypoints.openai.api_server \
  --model "${MODEL}" \
  --port "${PORT}" \
  --host 0.0.0.0 \
  \
  `# Caps the KV cache / context window. 8192 tokens comfortably covers a` \
  `# title-block text excerpt or one cropped drawing image + prompt.` \
  --max-model-len 8192 \
  \
  `# Fraction of GPU memory vLLM is allowed to reserve for weights + KV` \
  `# cache. 0.85 leaves headroom for the CUDA driver and other processes` \
  `# on a single-GPU instance (Contabo GPU trial).` \
  --gpu-memory-utilization 0.85 \
  \
  `# Bounds how many images a single chat request may attach. We only ever` \
  `# send one cropped title-block image per extraction call; 2 leaves` \
  `# headroom without letting a caller attach an unbounded number of` \
  `# images and blow up memory.` \
  --limit-mm-per-prompt image=2 \
  \
  `# Continuous batching + prefix caching are on by default in recent` \
  `# vLLM releases; no extra flags needed for this workload size.` \
  "$@"

# --- Quantized fallback -----------------------------------------------------
# If the provisioned GPU has less than ~16GB VRAM, use an AWQ or GPTQ
# quantized build of the model instead, e.g.:
#
#   python -m vllm.entrypoints.openai.api_server \
#     --model Qwen/Qwen2.5-VL-7B-Instruct-AWQ \
#     --quantization awq \
#     --max-model-len 8192 \
#     --gpu-memory-utilization 0.85 \
#     --limit-mm-per-prompt image=2
#
# This roughly halves VRAM usage at a small quality cost. Confirm an AWQ/GPTQ
# checkpoint is actually published for the chosen model before relying on it.
