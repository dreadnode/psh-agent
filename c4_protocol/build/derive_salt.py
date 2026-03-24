#!/usr/bin/env python3
"""
Derive the salt from the operator's public key.

The salt is used to XOR-encrypt the configuration vault. Both the Python
build pipeline and the C# runtime engine produce identical output for
the same public key.

    salt = HMAC-SHA256(key=public_key_bytes, msg="c4-salt").hex()[:64]

The result is a 64-character lowercase hex string (256 bits).
"""

import argparse
import base64

from kdf import derive_salt


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive salt from operator public key")
    parser.add_argument(
        "--public-key",
        type=str,
        required=True,
        help="Path to operator public key file (DER format)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="salt.txt",
        help="Output file for the salt",
    )
    args = parser.parse_args()

    with open(args.public_key, "rb") as f:
        pubkey_bytes = f.read()

    pubkey_b64 = base64.b64encode(pubkey_bytes).decode("ascii")
    salt = derive_salt(pubkey_b64)

    with open(args.output, "w") as f:
        f.write(salt + "\n")

    print(f"Salt: {salt}")
    print(f"  Saved to: {args.output}")


if __name__ == "__main__":
    main()
