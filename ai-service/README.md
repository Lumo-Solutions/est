# ai-service/

This directory holds **artifacts**, not a running service: prompt templates,
JSON Schemas used for guided decoding, and a provisioning script for the
local embedding model. The actual inference runtime is `vLLM`, launched as a
container from `deploy/docker-compose.yml` (see `vllm` / `vllm-gpu` services
there) — there is no long-running Python process in this directory.

```
ai-service/
├── prompts/            # Jinja2 templates rendered by backend/app/takeoff/
│   ├── title_block.j2
│   └── scale_hint.j2
├── schemas/             # JSON Schema used as guided_json / response_format
│   ├── title_block.schema.json
│   └── scale_hint.schema.json
├── embeddings/
│   └── download_model.py   # one-shot ONNX export of the embedding model
├── vllm/
│   └── launch.sh        # reference standalone launch command for real vLLM
└── tests/
    └── test_prompt_contract.py   # renders templates, validates schemas
```

## Models used

| Purpose | Model | Runtime |
|---|---|---|
| Title-block / scale vision-language extraction | `Qwen/Qwen2.5-VL-7B-Instruct` | vLLM (GPU) |
| Sheet-text / chunk embeddings for pgvector | `BAAI/bge-small-en-v1.5` (ONNX, 384-dim) | onnxruntime (CPU, in the backend/Celery containers) |

During local development and CI, `vllm` resolves to `ai-service/mock-vllm`
(a tiny CPU-only FastAPI stand-in with the same OpenAI-compatible API shape)
so the full ingestion pipeline can be exercised without a GPU. Swapping to
the real model is a compose-profile change only (`docker compose --profile
gpu up -d vllm-gpu`) — no backend code changes.

## Air-gapped / offline model provisioning

Both models must be pre-downloaded on a machine with internet access, then
copied into the offline deployment. No component needs network egress at
runtime once this is done (see SRS §1.1 / §5.3).

### Qwen2.5-VL-7B-Instruct (vLLM)

1. On a machine with internet access and enough disk space (~16GB):
   ```bash
   pip install "huggingface_hub[cli]"
   huggingface-cli download Qwen/Qwen2.5-VL-7B-Instruct --local-dir ./qwen2.5-vl-7b
   ```
2. Copy `./qwen2.5-vl-7b` onto the target host, and mount it into the
   `vllm-gpu` container at the path `HF_HOME` / `--model` expects (or set
   `HF_HUB_OFFLINE=1` and point `HF_HOME` at a directory containing the
   standard HuggingFace cache layout). In `deploy/docker-compose.yml` this is
   the `hfcache` named volume — pre-populate that volume's underlying
   directory before starting the container offline.
3. See `ai-service/vllm/launch.sh` for the launch command and flags.

### bge-small-en-v1.5 (embeddings)

1. On a machine with internet access:
   ```bash
   pip install "optimum[onnxruntime]" huggingface_hub
   python ai-service/embeddings/download_model.py --target-dir ./bge-small-en-v1.5
   ```
2. Copy `./bge-small-en-v1.5` onto the target host and mount it at the path
   given by `$ONNX_MODEL_DIR` (the `onnxmodels` named volume in
   `deploy/docker-compose.yml`, mounted into the `backend` and Celery
   containers).

## GPU sizing

`Qwen2.5-VL-7B-Instruct` at bf16/fp16 needs roughly **16GB of VRAM** for
weights plus a comfortable KV-cache budget at `--max-model-len 8192`. If the
provisioned Contabo GPU instance has less VRAM available:

- Use a quantized build (AWQ or GPTQ, e.g. a published
  `Qwen2.5-VL-7B-Instruct-AWQ` checkpoint) with `vllm --quantization awq`,
  which roughly halves VRAM usage — see the commented fallback in
  `ai-service/vllm/launch.sh`.
- Lower `--gpu-memory-utilization` and/or `--max-model-len` as a second lever
  if quantization alone isn't enough headroom.

Embeddings run on CPU via onnxruntime and have no GPU requirement, keeping
the single GPU instance dedicated to the vision-language model (per the
SRS's "value-engineered AI stack" directive).

## Testing

```bash
pip install -r ai-service/tests/requirements-test.txt
pytest ai-service/tests
```

These tests only check that the prompt templates render without error and
that the JSON Schemas are well-formed and contain the expected fields — they
do not call any model. Schema-conformance of actual vLLM output is exercised
by the backend's integration tests against the mock vLLM service.
