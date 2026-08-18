#!/usr/bin/env bash
# Drive `search enrich` to completion across restarts.
#
# Enriching the whole corpus takes hours, and a job that long does not reliably
# survive: the OS reaper has ended several multi-hour runs in this repository
# mid-flight. Nothing is lost when it does — every document is written to
# `doc_enrichment` as it completes, keyed by content hash, so a fresh run simply
# skips what is already there. The only thing missing was something to notice the
# process had died and start it again.
#
# Stops when the backlog is empty, or when a pass adds nothing (a real failure,
# e.g. the gateway being unreachable, rather than a killed process — retrying
# that in a tight loop would just burn the afternoon).
#
# Usage (from ~/docs):
#   scripts/enrich-loop.sh              # until the backlog is drained
#   MAX_PASSES=3 scripts/enrich-loop.sh
set -uo pipefail
cd "$(dirname "$0")/.."

PY=scripts/.venv/bin/python
MAX_PASSES=${MAX_PASSES:-40}
LOG=${LOG:-imports/enrich-loop.log}

remaining() {
  $PY - <<'EOF'
import duckdb
try:
    con = duckdb.connect("search/index.duckdb", read_only=True)
    print(con.execute("""
        SELECT count(*) FROM documents
        WHERE doc_id NOT IN (SELECT doc_id FROM doc_enrichment)
    """).fetchone()[0])
except Exception:
    print(-1)   # index locked by the pass that just started; treat as unknown
EOF
}

for ((pass = 1; pass <= MAX_PASSES; pass++)); do
  before=$(remaining)
  if [ "$before" = "0" ]; then
    echo "[loop] backlog empty after $((pass - 1)) pass(es)" | tee -a "$LOG"
    exit 0
  fi
  echo "[loop] pass $pass: $before documents remaining  ($(date '+%F %T'))" | tee -a "$LOG"
  $PY -u -m search.cli enrich >>"$LOG" 2>&1
  after=$(remaining)
  echo "[loop] pass $pass ended: $before -> $after" | tee -a "$LOG"
  if [ "$after" = "$before" ]; then
    echo "[loop] no progress; stopping (check the gateway)" | tee -a "$LOG"
    exit 1
  fi
  sleep 5
done
echo "[loop] hit MAX_PASSES=$MAX_PASSES with work left" | tee -a "$LOG"
