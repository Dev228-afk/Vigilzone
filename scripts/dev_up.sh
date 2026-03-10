#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  VigilZone — start ALL services locally (no Docker)
#  Usage:  ./scripts/dev_up.sh          (from repo root)
#  Stop:   Ctrl+C  (kills every child process)
# ──────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── Resolve Python ────────────────────────────────────────────
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3 &>/dev/null; then
  PY=python3
else
  PY=python
fi

# ── Colours ───────────────────────────────────────────────────
CYAN='\033[0;36m'; GREEN='\033[0;32m'; NC='\033[0m'
info() { echo -e "${CYAN}[dev_up]${NC} $*"; }

# ── Trap: kill all children on Ctrl+C ─────────────────────────
PIDS=()
cleanup() {
  info "Shutting down…"
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null
  info "Done."
}
trap cleanup EXIT INT TERM

# ── 1. Django backend (port 8000) ─────────────────────────────
info "Starting Django backend on :8000 …"
(
  cd "$ROOT/services/backend"
  "$PY" manage.py migrate --noinput 2>&1 | sed 's/^/  [django] /'
  "$PY" manage.py runserver 0.0.0.0:8000 2>&1 | sed 's/^/  [django] /'
) &
PIDS+=($!)

# ── 2. AI module (port 8080) ─────────────────────────────────
info "Starting AI module on :8080 …"
(
  cd "$ROOT/services/ai"
  "$PY" run.py 2>&1 | sed 's/^/  [ai]     /'
) &
PIDS+=($!)

# ── 3. UI dev server (port 5000) ─────────────────────────────
info "Starting Vite UI on :5000 …"
(
  cd "$ROOT/web/ui"
  npm install --silent 2>&1 | sed 's/^/  [ui]     /'
  npm run dev 2>&1 | sed 's/^/  [ui]     /'
) &
PIDS+=($!)

# ── Wait ──────────────────────────────────────────────────────
echo ""
info "${GREEN}All services starting…${NC}"
echo ""
echo "  Web UI:   http://localhost:5000"
echo "  API:      http://localhost:8000/api/"
echo "  AI:       http://localhost:8080"
echo ""
info "Press Ctrl+C to stop all."
echo ""

wait
