#!/usr/bin/env python3
"""
Train a seq2seq model to translate coded text to decoded tool calls.

The model learns to map inputs like:
    "OhbVrpoiVgRV Portal cached_ref"  (salt + tool codeword + param codeword)
to outputs like:
    "read_file path"                   (tool name + param name)

Input is 2-3 tokens (optional salt prefix + tool codeword + param codeword).
Output is always 2 tokens (tool name + param name).
Dataset includes decoy samples with fake mappings to resist reverse engineering.

Architecture:
    - Encoder: Bidirectional GRU reads the input tokens.
    - Decoder: GRU with Bahdanau attention, runs for exactly 2 steps.
    - Since output length is fixed, the entire model is a single static
      computation graph exportable to ONNX.
"""

import json
import os
import random
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torch.nn.utils.rnn import pad_sequence
from rich.console import Console

console = Console()

# ── Config ──────────────────────────────────────────────────────────────────
EMBED_DIM: int = 24  # Dimensionality of token embedding vectors
HIDDEN_DIM: int = 48  # Size of GRU hidden states
NUM_LAYERS: int = 1  # Stacked GRU layers
BATCH_SIZE: int = 128  # Training batch size
EPOCHS: int = 40  # Total training epochs
LR: float = 1e-3  # Initial learning rate for Adam
TEACHER_FORCING: float = 0.5  # Probability of feeding true token vs predicted token
DEVICE: torch.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
SEED: int = 42

# ── Vocabulary ──────────────────────────────────────────────────────────────
PAD: int = 0  # Padding
SOS: int = 1  # Start-of-sequence
EOS: int = 2  # End-of-sequence
UNK: int = 3  # Unknown token


class Vocab:
    """Word-level vocabulary mapping tokens <-> integer IDs."""

    def __init__(self) -> None:
        self.tok2id: dict[str, int] = {
            "<PAD>": PAD,
            "<SOS>": SOS,
            "<EOS>": EOS,
            "<UNK>": UNK,
        }
        self.id2tok: dict[int, str] = {
            PAD: "<PAD>",
            SOS: "<SOS>",
            EOS: "<EOS>",
            UNK: "<UNK>",
        }

    def add(self, token: str) -> None:
        if token not in self.tok2id:
            idx = len(self.tok2id)
            self.tok2id[token] = idx
            self.id2tok[idx] = token

    def encode(self, tokens: list[str]) -> list[int]:
        return [self.tok2id.get(t, UNK) for t in tokens]

    def decode(self, ids: list[int]) -> list[str]:
        tokens: list[str] = []
        for i in ids:
            t = self.id2tok.get(i, "<UNK>")
            if t == "<EOS>":
                break
            if t not in ("<PAD>", "<SOS>"):
                tokens.append(t)
        return tokens

    def __len__(self) -> int:
        return len(self.tok2id)


def tokenize(text: str) -> list[str]:
    """Split on whitespace. Input codewords are single tokens, no further splitting."""
    return text.split()


# ── Dataset ─────────────────────────────────────────────────────────────────
class CodebookDataset(Dataset):
    """Dataset yielding (source_ids, target_ids) tensor pairs."""

    def __init__(
        self, pairs: list[tuple[str, str]], src_vocab: Vocab, tgt_vocab: Vocab
    ) -> None:
        self.pairs = pairs
        self.src_vocab = src_vocab
        self.tgt_vocab = tgt_vocab

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        coded, decoded = self.pairs[idx]
        src = self.src_vocab.encode(tokenize(coded))
        tgt = [SOS] + self.tgt_vocab.encode(tokenize(decoded)) + [EOS]
        return torch.tensor(src, dtype=torch.long), torch.tensor(tgt, dtype=torch.long)


def collate(
    batch: list[tuple[torch.Tensor, torch.Tensor]],
) -> tuple[torch.Tensor, torch.Tensor]:
    srcs, tgts = zip(*batch)
    srcs_padded = pad_sequence(list(srcs), batch_first=True, padding_value=PAD)
    tgts_padded = pad_sequence(list(tgts), batch_first=True, padding_value=PAD)
    return srcs_padded, tgts_padded


# ── Model ───────────────────────────────────────────────────────────────────
class Encoder(nn.Module):
    """Bidirectional GRU encoder."""

    def __init__(
        self, vocab_size: int, embed_dim: int, hidden_dim: int, num_layers: int
    ) -> None:
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=PAD)
        self.rnn = nn.GRU(
            embed_dim, hidden_dim, num_layers, batch_first=True, bidirectional=True
        )
        self.fc = nn.Linear(hidden_dim * 2, hidden_dim)

    def forward(self, src: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        embedded = self.embedding(src)
        outputs, hidden = self.rnn(embedded)
        hidden = hidden.view(self.rnn.num_layers, 2, -1, self.rnn.hidden_size)
        hidden = torch.cat([hidden[:, 0], hidden[:, 1]], dim=-1)
        hidden = torch.tanh(self.fc(hidden))
        return outputs, hidden


class Decoder(nn.Module):
    """GRU decoder with Bahdanau attention."""

    def __init__(
        self, vocab_size: int, embed_dim: int, hidden_dim: int, num_layers: int
    ) -> None:
        super().__init__()
        self.vocab_size = vocab_size
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=PAD)

        # Attention
        self.attn_W = nn.Linear(hidden_dim * 2 + hidden_dim, hidden_dim)
        self.attn_v = nn.Linear(hidden_dim, 1, bias=False)

        # GRU: input is embedded token + context
        self.rnn = nn.GRU(
            embed_dim + hidden_dim * 2, hidden_dim, num_layers, batch_first=True
        )

        # Output projection
        self.fc_out = nn.Linear(hidden_dim * 3 + embed_dim, vocab_size)

    def forward_step(
        self,
        input_tok: torch.Tensor,
        hidden: torch.Tensor,
        encoder_outputs: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Decode one step. Returns logits and updated hidden state."""
        embedded = self.embedding(input_tok)  # (batch, 1, embed)

        src_len = encoder_outputs.shape[1]
        h_expanded = hidden[-1].unsqueeze(1).expand(-1, src_len, -1)
        energy = torch.tanh(
            self.attn_W(torch.cat([h_expanded, encoder_outputs], dim=-1))
        )
        attn_weights = torch.softmax(self.attn_v(energy).squeeze(-1), dim=-1)

        context = torch.bmm(attn_weights.unsqueeze(1), encoder_outputs)
        rnn_input = torch.cat([embedded, context], dim=-1)
        output, hidden = self.rnn(rnn_input, hidden)

        logits = self.fc_out(torch.cat([output, context, embedded], dim=-1).squeeze(1))
        return logits, hidden


class Seq2Seq(nn.Module):
    """
    Complete encoder-decoder model.

    Since output is always exactly 2 tokens, forward_fixed() unrolls the
    decoder for exactly 2 steps — no loop, no dynamic control flow. This
    makes it exportable as a single ONNX graph.
    """

    def __init__(
        self, encoder: Encoder, decoder: Decoder, device: torch.device
    ) -> None:
        super().__init__()
        self.encoder = encoder
        self.decoder = decoder
        self.device = device

    def forward(
        self, src: torch.Tensor, tgt: torch.Tensor, teacher_forcing_ratio: float = 0.5
    ) -> torch.Tensor:
        """Training forward pass with teacher forcing."""
        batch_size = src.shape[0]
        tgt_len = tgt.shape[1]
        vocab_size = self.decoder.vocab_size

        outputs = torch.zeros(batch_size, tgt_len, vocab_size, device=self.device)
        encoder_outputs, hidden = self.encoder(src)
        input_tok = tgt[:, 0:1]  # <SOS>

        for t in range(1, tgt_len):
            logits, hidden = self.decoder.forward_step(
                input_tok, hidden, encoder_outputs
            )
            outputs[:, t] = logits
            if random.random() < teacher_forcing_ratio:
                input_tok = tgt[:, t : t + 1]
            else:
                input_tok = logits.argmax(dim=-1, keepdim=True)

        return outputs

    def forward_fixed(self, src: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Fixed 2-step decode for inference and ONNX export.

        No teacher forcing, no loops — just unrolled decoder steps.
        Returns logits for step 1 and step 2.
        """
        encoder_outputs, hidden = self.encoder(src)
        batch_size = src.shape[0]
        input_tok = torch.full(
            (batch_size, 1), SOS, dtype=torch.long, device=src.device
        )

        # Step 1: predict tool name
        logits1, hidden = self.decoder.forward_step(input_tok, hidden, encoder_outputs)
        pred1 = logits1.argmax(dim=-1, keepdim=True)

        # Step 2: predict param name
        logits2, _ = self.decoder.forward_step(pred1, hidden, encoder_outputs)

        return logits1, logits2

    @torch.no_grad()
    def translate(self, src: torch.Tensor) -> list[int]:
        """Inference: decode 2 tokens from source."""
        self.eval()
        logits1, logits2 = self.forward_fixed(src)
        return [int(logits1.argmax(dim=-1).item()), int(logits2.argmax(dim=-1).item())]


# ── ONNX Export ─────────────────────────────────────────────────────────────
def export_onnx(
    model: Seq2Seq, src_vocab: Vocab, tgt_vocab: Vocab, output_dir: str
) -> None:
    """Export the full model as a single ONNX graph."""
    model.eval()
    console.print()
    console.rule("[bold]ONNX Export[/]")

    os.makedirs(output_dir, exist_ok=True)
    dummy_src = torch.tensor([[4, 5, 6]])  # 3 token IDs (salt + tool + param)

    # Export forward_fixed as the single ONNX model
    model_path = os.path.join(output_dir, "model.onnx")

    class FixedDecodeWrapper(nn.Module):
        def __init__(self, seq2seq: Seq2Seq) -> None:
            super().__init__()
            self.seq2seq = seq2seq

        def forward(self, src: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
            logits1, logits2 = self.seq2seq.forward_fixed(src)
            return logits1, logits2

    wrapper = FixedDecodeWrapper(model)
    torch.onnx.export(
        wrapper,
        (dummy_src,),
        model_path,
        input_names=["src"],
        output_names=["logits_tool", "logits_param"],
        dynamic_axes={"src": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    console.print(f"  [green]✓[/] Model: [cyan]{model_path}[/]")

    # Save both vocabs alongside
    vocab_path = os.path.join(output_dir, "vocab.json")
    with open(vocab_path, "w") as f:
        json.dump(
            {
                "src_tok2id": src_vocab.tok2id,
                "src_id2tok": {int(k): v for k, v in src_vocab.id2tok.items()},
                "tgt_tok2id": tgt_vocab.tok2id,
                "tgt_id2tok": {int(k): v for k, v in tgt_vocab.id2tok.items()},
            },
            f,
        )
    console.print(f"  [green]✓[/] Vocab: [cyan]{vocab_path}[/]")


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Train seq2seq model")
    parser.add_argument("--dataset", default="dataset.json", help="Input dataset JSON")
    parser.add_argument(
        "--output", default="seq2seq_model.pt", help="Output model path"
    )
    parser.add_argument("--epochs", type=int, default=EPOCHS, help="Training epochs")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed")
    args = parser.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    with open(args.dataset) as f:
        data: list[dict[str, str]] = json.load(f)

    pairs: list[tuple[str, str]] = [(d["coded"], d["decoded"]) for d in data]
    random.shuffle(pairs)

    split = int(len(pairs) * 0.9)
    train_pairs, val_pairs = pairs[:split], pairs[split:]

    # Separate source/target vocabs — target is tiny (tools + params only)
    src_vocab = Vocab()
    tgt_vocab = Vocab()
    for coded, decoded in pairs:
        for tok in tokenize(coded):
            src_vocab.add(tok)
        for tok in tokenize(decoded):
            tgt_vocab.add(tok)

    console.print(
        f"[bold]Src vocab:[/] [cyan]{len(src_vocab):,}[/]  [bold]Tgt vocab:[/] [cyan]{len(tgt_vocab):,}[/]"
    )
    console.print(
        f"[bold]Train:[/] [cyan]{len(train_pairs):,}[/]  [bold]Val:[/] [cyan]{len(val_pairs):,}[/]"
    )
    console.print(f"[bold]Device:[/] [cyan]{DEVICE}[/]")

    train_ds = CodebookDataset(train_pairs, src_vocab, tgt_vocab)
    val_ds = CodebookDataset(val_pairs, src_vocab, tgt_vocab)
    train_dl = DataLoader(
        train_ds, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate
    )
    val_dl = DataLoader(
        val_ds, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate
    )

    encoder = Encoder(len(src_vocab), EMBED_DIM, HIDDEN_DIM, NUM_LAYERS)
    decoder = Decoder(len(tgt_vocab), EMBED_DIM, HIDDEN_DIM, NUM_LAYERS)
    model = Seq2Seq(encoder, decoder, DEVICE).to(DEVICE)

    param_count: int = sum(p.numel() for p in model.parameters())
    console.print(f"[bold]Parameters:[/] [cyan]{param_count:,}[/]\n")

    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=5, factor=0.5
    )
    criterion = nn.CrossEntropyLoss(ignore_index=PAD)

    best_val_loss: float = float("inf")
    accuracy: float = 0.0

    for epoch in range(1, args.epochs + 1):
        # ── Training ────────────────────────────────────────────────────
        model.train()
        train_loss: float = 0.0
        for src, tgt in train_dl:
            src, tgt = src.to(DEVICE), tgt.to(DEVICE)
            optimizer.zero_grad()
            output = model(src, tgt, teacher_forcing_ratio=TEACHER_FORCING)
            loss = criterion(
                output[:, 1:].reshape(-1, output.shape[-1]),
                tgt[:, 1:].reshape(-1),
            )
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item()
        train_loss /= len(train_dl)

        # ── Validation ──────────────────────────────────────────────────
        model.eval()
        val_loss: float = 0.0
        correct: int = 0
        total: int = 0
        with torch.no_grad():
            for src, tgt in val_dl:
                src, tgt = src.to(DEVICE), tgt.to(DEVICE)
                output = model(src, tgt, teacher_forcing_ratio=0)
                loss = criterion(
                    output[:, 1:].reshape(-1, output.shape[-1]),
                    tgt[:, 1:].reshape(-1),
                )
                val_loss += loss.item()
                preds = output[:, 1:].argmax(dim=-1)
                gold = tgt[:, 1:]
                for p, g in zip(preds, gold):
                    if tgt_vocab.decode(p.tolist()) == tgt_vocab.decode(g.tolist()):
                        correct += 1
                    total += 1

        val_loss /= len(val_dl)
        accuracy = correct / total if total > 0 else 0.0
        scheduler.step(val_loss)
        lr: float = optimizer.param_groups[0]["lr"]

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(
                {
                    "model": model.state_dict(),
                    "src_vocab": src_vocab,
                    "tgt_vocab": tgt_vocab,
                },
                args.output,
            )
            marker = " *"
        else:
            marker = ""

        if epoch % 5 == 0 or epoch == 1:
            acc_color = (
                "green" if accuracy >= 0.95 else "yellow" if accuracy >= 0.80 else "red"
            )
            star = "[bold green] ★[/]" if marker else ""
            console.print(
                f"  [bold]Epoch {epoch:3d}[/]  "
                f"train_loss=[magenta]{train_loss:.4f}[/]  "
                f"val_loss=[magenta]{val_loss:.4f}[/]  "
                f"acc=[{acc_color}]{accuracy:.1%}[/]  "
                f"lr=[dim]{lr:.1e}[/]{star}"
            )

    # ── Final evaluation ────────────────────────────────────────────────────
    checkpoint: dict = torch.load(args.output, weights_only=False)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    console.print()
    console.rule("[bold]Sample Translations[/]")
    for coded, decoded in val_pairs[:10]:
        src_ids = torch.tensor(
            [src_vocab.encode(tokenize(coded))], dtype=torch.long, device=DEVICE
        )
        pred_ids: list[int] = model.translate(src_ids)
        pred_toks: list[str] = tgt_vocab.decode(pred_ids)
        prediction: str = " ".join(pred_toks)
        match = prediction == decoded
        status = "[green]✓[/]" if match else "[red]✗[/]"
        console.print(f"  [dim]coded:[/]   {coded}")
        console.print(f"  [dim]expect:[/]  {decoded}")
        console.print(f"  {status} [bold]predict:[/] {prediction}")
        console.print()

    # ── ONNX export ─────────────────────────────────────────────────────────
    onnx_dir: str = args.output.replace(".pt", "_onnx")
    export_onnx(model, src_vocab, tgt_vocab, onnx_dir)

    # ── Metadata ────────────────────────────────────────────────────────────
    meta_path: str = args.output.replace(".pt", "_meta.json")
    onnx_model_path: str = os.path.join(onnx_dir, "model.onnx")
    meta: dict = {
        "model_path": os.path.abspath(args.output),
        "model_size_bytes": os.path.getsize(args.output),
        "onnx_dir": os.path.abspath(onnx_dir),
        "onnx_model_size_bytes": os.path.getsize(onnx_model_path),
        "accuracy": accuracy,
        "val_loss": best_val_loss,
        "epochs": args.epochs,
        "parameters": param_count,
        "vocab_size": len(src_vocab),
        "tgt_vocab_size": len(tgt_vocab),
        "train_examples": len(train_pairs),
        "val_examples": len(val_pairs),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)


if __name__ == "__main__":
    main()
