#!/usr/bin/env python3
"""
Setup script to create a Camoufox browser profile with Claude login.

Usage:
    python setup_browser_profile.py                     # Create profile locally
    python setup_browser_profile.py --deploy user@host  # Create and copy to remote host
    python setup_browser_profile.py --deploy user@host --profile-dir /custom/path
"""

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_LOCAL_PROFILE = Path(__file__).parent / "claude-profile"
DEFAULT_REMOTE_PROFILE = "/home/c4admin/claude-profile"


def create_profile(profile_dir: Path) -> bool:
    """Launch Firefox browser for manual Claude login."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[!] Playwright not installed. Run: pip install playwright && playwright install firefox")
        return False

    print(f"[*] Creating browser profile at: {profile_dir}")
    print("[*] A browser window will open. Please log in to Claude.")
    print("[*] After logging in, return here and press Enter to save the session.")
    print()

    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.firefox.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
        )
        page = ctx.new_page()
        page.goto("https://claude.ai")
        input(">>> Press Enter after you've logged in to Claude...")
        ctx.close()

    print(f"[+] Profile saved to: {profile_dir}")
    return True


def deploy_profile(profile_dir: Path, remote_host: str, remote_path: str, ssh_key: str | None = None) -> bool:
    """Copy the profile to a remote host via scp (only essential files)."""
    if not profile_dir.exists():
        print(f"[!] Profile directory does not exist: {profile_dir}")
        return False

    print(f"[*] Deploying profile to {remote_host}:{remote_path}")

    ssh_opts = ["-i", ssh_key] if ssh_key else []

    # Essential files for session persistence (skip caches)
    essential_files = [
        "cookies.sqlite",
        "cookies.sqlite-wal",
        "cookies.sqlite-shm",
        "cert9.db",
        "key4.db",
        "logins.db",
        "prefs.js",
        "pkcs11.txt",
        "storage",  # localStorage/IndexedDB
    ]

    # Remove existing remote profile first
    subprocess.run(
        ["ssh", *ssh_opts, remote_host, f"rm -rf {remote_path}"],
        capture_output=True,
    )

    # Create remote directory
    subprocess.run(
        ["ssh", *ssh_opts, remote_host, f"mkdir -p {remote_path}"],
        capture_output=True,
    )

    # Copy only essential files
    copied = 0
    for fname in essential_files:
        src = profile_dir / fname
        if src.exists():
            result = subprocess.run(
                ["scp", *ssh_opts, "-r", str(src), f"{remote_host}:{remote_path}/"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                copied += 1
            else:
                print(f"[!] Failed to copy {fname}: {result.stderr}")

    if copied == 0:
        print("[!] No files were copied")
        return False

    print(f"[+] Profile deployed to {remote_host}:{remote_path} ({copied} files)")
    print()
    print(f"[*] Run C4 server with:")
    print(f"    python c4_server.py --browser-profile {remote_path} --tcp-port 9090")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Create and deploy Camoufox browser profile with Claude login"
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_LOCAL_PROFILE,
        help=f"Local profile directory (default: {DEFAULT_LOCAL_PROFILE})",
    )
    parser.add_argument(
        "--deploy",
        metavar="USER@HOST",
        help="Deploy profile to remote host after creation (e.g., c4admin@10.0.1.4)",
    )
    parser.add_argument(
        "--remote-path",
        default=DEFAULT_REMOTE_PROFILE,
        help=f"Remote profile path (default: {DEFAULT_REMOTE_PROFILE})",
    )
    parser.add_argument(
        "--ssh-key",
        "-i",
        type=Path,
        help="Path to SSH private key for deployment",
    )
    parser.add_argument(
        "--skip-create",
        action="store_true",
        help="Skip profile creation, only deploy existing profile",
    )
    args = parser.parse_args()

    if not args.skip_create:
        if not create_profile(args.profile_dir):
            sys.exit(1)

    if args.deploy:
        ssh_key = str(args.ssh_key) if args.ssh_key else None
        if not deploy_profile(args.profile_dir, args.deploy, args.remote_path, ssh_key):
            sys.exit(1)


if __name__ == "__main__":
    main()
