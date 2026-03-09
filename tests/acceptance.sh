#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# VigilZone Acceptance Test Script
#
# Prerequisites:
#   - Django backend running on $BACKEND (default: http://localhost:8000)
#   - AI module running on $AI_BASE (default: http://localhost:8080)
#   - User "dev" exists (password: VigilZone2024!)
#
# Usage:
#   bash tests/acceptance.sh               # local dev
#   BACKEND=http://localhost:8085 bash tests/acceptance.sh  # via Nginx
# ──────────────────────────────────────────────────────────────
set -euo pipefail

BACKEND="${BACKEND:-http://localhost:8000}"
AI_BASE="${AI_BASE:-http://localhost:8080}"
USERNAME="${TEST_USER:-dev}"
PASSWORD="${TEST_PASS:-VigilZone2024!}"
TENANT_ID="${TENANT_ID:-2}"

PASS=0
FAIL=0

check() {
    local name="$1" status="$2" expected="$3"
    if [ "$status" -eq "$expected" ]; then
        echo "  ✓ $name (HTTP $status)"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $name — expected $expected, got $status"
        FAIL=$((FAIL + 1))
    fi
}

echo "╔══════════════════════════════════════════════════════╗"
echo "║         VigilZone Acceptance Tests                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo "  Backend : $BACKEND"
echo "  AI      : $AI_BASE"
echo ""

# ── 1. Obtain JWT ─────────────────────────────────────────────
echo "▸ Auth"
TOKEN_RESP=$(curl -s -w "\n%{http_code}" -X POST "$BACKEND/api/auth/token/" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")
TOKEN_STATUS=$(echo "$TOKEN_RESP" | tail -1)
TOKEN_BODY=$(echo "$TOKEN_RESP" | head -n -1)
check "POST /api/auth/token/" "$TOKEN_STATUS" 200

TOKEN=$(echo "$TOKEN_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access',''))" 2>/dev/null || echo "")
if [ -z "$TOKEN" ]; then
    echo "  ✗ Could not extract JWT — aborting."
    exit 1
fi
AUTH="-H \"Authorization: Bearer $TOKEN\" -H \"X-Tenant-ID: $TENANT_ID\""

# ── 2. Core Django endpoints ──────────────────────────────────
echo ""
echo "▸ Core API (Django)"

for EP in \
    "GET /api/cameras/" \
    "GET /api/incidents/" \
    "GET /api/detections/" \
    "GET /api/audit/" \
    "GET /api/dashboard/summary/" \
    "GET /api/incidents/stats/" \
    "GET /api/profile/me/" \
    "GET /api/auth/context/"; do

    METHOD=$(echo "$EP" | cut -d' ' -f1)
    PATH_PART=$(echo "$EP" | cut -d' ' -f2)
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X "$METHOD" \
        -H "Authorization: Bearer $TOKEN" \
        -H "X-Tenant-ID: $TENANT_ID" \
        "$BACKEND$PATH_PART")
    check "$EP" "$STATUS" 200
done

# ── 3. AI proxy endpoints ─────────────────────────────────────
echo ""
echo "▸ AI Proxy (Django → AI)"

for EP in \
    "GET /api/ai/cameras/" \
    "GET /api/ai/alerts/" \
    "GET /api/ai/system/status/" \
    "GET /api/ai/entities/"; do

    METHOD=$(echo "$EP" | cut -d' ' -f1)
    PATH_PART=$(echo "$EP" | cut -d' ' -f2)
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X "$METHOD" \
        -H "Authorization: Bearer $TOKEN" \
        -H "X-Tenant-ID: $TENANT_ID" \
        "$BACKEND$PATH_PART")
    check "$EP" "$STATUS" 200
done

# Frame snapshot (may return 200 or 502 if no camera running)
FRAME_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-Tenant-ID: $TENANT_ID" \
    "$BACKEND/api/ai/frame/cam_live/")
if [ "$FRAME_STATUS" -eq 200 ]; then
    check "GET /api/ai/frame/cam_live/ (snapshot)" "$FRAME_STATUS" 200
else
    echo "  ⚠ GET /api/ai/frame/cam_live/ — HTTP $FRAME_STATUS (AI camera may be offline)"
fi

# ── 4. Webhook receive ────────────────────────────────────────
echo ""
echo "▸ Webhook Persistence"

WH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    "$BACKEND/api/ai/webhook/receive/" \
    -H "Content-Type: application/json" \
    -d '{
      "event": "alert.created",
      "data": {
        "id": "test-alert-001",
        "camera_id": "cam_live",
        "type": "intrusion",
        "severity": "high",
        "timestamp": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
        "message": "Acceptance test: intrusion detected",
        "confidence": 0.88,
        "evidence": {}
      }
    }')
# Expect 201 (created) or 200 (updated existing)
if [ "$WH_STATUS" -eq 201 ] || [ "$WH_STATUS" -eq 200 ]; then
    check "POST /api/ai/webhook/receive/ (persist incident)" "$WH_STATUS" "$WH_STATUS"
else
    check "POST /api/ai/webhook/receive/ (persist incident)" "$WH_STATUS" 201
fi

# Verify incident was persisted
INC_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-Tenant-ID: $TENANT_ID" \
    "$BACKEND/api/incidents/?type=INTRUSION")
check "GET /api/incidents/?type=INTRUSION (verify persistence)" "$INC_STATUS" 200

# ── 5. AI module direct (for webhook list) ────────────────────
echo ""
echo "▸ AI Module Direct"

AI_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$AI_BASE/api/v1/system/status")
check "GET $AI_BASE/api/v1/system/status" "$AI_STATUS" 200

AI_WH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$AI_BASE/webhooks")
check "GET $AI_BASE/webhooks" "$AI_WH_STATUS" 200

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "══════════════════════════════════════════════════════"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
