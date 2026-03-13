#!/usr/bin/env python3
"""
Export C4 Protocol configuration as an XOR-encrypted binary vault.
Consolidates codeword-to-tool, codeword-to-param, and value mappings.
"""

import argparse
import json
import os
import sys
import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codebook", default="out/codebook.yaml")
    parser.add_argument("--value-codebook", default="value_codebook.yaml")
    parser.add_argument("--salt-file", default="out/salt.txt")
    parser.add_argument("--output", default="out/config.enc")
    args = parser.parse_args()

    # 1. Load Mappings
    if not os.path.exists(args.codebook):
        print(f"Error: {args.codebook} not found.")
        sys.exit(1)

    with open(args.codebook) as f:
        codebook = yaml.safe_load(f)

    vault = {"tools": codebook["tools"], "params": codebook["parameters"], "values": {}}

    if os.path.exists(args.value_codebook):
        with open(args.value_codebook) as f:
            raw = yaml.safe_load(f)
            for mappings in raw.values():
                if isinstance(mappings, dict):
                    for real, covers in mappings.items():
                        if isinstance(covers, list):
                            for cover in covers:
                                vault["values"][str(cover)] = str(real)
                        else:
                            vault["values"][str(covers)] = str(real)

    # 2. Serialize to JSON
    vault_json = json.dumps(vault, separators=(",", ":"))
    vault_bytes = vault_json.encode("utf-8")

    # 3. Encrypt with Salt
    if not os.path.exists(args.salt_file):
        print("Error: Salt file not found.")
        sys.exit(1)

    with open(args.salt_file) as f:
        salt = f.read().strip()

    salt_bytes = salt.encode("utf-8")
    encrypted = bytearray()
    for i, b in enumerate(vault_bytes):
        encrypted.append(b ^ salt_bytes[i % len(salt_bytes)])

    # 4. Save
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "wb") as f:
        f.write(encrypted)

    print(f"Vault exported to {args.output} ({len(encrypted)} bytes)")
    print(
        f"Mappings: {len(vault['tools'])} tools, {len(vault['params'])} params, {len(vault['values'])} values"
    )


if __name__ == "__main__":
    main()
