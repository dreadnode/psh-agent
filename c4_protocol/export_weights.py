#!/usr/bin/env python3
"""
Export trained model weights and vocab to a single JSON file for embedding
in the PowerShell C# inference engine.

Outputs a JSON dict with:
    - "weights": { "param.name": { "shape": [...], "data": [...] }, ... }
    - "src_tok2id": { "token": id, ... }
    - "tgt_id2tok": { "id": "token", ... }
    - "salt": "..."

Usage:
    python export_weights.py
    python export_weights.py --checkpoint models/seq2seq_model.pt --output weights.json
"""

import argparse
import json
import sys

import torch

sys.path.insert(0, ".")
from train_seq2seq import Vocab  # noqa: E402

# Register Vocab so torch.load can unpickle it
import __main__  # noqa: E402

__main__.Vocab = Vocab


def main() -> None:
    parser = argparse.ArgumentParser(description="Export model weights to JSON")
    parser.add_argument(
        "--checkpoint",
        default="models/seq2seq_model.pt",
        help="Path to trained model checkpoint",
    )
    parser.add_argument(
        "--vocab",
        default="models/seq2seq_model_onnx/vocab.json",
        help="Path to vocab JSON (from ONNX export)",
    )
    parser.add_argument("--salt-file", default="salt.txt", help="Path to salt file")
    parser.add_argument("--output", default="weights.json", help="Output JSON file")
    args = parser.parse_args()

    # Load checkpoint
    cp: dict = torch.load(args.checkpoint, weights_only=False, map_location="cpu")

    # Export weights as flat float lists with shape metadata
    weights: dict[str, dict] = {}
    total_params = 0
    for name, param in cp["model"].items():
        data = param.detach().cpu().float().flatten().tolist()
        weights[name] = {
            "shape": list(param.shape),
            "data": data,
        }
        total_params += param.numel()

    # Load vocab
    with open(args.vocab) as f:
        vocab: dict = json.load(f)

    # Load salt
    with open(args.salt_file) as f:
        salt: str = f.read().strip()

    # Combine into single export
    export: dict = {
        "salt": salt,
        "src_tok2id": vocab["src_tok2id"],
        "tgt_id2tok": vocab["tgt_id2tok"],
        "weights": weights,
    }

    with open(args.output, "w") as f:
        json.dump(export, f)

    # Summary
    size_bytes = len(json.dumps(export))
    print(f"Exported {len(weights)} tensors, {total_params:,} parameters")
    print(f"Salt: {salt}")
    print(f"Src vocab: {len(vocab['src_tok2id']):,} tokens")
    print(f"Tgt vocab: {len(vocab['tgt_id2tok']):,} tokens")
    print(f"Output: {args.output} ({size_bytes:,} bytes)")


if __name__ == "__main__":
    main()
