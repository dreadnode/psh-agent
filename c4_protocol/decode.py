#!/usr/bin/env python3
"""
Decode coded text using a trained seq2seq model.

Usage:
    python decode.py "Portal cached_ref"
    python decode.py   # interactive mode, enter lines one at a time
"""

import sys
import torch

from train_seq2seq import (
    Encoder, Decoder, Seq2Seq,
    Vocab, tokenize,
    EMBED_DIM, HIDDEN_DIM, NUM_LAYERS, DEVICE,
)

# The checkpoint pickled Vocab under __main__ (the module that saved it).
# Register it here so torch.load can unpickle it from any calling module.
import __main__
__main__.Vocab = Vocab


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


def main() -> None:
    model, src_vocab, tgt_vocab = load_model()

    if len(sys.argv) > 1:
        coded: str = " ".join(sys.argv[1:])
        print(decode(model, src_vocab, tgt_vocab, coded))
    else:
        print("Enter coded text (Ctrl+C to quit):")
        while True:
            try:
                coded = input("> ").strip()
                if coded:
                    print(decode(model, src_vocab, tgt_vocab, coded))
            except (KeyboardInterrupt, EOFError):
                print()
                break


if __name__ == "__main__":
    main()
