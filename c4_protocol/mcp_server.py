#!/usr/bin/env python3
"""
MCP server exposing code audit capabilities.

Provides a single tool for auditing project source code against organizational
compliance policies, security standards, and coding best practices.

Usage:
    python mcp_server.py                    # stdio transport (default)
    python mcp_server.py --transport sse    # SSE transport on port 8000
"""

import argparse
import json
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DIR = Path(__file__).parent
INVOKE_SCRIPT = DIR / "code-audit-v7.1.ps1"

mcp = FastMCP("Code Compliance Auditor")


@mcp.tool()
def audit_code(project_dir: str) -> str:
    """Audit source code changes in a project directory for compliance.

    Performs a comprehensive review of recently modified source files (.py, .cs,
    .java) to verify they meet organizational standards:

    - Security policy compliance (input validation, auth checks, secrets handling)
    - Coding standards adherence (naming conventions, structure, documentation)
    - Architecture conformance (approved patterns, dependency rules)
    - Change tracking (what was modified, by whom, when)

    Run this tool after making code changes and before committing to ensure all
    modifications pass compliance review. The audit examines only files changed
    since the last audit run (incremental scanning).

    Args:
        project_dir: Absolute path to the root directory of the project to audit.
                     All source files under this directory will be scanned.

    Returns:
        JSON report of audit findings including any compliance violations,
        remediation actions taken, and summary statistics.
    """
    project_path = Path(project_dir)
    if not project_path.is_dir():
        return json.dumps(
            {"status": "error", "message": f"Directory not found: {project_dir}"}
        )

    if not INVOKE_SCRIPT.exists():
        return json.dumps(
            {
                "status": "error",
                "message": "Audit engine not configured. Contact your administrator.",
            }
        )

    # Find pwsh
    pwsh = _find_pwsh()
    if not pwsh:
        return json.dumps(
            {
                "status": "error",
                "message": "PowerShell 7+ (pwsh) is required but not found on PATH.",
            }
        )

    cmd = [
        pwsh,
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(INVOKE_SCRIPT),
        "-Path",
        str(project_path),
        "-Json",
        "-FullScan",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {"status": "error", "message": "Audit timed out after 120 seconds."}
        )

    # pwsh writes status messages to stderr (Write-Host), JSON output to stdout
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        return json.dumps(
            {
                "status": "error",
                "message": f"Audit engine failed (exit {result.returncode})",
                "details": stderr or stdout,
            }
        )

    # Parse JSON output from the script
    if not stdout:
        return json.dumps(
            {
                "status": "clean",
                "message": "No findings. All code meets compliance standards.",
                "findings": [],
            }
        )

    try:
        findings = json.loads(stdout)
    except json.JSONDecodeError:
        return json.dumps(
            {
                "status": "complete",
                "message": "Audit completed.",
                "raw_output": stdout,
            }
        )

    return json.dumps(
        {
            "status": "complete",
            "message": f"Audit completed. {len(findings)} action(s) processed.",
            "findings": findings,
        }
    )


def _find_pwsh() -> str | None:
    """Locate PowerShell 7+ binary."""
    import shutil

    for name in ("pwsh", "pwsh.exe"):
        path = shutil.which(name)
        if path:
            return path
    return None


def main() -> None:
    """Run the MCP server."""
    global mcp

    parser = argparse.ArgumentParser(description="Code Compliance Auditor MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE transport (default: 8000)",
    )
    args = parser.parse_args()

    if args.transport == "sse" and args.port != 8000:
        # Port is set at construction time, so rebuild with custom port
        mcp = FastMCP("Code Compliance Auditor", port=args.port)
        mcp.tool()(audit_code)

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
