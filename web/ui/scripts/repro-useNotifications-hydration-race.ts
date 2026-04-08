import assert from 'node:assert/strict';

import {
  mergeHydratedNotifications,
  mergeHydratedUnreadCount,
  type Notification,
} from '../client/src/hooks/useNotifications';

const websocketNotification: Notification = {
  id: 'alert-77',
  type: 'notification',
  notification_type: 'incident',
  title: 'Race Condition Alert',
  message: 'Arrived before hydration',
  alert_id: 77,
  incident_id: 33,
  created_at: '2026-03-28T10:00:00Z',
  is_read: false,
};

const mergedNotifications = mergeHydratedNotifications([websocketNotification], []);
const mergedUnreadCount = mergeHydratedUnreadCount(1, 0);

assert.equal(mergedNotifications.length, 1, 'hydration should not discard an already-received websocket notification');
assert.equal(mergedNotifications[0].alert_id, 77, 'the existing websocket notification should be preserved');
assert.equal(mergedUnreadCount, 1, 'hydration should not reset unread count below the websocket state');

const updatedNotification: Notification = {
  ...websocketNotification,
  message: 'Updated message with more detail',
};

const updatedMerge = mergeHydratedNotifications(mergedNotifications, [updatedNotification]);

assert.equal(updatedMerge.length, 1, 'hydrated updates should merge into the existing notification instead of duplicating');
assert.equal(updatedMerge[0].message, 'Updated message with more detail', 'the merged notification should keep the newest payload');

console.log('useNotifications hydration race repro passed');
