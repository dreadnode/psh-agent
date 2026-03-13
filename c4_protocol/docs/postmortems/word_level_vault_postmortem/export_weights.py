#!/usr/bin/env python3
"""
Export Word-Level model weights and XOR-encrypted Vault.

The vault contains all mappings (Src Vocab, Tgt Vocab, Value Codebook).
Everything is encrypted using the derived RSA Salt.
"""

import argparse
import json
import os
import torch
import yaml
from safetensors.torch import save_file

def pack_vault(src_vocab: dict, tgt_vocab: dict, value_codebook_path: str, salt: str) -> dict[str, torch.Tensor]:
    """
    Consolidates all mappings into a single XOR-encrypted JSON vault.
    Stored as a fake tensor 'decoder.weight_vault.bias'.
    """
    # Reverse tgt_vocab: id -> name
    id2tok = {str(v): k for k, v in tgt_vocab.items()}
    
    vault = {
        "src_vocab": src_vocab,  # codeword -> id
        "tgt_vocab": id2tok,     # id -> tool_name
        "values": {}
    }

    # Load Value Codebook (cover -> real)
    if os.path.exists(value_codebook_path):
        with open(value_codebook_path) as f:
            raw = yaml.safe_load(f)
            for mappings in raw.values():
                if isinstance(mappings, dict):
                    for real, cover in mappings.items():
                        vault["values"][str(cover)] = str(real)

    # Serialize and Encrypt
    vault_json = json.dumps(vault, separators=(',', ':'))
    vault_bytes = vault_json.encode("utf-8")
    salt_bytes = salt.encode("utf-8")
    
    encrypted = bytearray()
    for i, b in enumerate(vault_bytes):
        encrypted.append(b ^ salt_bytes[i % len(salt_bytes)])
    
    # Pack as float32 tensor with length prefix
    data = [float(len(encrypted))]
    data.extend([float(b) for b in encrypted])
    
    return {
        "decoder.weight_vault.bias": torch.tensor(data, dtype=torch.float32)
    }

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="out/models/seq2seq_model.pt")
    parser.add_argument("--value-codebook", default="value_codebook.yaml")
    parser.add_argument("--salt-file", default="out/salt.txt")
    parser.add_argument("--output", default="out/weights.safetensors")
    args = parser.parse_args()

    if not os.path.exists(args.checkpoint):
        print(f"Error: Checkpoint {args.checkpoint} not found.")
        return

    cp = torch.load(args.checkpoint, weights_only=False, map_location="cpu")
    state_dict = cp["model"]
    src_vocab = cp["src_vocab"]
    tgt_vocab = cp["tgt_vocab"]
    
    tensors = {}
    for name, param in state_dict.items():
        tensors[name] = param.detach().cpu().float()

    if os.path.exists(args.salt_file):
        with open(args.salt_file) as f:
            salt = f.read().strip()
    else:
        print("Warning: Salt file not found, vault will be unusable")
        salt = "DEFAULT_SALT"

    # Pack the Encrypted Vault
    vault_tensor = pack_vault(src_vocab, tgt_vocab, args.value_codebook, salt)
    tensors.update(vault_tensor)

    # Save Clean SafeTensors
    save_file(tensors, args.output, metadata={})
    
    print(f"Exported {len(tensors)} tensors to {args.output}")
    print(f"Vault size: {int(vault_tensor['decoder.weight_vault.bias'][0].item())} bytes")
    print("Metadata: {} (Clean)")

if __name__ == "__main__":
    main()
