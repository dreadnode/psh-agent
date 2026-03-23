#!/bin/bash
# Start Chrome with remote debugging enabled for CDP connection
# This script kills any existing Chrome instances first

set -e

PORT="${1:-9222}"
CHROME_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# Chrome requires a NON-default data directory for remote debugging
# We copy essential profile files to a separate debug directory
SOURCE_PROFILE="$HOME/Library/Application Support/Google/Chrome"
DEBUG_PROFILE="$HOME/Library/Application Support/Google/Chrome-Debug"

echo "=== Chrome CDP Debug Launcher ==="
echo ""

# Check if Chrome is running
if pgrep -f "Google Chrome" > /dev/null 2>&1; then
    echo "⚠️  Chrome is currently running."
    echo "   To enable CDP debugging, Chrome must be restarted."
    echo ""
    read -p "Kill existing Chrome and restart with debugging? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Killing Chrome processes..."
        pkill -f "Google Chrome" || true
        sleep 2
    else
        echo "Aborted. Please quit Chrome manually and re-run this script."
        exit 1
    fi
fi

# Copy profile cookies/login state if debug profile doesn't exist or is old
if [ ! -d "$DEBUG_PROFILE/Default" ] || [ "$SOURCE_PROFILE/Default/Cookies" -nt "$DEBUG_PROFILE/Default/Cookies" ] 2>/dev/null; then
    echo "Syncing profile data to debug directory..."
    mkdir -p "$DEBUG_PROFILE/Default"

    # Copy essential files for maintaining login state
    for f in Cookies "Login Data" "Web Data" Preferences "Secure Preferences" "Local State"; do
        if [ -e "$SOURCE_PROFILE/Default/$f" ]; then
            cp -f "$SOURCE_PROFILE/Default/$f" "$DEBUG_PROFILE/Default/" 2>/dev/null || true
        fi
    done

    # Copy Local State from root
    if [ -e "$SOURCE_PROFILE/Local State" ]; then
        cp -f "$SOURCE_PROFILE/Local State" "$DEBUG_PROFILE/" 2>/dev/null || true
    fi

    echo "Profile synced."
fi

echo "Starting Chrome with --remote-debugging-port=$PORT ..."
echo "Using debug profile: $DEBUG_PROFILE"
"$CHROME_APP" --remote-debugging-port="$PORT" --user-data-dir="$DEBUG_PROFILE" &

# Wait for DevTools to become available
echo "Waiting for DevTools server..."
for i in {1..10}; do
    sleep 1
    if curl -s "http://localhost:$PORT/json/version" > /dev/null 2>&1; then
        echo ""
        echo "✓ Chrome DevTools listening on port $PORT"
        echo ""
        curl -s "http://localhost:$PORT/json/version" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Browser: {d.get(\"Browser\",\"?\")}'); print(f'  WebSocket: {d.get(\"webSocketDebuggerUrl\",\"?\")}')"
        echo ""
        echo "You can now run the browser bridge with:"
        echo "  python browser_bridge_local.py --connect-existing --cdp-url http://localhost:$PORT"
        exit 0
    fi
    echo -n "."
done

echo ""
echo "❌ Timeout waiting for DevTools server on port $PORT"
echo "   Check if Chrome started correctly."
exit 1
