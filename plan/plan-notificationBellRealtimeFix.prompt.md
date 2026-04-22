Fix bell realtime update/count fidelity, empty notification details, and chime playback.

Pending Task 1:
Patch useNotifications.ts for UUID-safe IDs:
- alert_id and markAsRead arrays should be string-compatible.
- Normalize IDs via String(...) before dedupe, unread updates, and mark-read filtering.

Pending Task 2:
Patch NotificationBell.tsx:
- accept string IDs for mark-read.
- parse incident_id as string/number and route reliably.

Pending Task 3:
Patch backend notifications_list fallback composition:
- non-empty title/message derived from payload.data/incident fields if payload keys missing.

Pending Task 4:
Add audio unlock flow:
- call unlock on first user interaction in notification hook lifecycle.

Priority Information:
- Highest priority: UUID-safe frontend ID handling (this likely fixes realtime bell + count drift immediately).
- Next: backend message fallback for empty card details.
- Then: audio unlock polish.

Next Action:
Apply the above patches and run focused frontend hook tests + backend notification API tests to verify all four user-reported symptoms are resolved.
