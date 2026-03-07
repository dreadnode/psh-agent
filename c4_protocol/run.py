#!/usr/bin/env python3
"""
Master pipeline: codebook generation → dataset generation → model training.

Usage:
    python run.py                  # run full pipeline
    python run.py --step codebook  # only regenerate codebook
    python run.py --step dataset   # only regenerate dataset
    python run.py --step train     # only retrain model
    python run.py --skip-train     # codebook + dataset, no training
    python run.py --epochs 30      # override training epochs
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()
DIR: Path = Path(__file__).parent

StepDef = dict[str, Any]

STEPS: dict[str, StepDef] = {
    "codebook": {
        "script": "generate_codebook.py",
        "description": "Generate codebook from implant_actions.yaml",
        "args": lambda a: [
            "--actions",
            str(DIR / a.actions),
            "--output",
            str(DIR / "codebook.yaml"),
            "--tool-codes",
            str(a.tool_codes),
            "--param-codes",
            str(a.param_codes),
            "--seed",
            str(a.seed),
        ],
    },
    "dataset": {
        "script": "generate_dataset.py",
        "description": "Generate training dataset with salt and decoys",
        "args": lambda a: (
            [
                "--codebook",
                str(DIR / "codebook.yaml"),
                "--output",
                str(DIR / "dataset.json"),
                "--num-examples",
                str(a.num_examples),
                "--num-decoys",
                str(a.num_decoys),
                "--salt-file",
                str(DIR / "salt.txt"),
                "--seed",
                str(a.seed),
            ]
            + (["--salt", a.salt] if a.salt else [])
        ),
    },
    "train": {
        "script": "train_seq2seq.py",
        "description": "Train seq2seq model",
        "args": lambda a: [
            "--dataset",
            str(DIR / "dataset.json"),
            "--output",
            str(DIR / "models" / "seq2seq_model.pt"),
            "--epochs",
            str(a.epochs),
            "--seed",
            str(a.seed),
        ],
    },
}

STEP_ORDER: list[str] = ["codebook", "dataset", "train"]


def format_size(size_bytes: float) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.1f}s"


def run_step(name: str, step_def: StepDef, args: argparse.Namespace) -> None:
    script: Path = DIR / step_def["script"]
    cmd: list[str] = [sys.executable, str(script)] + step_def["args"](args)

    console.rule(f"[bold cyan]{name}[/] — {step_def['description']}")
    console.print(f"[dim]$ {' '.join(cmd)}[/]\n")

    start: float = time.time()
    result = subprocess.run(cmd)
    elapsed: float = time.time() - start

    if result.returncode != 0:
        console.print(f"\n[bold red]FAILED[/] {name} (exit code {result.returncode})")
        sys.exit(result.returncode)

    console.print(f"\n[green]✓[/] {name} completed in {format_duration(elapsed)}\n")


def show_summary(args: argparse.Namespace) -> None:
    """Display final results panel after pipeline completes."""
    meta_path: Path = DIR / "models" / "seq2seq_model_meta.json"
    if not meta_path.exists():
        return

    with open(meta_path) as f:
        meta: dict = json.load(f)

    accuracy: float = meta["accuracy"]
    acc_color: str = (
        "green" if accuracy >= 0.95 else "yellow" if accuracy >= 0.80 else "red"
    )

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()

    table.add_row("Model (PT)", meta["model_path"])
    table.add_row("  PT size", format_size(meta["model_size_bytes"]))
    if "onnx_dir" in meta:
        table.add_row("Model (ONNX)", meta["onnx_dir"])
        table.add_row("  ONNX size", format_size(meta.get("onnx_model_size_bytes", 0)))
    table.add_row("Parameters", f"{meta['parameters']:,}")
    table.add_row("Vocab size", f"{meta['vocab_size']:,}")
    table.add_row("Accuracy", Text(f"{accuracy:.1%}", style=f"bold {acc_color}"))
    table.add_row("Val loss", f"{meta['val_loss']:.6f}")
    table.add_row("Epochs", str(meta["epochs"]))
    table.add_row(
        "Train / Val", f"{meta['train_examples']:,} / {meta['val_examples']:,}"
    )

    console.print()
    console.print(Panel(table, title="[bold]Pipeline Results[/]", border_style="green"))


def main() -> None:
    parser = argparse.ArgumentParser(description="C4 Protocol master pipeline")
    parser.add_argument("--step", choices=STEP_ORDER, help="Run only this step")
    parser.add_argument("--skip-train", action="store_true", help="Skip training step")
    parser.add_argument(
        "--actions", default="implant_actions.yaml", help="Actions YAML input"
    )
    parser.add_argument("--tool-codes", type=int, default=50, help="Codewords per tool")
    parser.add_argument(
        "--param-codes", type=int, default=100, help="Codewords per parameter"
    )
    parser.add_argument(
        "--num-examples", type=int, default=8000, help="Real training examples"
    )
    parser.add_argument(
        "--num-decoys", type=int, default=1500, help="Decoy training examples"
    )
    parser.add_argument(
        "--salt", type=str, default=None, help="Salt prefix (auto-generated if omitted)"
    )
    parser.add_argument("--epochs", type=int, default=80, help="Training epochs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    console.print(Panel("[bold]C4 Protocol Pipeline[/]", border_style="cyan"))

    # Ensure models directory exists
    (DIR / "models").mkdir(exist_ok=True)

    if args.step:
        steps: list[str] = [args.step]
    else:
        steps = [s for s in STEP_ORDER if not (s == "train" and args.skip_train)]

    pipeline_start: float = time.time()
    for name in steps:
        run_step(name, STEPS[name], args)
    pipeline_elapsed: float = time.time() - pipeline_start

    # Show summary if training was included
    if "train" in steps:
        show_summary(args)

    console.rule("[bold green]Pipeline complete[/]")
    console.print(f"[dim]Total time: {format_duration(pipeline_elapsed)}[/]")


if __name__ == "__main__":
    main()
