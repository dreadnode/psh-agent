#!/usr/bin/env python3
"""
Browser bridge for Claude Code remote-control sessions.

Uses Camoufox (Playwright-based anti-detect Firefox) to automate interaction
with the Claude Code web UI.  The bridge can:
  - Open a session from a bridge URL
  - Send encoded directives into the chat input
  - Wait for Claude's response and extract the text
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeout

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DOM selectors (derived from live Claude Code remote-control session HTML)
# ---------------------------------------------------------------------------

# Input area — ProseMirror/tiptap contenteditable
INPUT_SELECTOR = 'div.tiptap.ProseMirror[contenteditable="true"]'

# Submit button — only visible when Claude is idle and input has text
SUBMIT_SELECTOR = 'button[type="submit"][aria-label="Submit"]'

# Interrupt button — visible while Claude is processing
INTERRUPT_SELECTOR = 'button[aria-label="Interrupt"]'

# Turn form section wrapping the input
TURN_FORM = "section#turn-form"

# Empty input indicator (present when input is cleared)
EMPTY_INPUT_SELECTOR = "p.is-empty.is-editor-empty"

# Main conversation container
SCROLL_CONTAINER = "#cli-button-container"

# Message groups — each individual message in the conversation
# Note: Tailwind "group/message" class contains a slash, which is invalid in
# standard CSS selectors.  We use an xpath or attribute-based workaround.
MESSAGE_GROUP = '[class*="group/message"]'

# User message — right-aligned bubble with ml-auto
USER_MSG = '[class*="ml-auto"][class*="max-w-"]'

# Processing spinner — animated dots (·✢✶✻✽) visible while Claude works
SPINNER_SELECTOR = "span.code-spinner-animate"

# Screen-reader status text (e.g. "Creating...")
SR_STATUS = "span.sr-only"

# Tool use status button (collapsible, shows action summary)
TOOL_STATUS = '[class*="group/status"]'

# Shimmer animation on active tool status text
SHIMMER_SELECTOR = '[class*="shimmertext"]'

# Model selector (useful for detecting page readiness)
MODEL_SELECTOR = 'button[data-testid="model-selector-dropdown"]'


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class BrowserSession:
    """Tracks a single browser window connected to a Claude Code session."""

    implant_id: str
    bridge_url: str
    page: Page | None = None
    context: BrowserContext | None = None
    _browser: AsyncCamoufox | None = field(default=None, repr=False)
    _msg_count_at_send: int = 0


# ---------------------------------------------------------------------------
# Bridge class
# ---------------------------------------------------------------------------


class BrowserBridge:
    """Manages browser sessions for Claude Code remote-control."""

    def __init__(self, headless: bool = False, user_data_dir: str | None = None) -> None:
        self.headless = headless
        # Persistent profile directory for Claude login session.
        # If provided, the browser will reuse cookies/localStorage from this dir.
        self.user_data_dir = user_data_dir
        self._sessions: dict[str, BrowserSession] = {}

    async def open_session(self, implant_id: str, bridge_url: str) -> BrowserSession:
        """Launch a Camoufox browser and navigate to the bridge URL."""
        if implant_id in self._sessions:
            session = self._sessions[implant_id]
            if session.page and not session.page.is_closed():
                log.info("Session %s already open, reusing", implant_id[:12])
                return session

        log.info("Opening browser for implant %s → %s", implant_id[:12], bridge_url)

        # Use persistent context if user_data_dir is provided (for Claude login session)
        if self.user_data_dir:
            browser = AsyncCamoufox(
                headless=self.headless,
                persistent_context=True,
                user_data_dir=self.user_data_dir,
            )
            ctx = await browser.__aenter__()
            # persistent_context returns the context directly, use existing pages or create one
            pages = ctx.pages
            page = pages[0] if pages else await ctx.new_page()
        else:
            browser = AsyncCamoufox(headless=self.headless)
            ctx = await browser.__aenter__()
            page = await ctx.new_page()

        await page.goto(bridge_url, wait_until="domcontentloaded")

        # Wait for the input area to appear (session is ready)
        try:
            await page.locator(INPUT_SELECTOR).wait_for(state="visible", timeout=30000)
        except PlaywrightTimeout:
            # Save screenshot for debugging
            screenshot_path = f"/tmp/claude_debug_{implant_id[:8]}.png"
            await page.screenshot(path=screenshot_path)
            log.error("Timeout waiting for input. Screenshot saved to %s", screenshot_path)
            log.error("Page URL: %s", page.url)
            log.error("Page title: %s", await page.title())
            raise
        log.info("Session %s ready", implant_id[:12])

        session = BrowserSession(
            implant_id=implant_id,
            bridge_url=bridge_url,
            page=page,
            context=ctx,
            _browser=browser,
        )
        self._sessions[implant_id] = session
        return session

    async def send_message(self, implant_id: str, text: str) -> None:
        """Type a message into the Claude Code input and submit it."""
        session = self._sessions.get(implant_id)
        if not session or not session.page:
            raise RuntimeError(f"No open session for implant {implant_id[:12]}")

        page = session.page

        # Record current message count so we can detect the new response
        session._msg_count_at_send = await page.locator(MESSAGE_GROUP).count()

        # Wait for Claude to be idle (no interrupt button = not processing)
        await self._wait_until_idle(page, timeout=60.0)

        # Focus the input and clear it (fill() doesn't work on contenteditable)
        input_el = page.locator(INPUT_SELECTOR)
        await input_el.click()
        await page.keyboard.press("Control+a")  # select all (works in Firefox on all platforms)
        await page.keyboard.press("Backspace")  # delete

        # Use press_sequentially for ProseMirror which relies on keydown events
        await input_el.press_sequentially(text, delay=10)

        # Small pause to let the UI register the input
        await asyncio.sleep(0.3)

        # Click submit if available and not disabled, otherwise press Enter
        submit_btn = page.locator(SUBMIT_SELECTOR)
        if await submit_btn.count() > 0:
            disabled = await submit_btn.get_attribute("disabled")
            if disabled is None:
                await submit_btn.click()
            else:
                await input_el.press("Enter")
        else:
            await input_el.press("Enter")

        log.info("Sent message to %s (%d chars)", implant_id[:12], len(text))

    async def wait_for_response(
        self, implant_id: str, timeout: float = 120.0, poll_interval: float = 1.0
    ) -> str:
        """Wait for Claude to finish responding and return the response text.

        Detection strategy:
        1. Wait for processing to start (interrupt button or spinner appears)
        2. Wait for processing to end (interrupt button and spinner gone)
        3. Confirm response text has stabilized
        """
        session = self._sessions.get(implant_id)
        if not session or not session.page:
            raise RuntimeError(f"No open session for implant {implant_id[:12]}")

        page = session.page
        baseline = session._msg_count_at_send

        # Phase 1: wait for processing to start (interrupt button or spinner appears)
        log.info("Waiting for processing to start on %s...", implant_id[:12])
        try:
            await page.locator(f"{INTERRUPT_SELECTOR}, {SPINNER_SELECTOR}").first.wait_for(
                state="visible", timeout=10000
            )
        except PlaywrightTimeout:
            # Processing may have already started and finished very quickly,
            # or new messages appeared — check if we got a response
            new_count = await page.locator(MESSAGE_GROUP).count()
            if new_count <= baseline:
                log.warning("Processing didn't start on %s", implant_id[:12])

        # Phase 2: wait for processing to end
        log.info("Waiting for response to complete on %s...", implant_id[:12])
        last_text = ""
        stable_count = 0
        elapsed = 0.0

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

            # Done when: not processing AND text is stable for 2+ polls
            if not is_processing and stable_count >= 2:
                log.info(
                    "Response complete on %s (%d chars)",
                    implant_id[:12],
                    len(last_text),
                )
                return last_text

            # Fallback: text stable for 5+ polls even if processing state is unclear
            if stable_count >= 5:
                log.info(
                    "Response stable (fallback) on %s (%d chars)",
                    implant_id[:12],
                    len(last_text),
                )
                return last_text

        log.warning("Response timed out on %s, returning partial", implant_id[:12])
        return last_text

    async def send_and_receive(
        self, implant_id: str, text: str, timeout: float = 120.0
    ) -> str:
        """Send a message and wait for the response. Returns response text."""
        await self.send_message(implant_id, text)
        return await self.wait_for_response(implant_id, timeout=timeout)

    async def close_session(self, implant_id: str) -> None:
        """Close the browser for a specific implant."""
        session = self._sessions.pop(implant_id, None)
        if not session:
            return
        if session._browser:
            await session._browser.__aexit__(None, None, None)
        log.info("Closed session %s", implant_id[:12])

    async def close_all(self) -> None:
        """Close all browser sessions."""
        for implant_id in list(self._sessions):
            await self.close_session(implant_id)

    # -- Internal helpers ---------------------------------------------------

    async def _is_processing(self, page: Page) -> bool:
        """Check if Claude is currently processing (interrupt button or spinner visible)."""
        interrupt = page.locator(INTERRUPT_SELECTOR)
        if await interrupt.count() > 0 and await interrupt.is_visible():
            return True

        spinner = page.locator(SPINNER_SELECTOR)
        if await spinner.count() > 0 and await spinner.is_visible():
            return True

        # Shimmer animation on tool status text = still working
        shimmer = page.locator(SHIMMER_SELECTOR)
        if await shimmer.count() > 0 and await shimmer.is_visible():
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
        raise TimeoutError("Claude is still processing after timeout")

    async def _get_last_response_text(self, page: Page) -> str:
        """Extract text from the last assistant response in the conversation.

        Walks message groups backwards, skipping user messages (identified by
        the ml-auto right-aligned bubble).
        """
        messages = page.locator(MESSAGE_GROUP)
        count = await messages.count()
        if count == 0:
            return ""

        # Walk backwards to find the last non-user message
        for i in range(count - 1, -1, -1):
            msg = messages.nth(i)
            # User messages contain the ml-auto max-w-[85%] bubble
            user_parts = msg.locator(USER_MSG)
            if await user_parts.count() > 0:
                continue
            return (await msg.inner_text()).strip()

        return ""

    def get_session(self, implant_id: str) -> BrowserSession | None:
        return self._sessions.get(implant_id)

    @property
    def active_sessions(self) -> list[str]:
        return [
            sid
            for sid, s in self._sessions.items()
            if s.page and not s.page.is_closed()
        ]
