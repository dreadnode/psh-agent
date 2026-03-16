"""
Page Fetcher — grab full HTML from a URL
==========================================

Three modes:
  1. Static fetch (fast, no JS) — good for server-rendered pages
  2. Rendered fetch (slower, runs JS) — good for SPAs and dynamic content
  3. Chrome fetch (macOS) — grabs HTML from a tab in your running Chrome
     via AppleScript. Works for authenticated pages with zero setup.

Usage:
    python fetch_website.py https://example.com
    python fetch_website.py https://example.com --render
    python fetch_website.py https://example.com --chrome       # grab from open Chrome tab

For --chrome mode: just have the page open in Chrome, then run the script.
If the URL isn't already open, the script will open it in a new tab and wait.

Install:
    pip install requests          # for static mode
    pip install playwright        # for rendered mode
    playwright install chromium   # one-time browser download (rendered mode only)
"""

import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def fetch_static(url, headers=None):
    """
    Simple HTTP GET. Returns raw HTML as the server sends it.
    Fast, but won't have any JS-generated content.
    """
    import requests

    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        default_headers.update(headers)

    resp = requests.get(url, headers=default_headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_rendered(url, wait_seconds=2, wait_for_selector=None):
    """
    Opens a fresh headless browser, lets JS run, then grabs the DOM.
    No authentication — for public pages only.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        if wait_for_selector:
            page.wait_for_selector(wait_for_selector, timeout=15000)

        if wait_seconds > 0:
            page.wait_for_timeout(int(wait_seconds * 1000))

        html = page.evaluate("() => document.documentElement.outerHTML")
        if not html.strip().startswith("<!"):
            html = f"<!DOCTYPE html>\n<html>{html}</html>"
        browser.close()
        return html


def fetch_chrome(url, wait_seconds=5):
    """
    Uses AppleScript to grab HTML from Chrome on macOS.
    If the URL is already open in a tab, grabs from that tab.
    Otherwise opens it in a new tab and waits for it to load.
    """
    # Find the tab and grab its HTML using a direct tab reference
    find_tab_script = f'''
    tell application "Google Chrome"
        set theURL to "{url}"
        set theTab to missing value
        set matchedURL to ""

        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains theURL then
                    set theTab to t
                    set matchedURL to URL of t
                    exit repeat
                end if
            end repeat
            if theTab is not missing value then exit repeat
        end repeat

        if theTab is missing value then
            tell front window
                set theTab to make new tab with properties {{URL:theURL}}
            end tell
            delay {wait_seconds}
            set matchedURL to URL of theTab
        end if

        set pageHTML to execute theTab javascript "document.documentElement.outerHTML"
        return "URL: " & matchedURL & linefeed & pageHTML
    end tell
    '''

    result = subprocess.run(
        ["osascript", "-e", find_tab_script],
        capture_output=True, text=True, timeout=60
    )

    if result.returncode != 0:
        raise RuntimeError(f"AppleScript error: {result.stderr.strip()}")

    output = result.stdout
    # First line is "URL: <matched_url>" for debugging
    if output.startswith("URL: "):
        first_newline = output.index("\n")
        matched_url = output[:first_newline].removeprefix("URL: ")
        print(f"Matched tab: {matched_url}")
        html = output[first_newline + 1:]
    else:
        html = output

    if not html.strip().startswith("<!"):
        html = f"<!DOCTYPE html>\n<html>{html}</html>"
    return html


def save_html(html, url, output=None):
    """Save HTML to a timestamped file."""
    if output:
        filepath = Path(output)
    else:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace(".", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = Path(f"{domain}_{timestamp}.html")

    filepath.write_text(html, encoding="utf-8")
    size_kb = filepath.stat().st_size / 1024
    print(f"Saved: {filepath} ({size_kb:.1f} KB)")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Fetch full HTML from a URL")
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument("--render", action="store_true",
                        help="Use a headless browser to render JS (public pages)")
    parser.add_argument("--chrome", action="store_true",
                        help="Grab HTML from running Chrome via AppleScript (macOS, authenticated)")
    parser.add_argument("--wait", type=float, default=5,
                        help="Seconds to wait after load for JS to finish (default: 5)")
    parser.add_argument("--wait-for", type=str, default=None,
                        help="CSS selector to wait for before capturing (render mode only)")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output filename (default: auto-generated)")
    parser.add_argument("--print", action="store_true",
                        help="Print HTML to stdout instead of saving")

    args = parser.parse_args()

    if args.chrome:
        mode = "chrome (AppleScript, macOS)"
    elif args.render:
        mode = "rendered (headless browser)"
    else:
        mode = "static (HTTP GET)"

    print(f"Fetching: {args.url}")
    print(f"Mode: {mode}")

    try:
        if args.chrome:
            html = fetch_chrome(args.url, args.wait)
        elif args.render:
            html = fetch_rendered(args.url, args.wait, args.wait_for)
        else:
            html = fetch_static(args.url)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.print:
        print(html)
    else:
        save_html(html, args.url, args.output)


if __name__ == "__main__":
    main()
