#!/usr/bin/env bash
# Regenerate the dashboard screenshots the README embeds.
#
# Uses headless Chrome, which is already present on most machines, rather than
# adding Playwright or Puppeteer for five images. Screenshots that can only be
# produced by hand drift silently from the dashboard; a script keeps them
# reproducible, which is the same standard the metrics in this repo are held to.
#
# Prerequisites: backend on :8000 and the Vite dev server on :5173.
#
#   .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
#   (cd frontend && npm run dev)
#
# Usage:
#   bash scripts/capture_screenshots.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/docs/screenshots"
BASE="${BASE_URL:-http://localhost:5173}"

# Vite binds IPv6 only, so localhost resolves while 127.0.0.1 is refused.
CHROME="${CHROME_PATH:-C:/Program Files/Google/Chrome/Application/chrome.exe}"
if [ ! -f "$CHROME" ]; then
  echo "Chrome not found at: $CHROME" >&2
  echo "Set CHROME_PATH to your Chrome or Edge binary." >&2
  exit 1
fi

if ! curl -s -m 5 -o /dev/null "$BASE"; then
  echo "Dev server not reachable at $BASE. Start it first." >&2
  exit 1
fi

mkdir -p "$OUT"

# name -> route. Names match what README.md embeds.
capture() {
  local name="$1" route="$2"
  # virtual-time-budget lets the SPA render and fetch before the frame is taken;
  # without it the capture can land on an empty shell.
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --window-size=1440,1800 --virtual-time-budget=9000 \
    --screenshot="$OUT/$name.png" "$BASE$route" >/dev/null 2>&1
  local size
  size=$(stat -c%s "$OUT/$name.png" 2>/dev/null || echo 0)
  if [ "$size" -lt 20000 ]; then
    echo "  WARNING $name.png is only $size bytes - it may have captured an empty page" >&2
  fi
  printf "  %-14s %-12s %8s bytes\n" "$name" "$route" "$size"
}

echo "capturing from $BASE"
capture overview      "/"
capture agents        "/agents"
capture retrieval     "/retrieval"
capture judges        "/judges"
capture runs          "/runs"
capture review-queue  "/review"
echo "done -> docs/screenshots/"
