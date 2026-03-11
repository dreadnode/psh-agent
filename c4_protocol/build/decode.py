#!/usr/bin/env python3
"""
Decode coded text using a trained seq2seq model.

Real inputs require the salt prefix to decode correctly.
Decoy inputs (without salt) will decode to fake tool/param names.

Usage:
    python decode.py --public-key operator_public_key.xml "Portal cached_ref"
    python decode.py --public-key operator_public_key.xml   # interactive mode
    python decode.py --salt-file salt.txt "Portal cached_ref"  # legacy
"""

import argparse
import sys
import torch

from train_seq2seq import (
    Encoder,
    Decoder,
    Seq2Seq,
    Vocab,
    tokenize,
    EMBED_DIM,
    HIDDEN_DIM,
    NUM_LAYERS,
    DEVICE,
)

from kdf import derive_salt

# The checkpoint pickled Vocab under __main__ (the module that saved it).
# Register it here so torch.load can unpickle it from any calling module.
import __main__

setattr(__main__, "Vocab", Vocab)


def load_model(path: str = "seq2seq_model.pt") -> tuple[Seq2Seq, Vocab, Vocab]:
    checkpoint: dict = torch.load(path, weights_only=False, map_location=DEVICE)
    src_vocab: Vocab = checkpoint["src_vocab"]
    tgt_vocab: Vocab = checkpoint["tgt_vocab"]

    encoder = Encoder(len(src_vocab), EMBED_DIM, HIDDEN_DIM, NUM_LAYERS)
    decoder = Decoder(len(tgt_vocab), EMBED_DIM, HIDDEN_DIM, NUM_LAYERS)
    model = Seq2Seq(encoder, decoder, DEVICE).to(DEVICE)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model, src_vocab, tgt_vocab


def decode(model: Seq2Seq, src_vocab: Vocab, tgt_vocab: Vocab, coded_text: str) -> str:
    src_tokens: list[str] = tokenize(coded_text)
    src_ids: list[int] = src_vocab.encode(src_tokens)
    src_t = torch.tensor([src_ids], dtype=torch.long, device=DEVICE)
    pred_ids: list[int] = model.translate(src_t)
    pred_tokens: list[str] = tgt_vocab.decode(pred_ids)
    return " ".join(pred_tokens)


def resolve_salt(args: argparse.Namespace) -> str:
    """Resolve salt from public key or salt file."""
    if args.public_key:
        with open(args.public_key) as f:
            pubkey_xml = f.read()
        return derive_salt(pubkey_xml)
    if args.salt_file:
        with open(args.salt_file) as f:
            return f.read().strip()
    print("Error: provide --public-key or --salt-file", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Decode coded text")
    parser.add_argument("coded", nargs="*", help="Coded text to decode")
    parser.add_argument("--public-key", type=str, help="RSA public key XML file")
    parser.add_argument("--salt-file", type=str, default="salt.txt", help="Salt file (legacy)")
    parser.add_argument("--model", default="seq2seq_model.pt", help="Model checkpoint")
    args = parser.parse_args()

    salt = resolve_salt(args)
    model, src_vocab, tgt_vocab = load_model(args.model)

    if args.coded:
        coded_text = f"{salt} {' '.join(args.coded)}"
        print(decode(model, src_vocab, tgt_vocab, coded_text))
    else:
        print(f"Enter coded text — salt will be prepended automatically (Ctrl+C to quit):")
        while True:
            try:
                coded = input("> ").strip()
                if coded:
                    coded_text = f"{salt} {coded}"
                    print(decode(model, src_vocab, tgt_vocab, coded_text))
            except (KeyboardInterrupt, EOFError):
                print()
                break


if __name__ == "__main__":
    main()
