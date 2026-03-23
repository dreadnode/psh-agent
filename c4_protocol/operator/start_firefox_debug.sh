#!/bin/bash
# Start Firefox with remote debugging enabled for CDP connection
# This script kills any existing Firefox instances first

set -e

PORT="${1:-9222}"
FIREFOX_APP="/Applications/Firefox.app/Contents/MacOS/firefox"

echo "=== Firefox CDP Debug Launcher ==="
echo ""

# Check if Firefox is running
if pgrep -f "firefox" > /dev/null 2>&1; then
    echo "⚠️  Firefox is currently running."
    echo "   To enable CDP debugging, Firefox must be restarted."
    echo ""
    read -p "Kill existing Firefox and restart with debugging? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Killing Firefox processes..."
        pkill -f "firefox" || true
        sleep 2
    else
        echo "Aborted. Please quit Firefox manually and re-run this script."
        exit 1
    fi
fi

echo "Starting Firefox with --remote-debugging-port=$PORT ..."
"$FIREFOX_APP" --remote-debugging-port="$PORT" &

# Wait for DevTools to become available
echo "Waiting for DevTools server..."
for i in {1..15}; do
    sleep 1
    if curl -s "http://localhost:$PORT/json/version" > /dev/null 2>&1; then
        echo ""
        echo "✓ Firefox DevTools listening on port $PORT"
        echo ""
        curl -s "http://localhost:$PORT/json/version" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Browser: {d.get(\"Browser\",\"?\")}')" 2>/dev/null || echo "  (DevTools responding)"
        echo ""
        echo "Now:"
        echo "  1. Log into claude.ai in Firefox if needed"
        echo "  2. Run the browser bridge:"
        echo "     python browser_bridge_local.py --connect-existing --cdp-url http://localhost:$PORT"
        exit 0
    fi
    echo -n "."
done

echo ""
echo "❌ Timeout waiting for DevTools server on port $PORT"
echo "   Firefox may not support the standard DevTools protocol."
echo ""
echo "Alternative: Try Chrome instead with ./start_chrome_debug.sh"
exit 1
