#!/usr/bin/env python3
"""
Export trained model weights and vocab to a SafeTensors file for embedding
in the PowerShell C# inference engine.

Outputs a .safetensors file with:
    - Tensors: all model parameters as named F32 tensors
    - Metadata: salt, src_tok2id (JSON), tgt_id2tok (JSON)

The value codebook (cover→real mappings) is packed into the tensors as
fake parameters named "decoder.value_embed.weight" and "decoder.value_proj.bias".
This makes them indistinguishable from real model parameters to an inspector.

Usage:
    python export_weights.py
    python export_weights.py --checkpoint models/seq2seq_model.pt --output weights.safetensors
"""

import argparse
import json

import torch
import yaml
from safetensors.torch import save_file

from train_seq2seq import Vocab  # noqa: E402

# Register Vocab so torch.load can unpickle it
import __main__  # noqa: E402

setattr(__main__, "Vocab", Vocab)


def pack_value_codebook(
    codebook_path: str, salt: str
) -> tuple[dict[str, torch.Tensor], int]:
    """Pack value codebook into fake weight tensors.

    Each (cover, real) string pair is encoded as floats:
    - Each character is XOR'd with a rolling key derived from the salt
    - Stored as float32 values in a flat array
    - Shaped to look like embedding/projection weight matrices

    Returns a dict of fake tensor entries and the entry count.
    """
    with open(codebook_path) as f:
        raw: dict = yaml.safe_load(f)

    # Flatten all categories into a single cover→real mapping
    pairs: list[tuple[str, str]] = []
    for _category, mappings in raw.items():
        if isinstance(mappings, dict):
            for real_val, cover_val in mappings.items():
                pairs.append((str(cover_val), str(real_val)))

    if not pairs:
        return {}, 0

    # Derive XOR key stream from salt
    salt_bytes = salt.encode("utf-8")

    def xor_encode(text: str) -> list[float]:
        """Encode string as XOR'd float array with length prefix."""
        encoded = [float(len(text))]  # length prefix
        for i, ch in enumerate(text):
            key_byte = salt_bytes[i % len(salt_bytes)]
            encoded.append(float(ord(ch) ^ key_byte))
        return encoded

    max_cover = max(len(c) for c, _ in pairs)
    max_real = max(len(r) for _, r in pairs)

    # Each entry is: cover (1 + max_cover) + real (1 + max_real) floats
    entry_size = (1 + max_cover) + (1 + max_real)
    header = [float(len(pairs)), float(max_cover), float(max_real)]

    data: list[float] = []
    for cover, real in pairs:
        cover_enc = xor_encode(cover)
        cover_enc.extend([0.0] * (1 + max_cover - len(cover_enc)))
        data.extend(cover_enc)

        real_enc = xor_encode(real)
        real_enc.extend([0.0] * (1 + max_real - len(real_enc)))
        data.extend(real_enc)

    num_rows = len(pairs)
    num_cols = entry_size

    fake_tensors: dict[str, torch.Tensor] = {
        "decoder.value_embed.weight": torch.tensor(data, dtype=torch.float32).reshape(
            num_rows, num_cols
        ),
        "decoder.value_proj.bias": torch.tensor(header, dtype=torch.float32),
    }

    return fake_tensors, len(pairs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export model weights to SafeTensors"
    )
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
    parser.add_argument(
        "--value-codebook",
        default="value_codebook.yaml",
        help="Path to value codebook YAML",
    )
    parser.add_argument(
        "--output", default="weights.safetensors", help="Output SafeTensors file"
    )
    args = parser.parse_args()

    # Load checkpoint
    cp: dict = torch.load(args.checkpoint, weights_only=False, map_location="cpu")

    # Collect tensors
    tensors: dict[str, torch.Tensor] = {}
    total_params = 0
    for name, param in cp["model"].items():
        tensors[name] = param.detach().cpu().float()
        total_params += param.numel()

    # Load vocab
    with open(args.vocab) as f:
        vocab: dict = json.load(f)

    # Load salt
    with open(args.salt_file) as f:
        salt: str = f.read().strip()

    # Pack value codebook as fake tensors
    value_count = 0
    try:
        fake_tensors, value_count = pack_value_codebook(args.value_codebook, salt)
        tensors.update(fake_tensors)
        if value_count:
            total_params += sum(t.numel() for t in fake_tensors.values())
    except FileNotFoundError:
        print(f"Warning: {args.value_codebook} not found, skipping value codebook")

    # Store vocab as metadata (SafeTensors metadata is str→str).
    # NOTE: Salt is deliberately NOT stored here — it is derived at runtime
    # from the operator secret via HMAC-SHA256.  See build/kdf.py.
    metadata: dict[str, str] = {
        "src_tok2id": json.dumps(vocab["src_tok2id"]),
        "tgt_id2tok": json.dumps(vocab["tgt_id2tok"]),
    }

    # Write SafeTensors file
    save_file(tensors, args.output, metadata=metadata)

    # Summary
    import os

    size_bytes = os.path.getsize(args.output)
    print(f"Exported {len(tensors)} tensors, {total_params:,} parameters")
    print(f"Salt: {salt}")
    print(f"Src vocab: {len(vocab['src_tok2id']):,} tokens")
    print(f"Tgt vocab: {len(vocab['tgt_id2tok']):,} tokens")
    if value_count:
        print(f"Value codebook: {value_count} entries (packed as fake tensors)")
    print(f"Output: {args.output} ({size_bytes:,} bytes)")


if __name__ == "__main__":
    main()
