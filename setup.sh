#!/bin/bash
# 1stTix Checker - Setup Script
# This script installs the periodic checker on your Mac

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.rsua.firsttix-checker.plist"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "==================================="
echo "1stTix Checker Setup — San Diego"
echo "==================================="

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install it first."
    echo "   You can install it via: brew install python3"
    exit 1
fi
echo "✓ Python 3 found"

# Install required Python packages
echo ""
echo "Installing required Python packages..."
python3 -m pip install --quiet --upgrade requests beautifulsoup4
echo "✓ Python packages installed"

# Make the main script executable
chmod +x "$SCRIPT_DIR/firsttix_checker.py"
echo "✓ Made checker script executable"

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$HOME/Library/LaunchAgents"

# Unload existing job if present
if launchctl list | grep -q "com.rsua.firsttix-checker"; then
    echo ""
    echo "Unloading existing job..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Copy plist to LaunchAgents
cp "$PLIST_SRC" "$PLIST_DEST"
echo "✓ Copied plist to ~/Library/LaunchAgents/"

# Load the job
launchctl load "$PLIST_DEST"
echo "✓ Loaded launchd job"

echo ""
echo "==================================="
echo "✅ Setup Complete!"
echo "==================================="
echo ""
echo "The checker will now run:"
echo "  • Immediately when you log in"
echo "  • Every 30 minutes while your Mac is on"
echo ""
echo "Files:"
echo "  • Script:    $SCRIPT_DIR/firsttix_checker.py"
echo "  • Denylist:  $SCRIPT_DIR/denylist.txt"
echo "  • Results:   $SCRIPT_DIR/firsttix_shows.json"
echo "  • Log:       $SCRIPT_DIR/firsttix.log"
echo ""
echo "To manually run the checker now:"
echo "  python3 $SCRIPT_DIR/firsttix_checker.py --fast"
echo ""
echo "To uninstall:"
echo "  launchctl unload ~/Library/LaunchAgents/$PLIST_NAME"
echo "  rm ~/Library/LaunchAgents/$PLIST_NAME"
