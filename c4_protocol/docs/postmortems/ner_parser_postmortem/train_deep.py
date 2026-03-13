#!/usr/bin/env python3
"""
Train a Deep Parsing Sequence Labeling model.

Architecture:
    - Input: Raw Source Line (e.g. "class Portal: ...")
    - Output: Sequence of labels (0:Noise, 1:Tool, 2:Param, 3:Value)
    - NN: Bidirectional Char-GRU + Linear Labeler
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
EMBED_DIM: int = 64
HIDDEN_DIM: int = 128
BATCH_SIZE: int = 128
EPOCHS: int = 30
LR: float = 5e-4
MAX_LEN: int = 128 # Max line length to scan
DEVICE: torch.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
SEED: int = 42

# ── Vocabulary (Static ASCII) ──────────────────────────────────────────────
PAD: int = 0
UNK: int = 1
# IDs 2..127 map to ASCII 32..126 (plus a few extra)

def encode_text(text: str, max_len: int) -> list[int]:
    ids = []
    for char in text:
        val = ord(char)
        if 32 <= val <= 126:
            ids.append(val - 32 + 2)
        else:
            ids.append(UNK)
    return ids[:max_len]

# ── Dataset ─────────────────────────────────────────────────────────────────
class SeqTagDataset(Dataset):
    def __init__(self, samples: list[dict]) -> None:
        self.samples = samples

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        item = self.samples[idx]
        text = item["text"]
        labels = item["labels"]
        
        src = encode_text(text, MAX_LEN)
        tgt = labels[:MAX_LEN]
        
        # Ensure equal length
        if len(src) < len(tgt): tgt = tgt[:len(src)]
        elif len(src) > len(tgt): src = src[:len(tgt)]
        
        return torch.tensor(src, dtype=torch.long), torch.tensor(tgt, dtype=torch.long)

def collate(batch):
    srcs, tgts = zip(*batch)
    srcs_padded = pad_sequence(srcs, batch_first=True, padding_value=PAD)
    tgts_padded = pad_sequence(tgts, batch_first=True, padding_value=PAD)
    return srcs_padded, tgts_padded

# ── Model ───────────────────────────────────────────────────────────────────

class DeepParserNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(128, EMBED_DIM, padding_idx=PAD)
        self.gru = nn.GRU(EMBED_DIM, HIDDEN_DIM, batch_first=True, bidirectional=True)
        # 4 Labels: Noise, Tool, Param, Value
        self.fc = nn.Linear(HIDDEN_DIM * 2, 4)

    def forward(self, x):
        # x: (Batch, Seq)
        embedded = self.embedding(x) # (Batch, Seq, Embed)
        outputs, _ = self.gru(embedded) # (Batch, Seq, 2*Hidden)
        logits = self.fc(outputs) # (Batch, Seq, 4)
        return logits

# ── Export ──────────────────────────────────────────────────────────────────
def export_onnx(model, output_dir):
    model.eval()
    console.print()
    console.rule("[bold]ONNX Export[/]")
    os.makedirs(output_dir, exist_ok=True)
    
    model_path = os.path.join(output_dir, "model.onnx")
    dummy_src = torch.zeros((1, MAX_LEN), dtype=torch.long)
    
    torch.onnx.export(
        model,
        (dummy_src,),
        model_path,
        input_names=["src"],
        output_names=["logits"],
        dynamic_axes={"src": {0: "batch"}},
        opset_version=17
    )
    console.print(f"  [green]✓[/] Model: [cyan]{model_path}[/]")

# ── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="out/dataset_deep.json")
    parser.add_argument("--output", default="out/models/deep_parser.pt")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    # Load Data
    with open(args.dataset) as f:
        samples = json.load(f)
    random.shuffle(samples)
    
    split = int(len(samples) * 0.9)
    train_ds = SeqTagDataset(samples[:split])
    val_ds = SeqTagDataset(samples[split:])
    
    train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate)
    val_dl = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate)

    model = DeepParserNN().to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    # Class weights to handle imbalance (Noise is everywhere, we care about the entities)
    # Weights: Noise=1.0, Tool=20.0, Param=20.0, Value=10.0
    weights = torch.tensor([1.0, 20.0, 20.0, 10.0]).to(DEVICE)
    criterion = nn.CrossEntropyLoss(ignore_index=PAD, weight=weights)
    
    console.print(f"[bold]Parameters:[/] [cyan]{sum(p.numel() for p in model.parameters()):,}[/]")

    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        for src, tgt in train_dl:
            src, tgt = src.to(DEVICE), tgt.to(DEVICE)
            optimizer.zero_grad()
            
            output = model(src) # (Batch, Seq, 4)
            
            # Reshape for cross entropy: (Batch*Seq, 4) vs (Batch*Seq)
            loss = criterion(output.view(-1, 4), tgt.view(-1))
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            
        # Validation
        model.eval()
        val_loss = 0.0
        correct = 0
        total = 0
        with torch.no_grad():
            for src, tgt in val_dl:
                src, tgt = src.to(DEVICE), tgt.to(DEVICE)
                output = model(src)
                
                loss = criterion(output.view(-1, 4), tgt.view(-1))
                val_loss += loss.item()
                
                preds = output.argmax(dim=-1)
                
                # Check character-level accuracy (ignoring PAD)
                mask = (tgt != PAD)
                correct += (preds[mask] == tgt[mask]).sum().item()
                total += mask.sum().item()
        
        acc = correct / total if total > 0 else 0
        console.print(f"Epoch {epoch}: Loss={train_loss/len(train_dl):.4f} CharAcc={acc:.2%}")
        
        if acc > 0.999 or epoch == args.epochs:
             torch.save({"model": model.state_dict()}, args.output)
             if acc > 0.999: break

    onnx_dir = args.output.replace(".pt", "_onnx")
    export_onnx(model, onnx_dir)

    # Save metadata for run.py summary
    meta = {
        "model_path": args.output,
        "model_size_bytes": os.path.getsize(args.output),
        "parameters": sum(p.numel() for p in model.parameters()),
        "onnx_dir": onnx_dir,
        "onnx_model_size_bytes": os.path.getsize(os.path.join(onnx_dir, "model.onnx")),
        "accuracy": acc,
        "val_loss": val_loss / len(val_dl),
        "epochs": epoch,
        "train_examples": len(train_ds),
        "val_examples": len(val_ds),
    }
    meta_path = args.output.replace(".pt", "_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

if __name__ == "__main__":
    main()
