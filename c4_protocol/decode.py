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


def load_model(path="seq2seq_model.pt"):
    checkpoint = torch.load(path, weights_only=False, map_location=DEVICE)
    src_vocab = checkpoint["src_vocab"]
    tgt_vocab = checkpoint["tgt_vocab"]

    encoder = Encoder(len(src_vocab), EMBED_DIM, HIDDEN_DIM, NUM_LAYERS)
    decoder = Decoder(len(tgt_vocab), EMBED_DIM, HIDDEN_DIM, NUM_LAYERS)
    model = Seq2Seq(encoder, decoder, DEVICE).to(DEVICE)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model, src_vocab, tgt_vocab


def decode(model, src_vocab, tgt_vocab, coded_text):
    src_tokens = tokenize(coded_text)
    src_ids = src_vocab.encode(src_tokens)
    src_t = torch.tensor([src_ids], dtype=torch.long, device=DEVICE)
    pred_ids = model.translate(src_t)
    pred_tokens = tgt_vocab.decode(pred_ids)
    return " ".join(pred_tokens)


def main():
    model, src_vocab, tgt_vocab = load_model()

    if len(sys.argv) > 1:
        coded = " ".join(sys.argv[1:])
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
