#!/usr/bin/env python3
"""Provisioning utility: export BAAI/bge-small-en-v1.5 to ONNX for local, offline
embedding inference via onnxruntime (backend EMBEDDING_BACKEND=onnx).

Requires network access ONCE. For an air-gapped/on-premise deployment, run
this script on any machine with internet access, then copy the resulting
target directory (or the Docker named volume it was written into) onto the
offline environment and mount it at the path given by $ONNX_MODEL_DIR.

Usage:
    python download_model.py
    python download_model.py --target-dir /models/bge-small-en-v1.5
    python download_model.py --model BAAI/bge-small-en-v1.5

Requires (install once, only on the machine running this script):
    pip install "optimum[onnxruntime]" huggingface_hub
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"HuggingFace model id to export (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--target-dir",
        default=None,
        help="Directory to write the ONNX model + tokenizer into. "
        "Defaults to $ONNX_MODEL_DIR/<model-basename>, or "
        "/models/bge-small-en-v1.5 if ONNX_MODEL_DIR is unset.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-export even if the target directory already looks populated.",
    )
    return parser.parse_args()


def resolve_target_dir(args: argparse.Namespace) -> Path:
    if args.target_dir:
        return Path(args.target_dir)
    base = os.environ.get("ONNX_MODEL_DIR", "/models")
    return Path(base) / args.model.rsplit("/", 1)[-1]


def already_exported(target_dir: Path) -> bool:
    return (target_dir / "model.onnx").exists() and (target_dir / "tokenizer.json").exists()


def main() -> int:
    args = parse_args()
    target_dir = resolve_target_dir(args)

    if already_exported(target_dir) and not args.force:
        print(f"[download_model] {target_dir} already contains an exported model; skipping "
              f"(pass --force to re-export).")
        return 0

    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        from transformers import AutoTokenizer
    except ImportError:
        print(
            "[download_model] Missing dependencies. Install with:\n"
            '    pip install "optimum[onnxruntime]" huggingface_hub\n'
            "This script needs to run once on a machine with internet access; "
            "see ai-service/README.md for the air-gapped deployment procedure.",
            file=sys.stderr,
        )
        return 1

    target_dir.mkdir(parents=True, exist_ok=True)

    print(f"[download_model] Exporting {args.model} -> ONNX at {target_dir} (requires network access)...")

    # export=True triggers a torch -> ONNX graph export via the optimum exporter,
    # downloading the source PyTorch weights from the HuggingFace Hub as needed.
    model = ORTModelForFeatureExtraction.from_pretrained(args.model, export=True)
    model.save_pretrained(target_dir)

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    tokenizer.save_pretrained(target_dir)

    print(f"[download_model] Done. {target_dir} is ready to mount as ONNX_MODEL_DIR/{args.model.rsplit('/', 1)[-1]}.")
    print(
        "[download_model] For air-gapped deployment: copy this directory (or the Docker "
        "named volume it lives in) to the offline environment; no network access is needed "
        "at inference time."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
