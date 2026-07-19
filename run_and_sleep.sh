#!/bin/bash
# 1stTix checker wrapper for a personal Mac that sleeps.
#
# Runs the checker, then puts the Mac back to sleep ONLY when it looks like the
# machine woke on its own for this scheduled run and nobody is using it — so a
# mid-session 30-min timer never sleeps a laptop you're actively working on.
#
# Wake scheduling itself is done separately with `sudo pmset repeat ...` (see
# the README/notes) because that needs admin rights.

VENV_PY="/Users/rsua/_CLAUDE_PLAY/.ftvenv/bin/python"
REPO="/Users/rsua/_CLAUDE_PLAY/firsttix-checker"

# --- Tunables ---
WOKE_WITHIN_SECS=300   # consider it a "scheduled wake" if we woke <5 min ago
IDLE_MIN_SECS=120      # only sleep if no keyboard/mouse input for >2 min

# --- Run the checker (env vars come from the launchd plist) ---
cd "$REPO" || exit 1
"$VENV_PY" "$REPO/firsttix_checker.py" --fast
run_status=$?

# --- Decide whether to sleep back ---
now=$(date +%s)

# seconds since the last wake-from-sleep (first "sec = N"; avoid the usec value)
wake=$(sysctl -n kern.waketime 2>/dev/null | grep -oE 'sec = [0-9]+' | head -1 | grep -oE '[0-9]+')
since_wake=$(( now - ${wake:-0} ))

# seconds of human input idle
idle=$(ioreg -c IOHIDSystem 2>/dev/null | awk '/HIDIdleTime/ {print int($NF/1000000000); exit}')
idle=${idle:-0}

echo "[run_and_sleep] status=$run_status since_wake=${since_wake}s idle=${idle}s"

if [ "$since_wake" -lt "$WOKE_WITHIN_SECS" ] && [ "$idle" -gt "$IDLE_MIN_SECS" ]; then
    echo "[run_and_sleep] woke recently and unattended -> sleeping"
    # pmset sleepnow works for the console user; if your macOS asks for admin,
    # swap for: osascript -e 'tell application "System Events" to sleep'
    pmset sleepnow
else
    echo "[run_and_sleep] leaving awake (in-use or not a scheduled wake)"
fi
