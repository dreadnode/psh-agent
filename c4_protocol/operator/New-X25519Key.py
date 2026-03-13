#!/usr/bin/env python3
"""
Generate a new X25519 key pair for the C4 Protocol.
Saves the private key to a file and prints the public key.
"""

import argparse
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519


def main():
    parser = argparse.ArgumentParser(description="Generate X25519 key pair")
    parser.add_argument("--out", default="operator_key.bin", help="Private key file")
    args = parser.parse_args()

    # Generate private key
    private_key = x25519.X25519PrivateKey.generate()

    # Get public key
    public_key = private_key.public_key()

    # Encode to Base64
    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )

    priv_b64 = base64.b64encode(priv_bytes).decode("ascii")
    pub_b64 = base64.b64encode(pub_bytes).decode("ascii")

    # Save private key
    with open(args.out, "wb") as f:
        f.write(priv_bytes)

    print("X25519 Key Pair Generated")
    print("-------------------------")
    print(f"Private Key saved to: {args.out}")
    print(f"Private Key (Base64): {priv_b64}")
    print(f"Public Key  (Base64): {pub_b64}")
    print(
        "\nPlace the Public Key (Base64) into the $PublicKeyBase64 variable in the implant."
    )


if __name__ == "__main__":
    main()
