#!/bin/bash
# Start Chrome with remote debugging enabled for PDV token auto-refresh
#
# Usage: ./scripts/start-chrome-debug.sh
#
# After Chrome starts:
# 1. Navigate to https://insights.example.com
# 2. Log in with your YourCompany credentials
# 3. The backend will automatically extract the token

echo "Starting Chrome with remote debugging on port 9222..."
echo ""
echo "After Chrome opens:"
echo "  1. Go to https://insights.example.com"
echo "  2. Log in with your credentials"
echo "  3. The PDV backend will auto-refresh tokens"
echo ""

# Check if Chrome is already running with debug port
if curl -s http://localhost:9222/json >/dev/null 2>&1; then
    echo "✓ Chrome debug port already active on localhost:9222"
    echo ""
    echo "Checking for insights.example.com tab..."
    TABS=$(curl -s http://localhost:9222/json 2>/dev/null)
    if echo "$TABS" | grep -q "insights.example.com"; then
        echo "✓ Found insights.example.com tab - ready for token extraction"
    else
        echo "⚠ No insights.example.com tab found"
        echo "  Please navigate to https://insights.example.com and log in"
    fi
    exit 0
fi

# macOS
if [[ "$OSTYPE" == "darwin"* ]]; then
    /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
        --remote-debugging-port=9222 \
        --user-data-dir="$HOME/.chrome-debug-profile" \
        "https://insights.example.com" &
# Linux
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    google-chrome \
        --remote-debugging-port=9222 \
        --user-data-dir="$HOME/.chrome-debug-profile" \
        "https://insights.example.com" &
# Windows (Git Bash/WSL)
else
    echo "Please start Chrome manually with:"
    echo '  "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222'
    exit 1
fi

echo ""
echo "Chrome started. Waiting for debug port..."
sleep 3

if curl -s http://localhost:9222/json >/dev/null 2>&1; then
    echo "✓ Chrome debug port active on localhost:9222"
else
    echo "⚠ Could not connect to Chrome debug port"
    echo "  Make sure no other Chrome instances are running"
fi
