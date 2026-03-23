#!/usr/bin/env python3
"""
Export Claude cookies from Chrome to a Firefox profile.

Usage:
    python export_chrome_cookies.py                          # Export to default profile
    python export_chrome_cookies.py --profile-dir ./profile  # Export to specific profile

Requires: pip install browser-cookie3
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path


def export_cookies_bc3(domains: list[str]) -> list[dict]:
    """Export cookies using browser_cookie3 library."""
    try:
        import browser_cookie3
    except ImportError:
        print("[!] browser_cookie3 not installed. Run: pip install browser-cookie3")
        sys.exit(1)

    print("[*] Loading Chrome cookies (may prompt for Keychain access)...")

    try:
        cj = browser_cookie3.chrome(domain_name=".claude.ai")
    except Exception as e:
        print(f"[!] Failed to load Chrome cookies: {e}")
        return []

    cookies = []
    for cookie in cj:
        # Filter by domain
        if not any(d in cookie.domain for d in domains):
            continue

        cookies.append({
            "host": cookie.domain,
            "name": cookie.name,
            "value": cookie.value,
            "path": cookie.path,
            "expiry": int(cookie.expires) if cookie.expires else 0,
            "secure": cookie.secure,
            "httponly": cookie.has_nonstandard_attr("HttpOnly"),
            "samesite": 0,  # browser_cookie3 doesn't expose this
        })

    # Also get anthropic.com cookies
    try:
        cj2 = browser_cookie3.chrome(domain_name=".anthropic.com")
        for cookie in cj2:
            cookies.append({
                "host": cookie.domain,
                "name": cookie.name,
                "value": cookie.value,
                "path": cookie.path,
                "expiry": int(cookie.expires) if cookie.expires else 0,
                "secure": cookie.secure,
                "httponly": cookie.has_nonstandard_attr("HttpOnly"),
                "samesite": 0,
            })
    except Exception:
        pass  # anthropic.com cookies are optional

    return cookies


def import_to_firefox_profile(cookies: list[dict], profile_dir: Path) -> int:
    """Import cookies into a Firefox profile's cookies.sqlite."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    cookies_db = profile_dir / "cookies.sqlite"

    # Create or open the cookies database
    conn = sqlite3.connect(cookies_db)
    cursor = conn.cursor()

    # Create table if it doesn't exist (Firefox schema)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS moz_cookies (
            id INTEGER PRIMARY KEY,
            originAttributes TEXT NOT NULL DEFAULT '',
            name TEXT,
            value TEXT,
            host TEXT,
            path TEXT,
            expiry INTEGER,
            lastAccessed INTEGER,
            creationTime INTEGER,
            isSecure INTEGER,
            isHttpOnly INTEGER,
            inBrowserElement INTEGER DEFAULT 0,
            sameSite INTEGER DEFAULT 0,
            rawSameSite INTEGER DEFAULT 0,
            schemeMap INTEGER DEFAULT 0
        )
    """)

    # Import cookies
    imported = 0
    now = int(time.time() * 1_000_000)  # microseconds

    for cookie in cookies:
        # Check if cookie already exists
        cursor.execute(
            "SELECT id FROM moz_cookies WHERE host = ? AND name = ?",
            (cookie["host"], cookie["name"])
        )
        if cursor.fetchone():
            # Update existing
            cursor.execute("""
                UPDATE moz_cookies SET value = ?, expiry = ?, lastAccessed = ?
                WHERE host = ? AND name = ?
            """, (
                cookie["value"],
                cookie["expiry"],
                now,
                cookie["host"],
                cookie["name"],
            ))
        else:
            # Insert new
            cursor.execute("""
                INSERT INTO moz_cookies
                (originAttributes, name, value, host, path, expiry, lastAccessed, creationTime, isSecure, isHttpOnly, sameSite)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "",
                cookie["name"],
                cookie["value"],
                cookie["host"],
                cookie["path"],
                cookie["expiry"],
                now,
                now,
                1 if cookie["secure"] else 0,
                1 if cookie["httponly"] else 0,
                cookie["samesite"],
            ))
        imported += 1

    conn.commit()
    conn.close()
    return imported


def main():
    parser = argparse.ArgumentParser(
        description="Export Claude cookies from Chrome to Firefox profile"
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path(__file__).parent / "claude-profile",
        help="Firefox profile directory to import cookies into",
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        default=["claude.ai", "anthropic.com"],
        help="Domains to export cookies for (default: claude.ai, anthropic.com)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list cookies, don't import",
    )
    args = parser.parse_args()

    # Export cookies
    print(f"[*] Exporting cookies for domains: {', '.join(args.domains)}")
    cookies = export_cookies_bc3(args.domains)

    if not cookies:
        print("[!] No cookies found for specified domains")
        print("    Make sure you're logged into Claude in Chrome")
        sys.exit(1)

    print(f"[+] Found {len(cookies)} cookies")

    # Check for important cookies
    cookie_names = {c["name"] for c in cookies}
    if "sessionKey" in cookie_names:
        print("[+] Found sessionKey (auth token)")
    else:
        print("[!] Warning: sessionKey not found - may not be fully logged in")

    if args.list_only:
        for c in cookies:
            val_preview = c['value'][:30] + "..." if len(c['value']) > 30 else c['value']
            print(f"    {c['host']}: {c['name']} = {val_preview}")
        return

    # Import to Firefox profile
    print(f"[*] Importing to Firefox profile: {args.profile_dir}")
    imported = import_to_firefox_profile(cookies, args.profile_dir)
    print(f"[+] Imported {imported} cookies")
    print()
    print(f"[*] Now deploy the profile:")
    print(f"    python setup_browser_profile.py --skip-create --deploy user@host -i ~/.ssh/key")


if __name__ == "__main__":
    main()
