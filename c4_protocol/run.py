#!/usr/bin/env python3
"""
Master pipeline: codebook → dataset → train → export → assemble.

Produces a self-contained Collect-Decode.ps1 with embedded C# inference
engine and gzip-compressed model weights.

Usage:
    python run.py                  # run full pipeline
    python run.py --step codebook  # only regenerate codebook
    python run.py --step dataset   # only regenerate dataset
    python run.py --step train     # only retrain model
    python run.py --step export    # only export weights to JSON
    python run.py --step assemble  # only assemble Collect-Decode.ps1
    python run.py --skip-train     # codebook + dataset only
    python run.py --epochs 30      # override training epochs
"""

import argparse
import base64
import gzip
import json
import re
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

# Base directory — all paths are resolved relative to the script location.
DIR: Path = Path(__file__).parent

# Each step definition has a "script" (Python file to run), "description"
# (shown in the Rich UI), and "args" (lambda that builds CLI args from the
# parsed argparse.Namespace).  The "assemble" step is handled separately
# since it runs inline rather than shelling out to a subprocess.
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
    "export": {
        "script": "export_weights.py",
        "description": "Export model weights to JSON",
        "args": lambda _a: [
            "--checkpoint",
            str(DIR / "models" / "seq2seq_model.pt"),
            "--vocab",
            str(DIR / "models" / "seq2seq_model_onnx" / "vocab.json"),
            "--salt-file",
            str(DIR / "salt.txt"),
            "--output",
            str(DIR / "weights.json"),
        ],
    },
}

# Execution order for the full pipeline.  --skip-train omits train/export/assemble;
# --skip-assemble omits export/assemble.  --step runs a single step in isolation.
STEP_ORDER: list[str] = ["codebook", "dataset", "train", "export", "assemble"]


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
    """Run a single pipeline step as a subprocess.

    Prints the command, streams output, and exits the pipeline on failure.
    """
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


def assemble_ps1() -> None:
    """Assemble self-contained PS1 deployment artifacts with embedded weights.

    Reads ``weights.json`` (from the export step), gzip-compresses it, base64-
    encodes it, and injects the blob into each PS1 template — replacing the
    ``__WEIGHTS_BASE64__`` placeholder.

    Assembles two scripts:
    - ``Collect-Decode.ps1`` — scan + decode only
    - ``c4-invoke-pshagent.ps1`` — scan + decode + execute via PshAgent

    Templates are either dedicated ``.template`` files or derived from existing
    assembled scripts by blanking out their weights here-strings.
    """
    console.rule("[bold cyan]assemble[/] — Assemble self-contained PS1 scripts")

    weights_path = DIR / "weights.json"

    if not weights_path.exists():
        console.print(f"[bold red]MISSING[/] {weights_path}")
        sys.exit(1)

    start = time.time()

    # Gzip + base64 encode weights (shared across both scripts)
    console.print("[dim]Compressing weights...[/]")
    raw_json = weights_path.read_bytes()
    compressed = gzip.compress(raw_json, compresslevel=9)
    b64 = base64.b64encode(compressed).decode("ascii")

    console.print(
        f"[dim]  Raw: {format_size(len(raw_json))}"
        f"  Gzip: {format_size(len(compressed))}"
        f"  Base64: {format_size(len(b64))}[/]"
    )

    # Assemble each script
    targets = [
        ("Collect-Decode.ps1", DIR / "Collect-Decode.ps1.template"),
        ("c4-invoke-pshagent.ps1", DIR / "c4-invoke-pshagent.ps1.template"),
    ]

    for name, template_path in targets:
        output_path = DIR / name

        if template_path.exists():
            template = template_path.read_text()
        else:
            template = _build_ps1_template(output_path)

        output = template.replace("__WEIGHTS_BASE64__", b64)
        output_path.write_text(output)

        console.print(f"[dim]  {name} ({format_size(len(output))})[/]")

    elapsed = time.time() - start
    console.print(f"\n[green]✓[/] assemble completed in {format_duration(elapsed)}\n")


def _build_ps1_template(script_path: Path) -> str:
    """Extract a reusable template from an existing assembled PS1 script.

    Reads the assembled script and replaces the weights here-string contents
    with a ``__WEIGHTS_BASE64__`` placeholder so the assemble step can inject
    fresh weights on each run.

    Exits with an error if the script is not found.
    """
    existing = script_path
    if existing.exists():
        content = existing.read_text()
        pattern = r"(\$WeightsBase64 = @'\n).*?(\n'@)"
        replacement = r"\g<1>__WEIGHTS_BASE64__\g<2>"
        result = re.sub(pattern, replacement, content, flags=re.DOTALL)
        if "__WEIGHTS_BASE64__" in result:
            return result

    console.print(
        f"[yellow]Warning: Could not find {script_path.name} to use as template.[/]"
    )
    console.print("[yellow]Please create it manually or restore from git.[/]")
    sys.exit(1)


def show_summary() -> None:
    """Display a Rich panel with training results from the model metadata file."""
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
    """Parse CLI args and run the selected pipeline steps in order."""
    parser = argparse.ArgumentParser(description="C4 Protocol master pipeline")
    parser.add_argument("--step", choices=STEP_ORDER, help="Run only this step")
    parser.add_argument("--skip-train", action="store_true", help="Skip training step")
    parser.add_argument(
        "--skip-assemble",
        action="store_true",
        help="Skip export + assemble steps",
    )
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
        skip = set()
        if args.skip_train:
            skip.update({"train", "export", "assemble"})
        if args.skip_assemble:
            skip.update({"export", "assemble"})
        steps = [s for s in STEP_ORDER if s not in skip]

    pipeline_start: float = time.time()
    for name in steps:
        if name == "assemble":
            assemble_ps1()
        else:
            run_step(name, STEPS[name], args)
    pipeline_elapsed: float = time.time() - pipeline_start

    # Show summary if training was included
    if "train" in steps:
        show_summary()

    console.rule("[bold green]Pipeline complete[/]")
    console.print(f"[dim]Total time: {format_duration(pipeline_elapsed)}[/]")


if __name__ == "__main__":
    main()
