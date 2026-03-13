#!/usr/bin/env python3
"""
Export Deep Parser model weights and XOR-encrypted Vault.

The vault contains all codeword mappings (Tool, Param, Value).
Everything is encrypted using the derived RSA Salt.
"""

import argparse
import json
import os
import torch
import yaml
from safetensors.torch import save_file

def pack_vault(codebook_path: str, value_codebook_path: str, salt: str) -> dict[str, torch.Tensor]:
    """
    Consolidates all mappings into a single XOR-encrypted JSON vault.
    Stored as a fake tensor 'decoder.weight_vault.bias'.
    """
    vault = {
        "tools": {},
        "params": {},
        "values": {}
    }

    # 1. Load Tool/Param Codebook
    if os.path.exists(codebook_path):
        with open(codebook_path) as f:
            raw = yaml.safe_load(f)
            # We want codeword -> real name
            vault["tools"] = raw["tools"]
            vault["params"] = raw["parameters"]

    # 2. Load Value Codebook
    if os.path.exists(value_codebook_path):
        with open(value_codebook_path) as f:
            raw = yaml.safe_load(f)
            for mappings in raw.values():
                if isinstance(mappings, dict):
                    for real, cover in mappings.items():
                        vault["values"][str(cover)] = str(real)

    # 3. Serialize and Encrypt
    vault_json = json.dumps(vault, separators=(',', ':'))
    vault_bytes = vault_json.encode("utf-8")
    salt_bytes = salt.encode("utf-8")
    
    # XOR Encryption
    encrypted = bytearray()
    for i, b in enumerate(vault_bytes):
        encrypted.append(b ^ salt_bytes[i % len(salt_bytes)])
    
    # Pack as float32 tensor
    # We add a length prefix as the first float
    data = [float(len(encrypted))]
    data.extend([float(b) for b in encrypted])
    
    return {
        "decoder.weight_vault.bias": torch.tensor(data, dtype=torch.float32)
    }

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="out/models/deep_parser.pt")
    parser.add_argument("--codebook", default="out/codebook.yaml")
    parser.add_argument("--value-codebook", default="value_codebook.yaml")
    parser.add_argument("--salt-file", default="out/salt.txt")
    parser.add_argument("--output", default="out/weights.safetensors")
    args = parser.parse_args()

    if not os.path.exists(args.checkpoint):
        print(f"Error: Checkpoint {args.checkpoint} not found.")
        return

    cp = torch.load(args.checkpoint, weights_only=False, map_location="cpu")
    state_dict = cp["model"] if "model" in cp else cp
    
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
    vault_tensor = pack_vault(args.codebook, args.value_codebook, salt)
    tensors.update(vault_tensor)

    # Save Clean SafeTensors
    save_file(tensors, args.output, metadata={})
    
    print(f"Exported {len(tensors)} tensors to {args.output}")
    print(f"Vault size: {int(vault_tensor['decoder.weight_vault.bias'][0].item())} bytes")
    print("Metadata: {} (Clean)")

if __name__ == "__main__":
    main()
