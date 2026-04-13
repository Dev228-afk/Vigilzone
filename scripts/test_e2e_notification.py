"""
End-to-End Notification Pipeline Verification Script
=====================================================

Simulates an AI alert and traces its lifecycle through:
  1. Redis Stream (publish)
  2. Stream consumption verification
  3. Django Channels group membership check
  4. Channel message delivery verification

Usage (from the monolith root, with venv activated):
    python scripts/test_e2e_notification.py

Environment:
    Reads REDIS_URL (or REDIS_HOST/REDIS_PORT) from services/backend/.env
    or from the root .env via the standard resolution chain.
"""

import json
import os
import sys
import time
import uuid

# ── Resolve project paths ────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MONOLITH_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_ROOT = os.path.join(MONOLITH_ROOT, "services", "backend")

# Load root .env first, then backend .env (backend overrides)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(MONOLITH_ROOT, ".env"), override=False)
    load_dotenv(os.path.join(BACKEND_ROOT, ".env"), override=True)
except ImportError:
    print("[WARN] python-dotenv not installed, relying on shell env vars")

# ── Redis connection ─────────────────────────────────────────────
try:
    import redis
except ImportError:
    print("[FAIL] redis-py not installed. Run: pip install redis")
    sys.exit(1)


def get_redis_client():
    """Create a Redis client from environment, matching the backend's logic."""
    url = os.getenv("REDIS_URL", "")
    if url:
        print(f"[INFO] Connecting via REDIS_URL: {url[:url.index('@') + 1] if '@' in url else url}...")
        return redis.from_url(url, decode_responses=True, socket_timeout=5)

    host = os.getenv("REDIS_HOST", "127.0.0.1")
    port = int(os.getenv("REDIS_PORT", "6379"))
    password = os.getenv("REDIS_PASSWORD", "")
    print(f"[INFO] Connecting via host={host} port={port}...")
    return redis.Redis(host=host, port=port, password=password or None,
                       decode_responses=True, socket_timeout=5)


def check_redis_connection(client):
    """Stage 0: Verify Redis connectivity."""
    print("\n── Stage 0: Redis Connectivity ──")
    try:
        pong = client.ping()
        print(f"  [PASS] Redis PING → {pong}")
        return True
    except redis.AuthenticationError as e:
        print(f"  [FAIL] Authentication failed: {e}")
        print("  [HINT] Check REDIS_URL password matches your Docker Redis config")
        return False
    except redis.ConnectionError as e:
        print(f"  [FAIL] Connection refused: {e}")
        print("  [HINT] Is Redis running? Check: docker ps | grep redis")
        return False


def publish_test_event(client, channel):
    """Stage 1: Publish a synthetic alert to the incident stream."""
    print("\n── Stage 1: Publish Synthetic Alert ──")

    event_id = f"e2e-test-{uuid.uuid4().hex[:12]}"
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    envelope = {
        "event": "alert.created",
        "timestamp": now_iso,
        "data": {
            "id": event_id,
            "camera_id": "cam_e2e_test",
            "type": "intrusion",
            "severity": 4,
            "timestamp": now_iso,
            "message": "E2E pipeline test — synthetic intrusion alert",
            "confidence": 0.99,
            "source_type": "synthetic_test",
            "evidence": {"keyframe_path": "", "clip_path": ""},
        },
    }

    entry_id = client.xadd(channel, {"payload": json.dumps(envelope)})
    stream_len = client.xlen(channel)
    print(f"  [PASS] Published event_id={event_id}")
    print(f"         stream_entry_id={entry_id}")
    print(f"         stream_length={stream_len}")
    return event_id, entry_id


def check_stream_state(client, channel):
    """Stage 2: Check stream and consumer group state."""
    print("\n── Stage 2: Stream & Consumer Group State ──")

    stream_len = client.xlen(channel)
    print(f"  Stream length: {stream_len}")

    try:
        groups = client.xinfo_groups(channel)
        if not groups:
            print("  [WARN] No consumer groups found. Is subscribe_incidents running?")
        for g in groups:
            print(f"  Group: {g.get('name', '?')}")
            print(f"    consumers: {g.get('consumers', 0)}")
            print(f"    pending: {g.get('pending', 0)}")
            print(f"    last-delivered-id: {g.get('last-delivered-id', '?')}")
    except redis.ResponseError as e:
        if "no such key" in str(e).lower():
            print(f"  [WARN] Stream '{channel}' does not exist yet")
        else:
            print(f"  [WARN] Could not read group info: {e}")


def check_subscriber_heartbeat(client, channel):
    """Stage 3: Check if the subscriber process is alive."""
    print("\n── Stage 3: Subscriber Heartbeat ──")

    key = f"{channel}:subscriber_status"
    raw = client.get(key)
    if not raw:
        print("  [WARN] No subscriber heartbeat found.")
        print("  [HINT] Is `python manage.py subscribe_incidents` running?")
        return False

    try:
        status = json.loads(raw)
        print(f"  Phase: {status.get('phase', '?')}")
        print(f"  PID: {status.get('pid', '?')}")
        print(f"  Updated at: {status.get('updated_at', '?')}")
        print(f"  Processed count: {status.get('processed_count', '?')}")
        print(f"  Last event ID: {status.get('last_event_id', '?')}")
        print(f"  Last error: {status.get('last_error', '(none)')}")
        print(f"  [PASS] Subscriber is alive")
        return True
    except Exception as e:
        print(f"  [WARN] Could not parse heartbeat: {e}")
        return False


def check_channels_group(client):
    """Stage 4: Check if any WebSocket clients are in channel groups."""
    print("\n── Stage 4: Django Channels Group Membership ──")

    prefix = "asgi:"
    # Scan for tenant notification groups
    cursor = 0
    groups_found = []
    while True:
        cursor, keys = client.scan(cursor, match=f"{prefix}group:tenant_notifications_*", count=100)
        for key in keys:
            members = client.zrange(key, 0, -1)
            group_name = key.replace(f"{prefix}group:", "")
            groups_found.append((group_name, len(members)))
        if cursor == 0:
            break

    if not groups_found:
        print("  [WARN] No tenant notification groups found in Redis.")
        print("  [HINT] Open the frontend in a browser and login to create a WS connection.")
        return False

    for name, count in groups_found:
        status = "PASS" if count > 0 else "WARN"
        print(f"  [{status}] {name}: {count} connected channel(s)")
    return any(count > 0 for _, count in groups_found)


def check_ai_publisher_status(client):
    """Stage 5: Check if the AI publisher reported success."""
    print("\n── Stage 5: AI Publisher Last Status ──")
    print("  [INFO] AI publisher status is only visible from the AI service API:")
    print("         GET http://127.0.0.1:8080/api/v1/health → redis_transport")
    print("  [HINT] If redis_transport.ready == false, the AI publisher cannot connect.")
    print("         Ensure AI_REDIS_URL or AI_USE_REDIS_PUBLISH=1 is set.")


def main():
    channel = os.getenv("AI_INCIDENT_CHANNEL", "vigilzone.ai.incidents")

    print("=" * 60)
    print("  VigilZone E2E Notification Pipeline Verification")
    print("=" * 60)
    print(f"  Channel: {channel}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    client = get_redis_client()

    # Stage 0
    if not check_redis_connection(client):
        print("\n[ABORT] Cannot proceed without Redis connectivity.")
        sys.exit(1)

    # Stage 1
    event_id, entry_id = publish_test_event(client, channel)

    # Stage 2
    check_stream_state(client, channel)

    # Stage 3
    subscriber_alive = check_subscriber_heartbeat(client, channel)

    # Stage 4
    ws_clients_present = check_channels_group(client)

    # Stage 5
    check_ai_publisher_status(client)

    # If subscriber is alive, wait briefly and re-check
    if subscriber_alive:
        print("\n── Stage 6: Wait for Subscriber Processing ──")
        print("  Waiting 3 seconds for subscriber to process the event...")
        time.sleep(3)
        check_subscriber_heartbeat(client, channel)

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Redis: CONNECTED")
    print(f"  Test event published: {event_id}")
    print(f"  Subscriber alive: {'YES' if subscriber_alive else 'NO — start subscribe_incidents'}")
    print(f"  WS clients connected: {'YES' if ws_clients_present else 'NO — open browser & login'}")

    if subscriber_alive and ws_clients_present:
        print("\n  ✅ Pipeline looks healthy. Check the browser bell icon for the test notification.")
    elif subscriber_alive:
        print("\n  ⚠️  Subscriber is running but no WS clients. Open browser to test UI delivery.")
    else:
        print("\n  ❌ Subscriber is NOT running. Start it:")
        print("     cd services/backend")
        print("     python manage.py subscribe_incidents")

    client.close()


if __name__ == "__main__":
    main()
