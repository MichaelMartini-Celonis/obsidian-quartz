#!/usr/bin/env bash
# Run the YouTube transcript extraction in the background, gently, with logging.
#
# It (1) enqueues the sources into the backlog, then (2) drains the backlog in a
# loop with delays + exponential backoff so YouTube does not block us. Safe to
# stop/restart at any time — progress lives in imports/youtube-backlog.json.
#
#   scripts/youtube-transcribe-bg.sh           # enqueue + run in background
#   scripts/youtube-transcribe-bg.sh run       # skip enqueue, just drain
#   tail -f imports/youtube-import.log         # watch progress
#   scripts/.venv/bin/python scripts/import-youtube.py status   # counts
#
# After it has made progress, index the new transcripts into the search engine:
#   scripts/.venv/bin/python -m search.cli index --roots transcripts
set -euo pipefail

cd "$(dirname "$0")/.."
PY="scripts/.venv/bin/python -u"   # -u: unbuffered, so the log updates live
LOG="imports/youtube-import.log"
mkdir -p imports

if [[ "${1:-}" != "run" ]]; then
  echo "[$(date '+%F %T')] enqueue" | tee -a "$LOG"
  $PY scripts/import-youtube.py enqueue >>"$LOG" 2>&1 || true
fi

echo "[$(date '+%F %T')] starting background run (loop, sleep 3s +2s jitter)" | tee -a "$LOG"
nohup $PY scripts/import-youtube.py run --loop --sleep 3 --jitter 2 >>"$LOG" 2>&1 &
pid=$!
echo "started pid $pid — logging to $LOG"
echo "stop with: kill $pid"
